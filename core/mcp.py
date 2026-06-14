"""
P2-E / P5.11: MCP (Model Context Protocol) Adapter

连接 stdio 或 streamable HTTP MCP 服务器，将其工具按需注入为 Archer 技能。
所有 MCP 工具调用仍经过 Policy Layer 和 ToolRuntime。

工具命名：{server_name}__{tool_name}

archer.toml 示例见 docs/p5-mcp-integration-design.md
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import threading
import types
from collections import OrderedDict
from collections.abc import Iterator, Mapping
from typing import Any

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    _MCP_AVAILABLE = True
except ImportError:
    ClientSession = None  # type: ignore[assignment,misc]
    StdioServerParameters = None  # type: ignore[assignment,misc]
    stdio_client = None  # type: ignore[assignment]
    _MCP_AVAILABLE = False


def _fn_name(server: str, tool: str) -> str:
    """生成合法的 function name：server__tool（双下划线分隔）。"""
    return f"{server}__{tool}"


def _normalize_server_config(raw: dict, defaults: dict | None = None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name", "")).strip()
    if not name:
        return None
    cfg = dict(defaults or {})
    cfg.update(raw)
    cfg["name"] = name
    transport = str(cfg.get("transport", "stdio")).strip().lower()
    cfg["transport"] = transport
    if transport == "stdio":
        if not str(cfg.get("command", "")).strip():
            return None
    elif transport in {"streamable_http", "http", "remote"}:
        cfg["transport"] = "streamable_http"
        if not str(cfg.get("url", "")).strip():
            return None
    else:
        return None
    cfg["reconnect"] = cfg.get("reconnect", True) is not False
    return cfg


def _resolve_auth_token(cfg: dict) -> str:
    env_key = str(cfg.get("auth_token_env", "")).strip()
    if env_key:
        token = os.environ.get(env_key, "").strip()
        if token:
            return token
    return str(cfg.get("auth_token", "")).strip()


def _build_http_headers(cfg: dict) -> dict[str, str]:
    headers: dict[str, str] = {}
    raw_headers = cfg.get("headers") or {}
    if isinstance(raw_headers, dict):
        headers.update({str(k): str(v) for k, v in raw_headers.items()})
    auth_type = str(cfg.get("auth_type", "none")).strip().lower()
    token = _resolve_auth_token(cfg)
    if auth_type == "bearer" and token:
        headers["Authorization"] = f"Bearer {token}"
    elif auth_type == "header" and token:
        header_name = str(cfg.get("auth_header", "Authorization")).strip() or "Authorization"
        headers[header_name] = token
    return headers


def _build_http_client(cfg: dict):
    import httpx

    timeout_s = float(cfg.get("timeout_s", 45))
    return httpx.AsyncClient(headers=_build_http_headers(cfg), timeout=timeout_s)


class MCPDeferredSkillRegistry(Mapping[str, Any]):
    """Meta-first MCP tool registry; modules materialize on first access."""

    def __init__(self, manager: MCPManager, tool_infos: dict[str, dict]):
        self._manager = manager
        self._infos = dict(tool_infos)
        self._modules: OrderedDict[str, Any] = OrderedDict()

    def __getitem__(self, name: str) -> Any:
        if name not in self._infos:
            raise KeyError(name)
        if name in self._modules:
            self._modules.move_to_end(name)
            return self._modules[name]
        mod = _make_module(self._infos[name], self._manager)
        self._modules[name] = mod
        self._modules.move_to_end(name)
        while len(self._modules) > 10:
            self._modules.popitem(last=False)
        return mod

    def __iter__(self) -> Iterator[str]:
        return iter(self._infos)

    def __len__(self) -> int:
        return len(self._infos)

    def __contains__(self, name: object) -> bool:
        return name in self._infos

    def get(self, name: str, default: Any = None) -> Any:
        if name not in self._infos:
            return default
        return self[name]

    def metas(self) -> dict[str, Any]:
        from skills.meta import SkillMeta

        out: dict[str, SkillMeta] = {}
        for key, info in self._infos.items():
            out[key] = SkillMeta(
                name=key,
                description=f"[MCP:{info['server']}] {info.get('description') or key}",
                risk="medium",
                auto_trigger=False,
            )
        return out

    def module_count(self) -> int:
        return len(self._modules)


class MCPManager:
    """
    管理多个 MCP server 连接。

    - 后台 asyncio 事件循环运行在独立 daemon 线程中。
    - 对外提供同步接口，REPL 主循环无需感知 async。
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._sessions: dict[str, Any] = {}
        self._exit_stack: Any = None
        self._tools: dict[str, dict] = {}
        self._server_configs: dict[str, dict] = {}
        self._reconnect_attempts = 2
        self.ready: bool = False

    def start(self, server_configs: list[dict], timeout: float = 30.0, *, mcp_cfg: dict | None = None) -> None:
        if not _MCP_AVAILABLE:
            raise ImportError("mcp 包未安装。请运行：pip install mcp")
        defaults = mcp_cfg or {}
        self._reconnect_attempts = int(defaults.get("reconnect_attempts", 2))
        normalized = [
            cfg for cfg in (
                _normalize_server_config(raw, defaults)
                for raw in server_configs
            )
            if cfg is not None
        ]
        if not normalized:
            self.ready = True
            return

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="archer-mcp"
        )
        self._thread.start()

        future = asyncio.run_coroutine_threadsafe(
            self._connect_all(normalized), self._loop
        )
        future.result(timeout=timeout)
        self.ready = True

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _connect_all(self, server_configs: list[dict]) -> None:
        from contextlib import AsyncExitStack

        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()
        for cfg in server_configs:
            await self._connect_one(cfg)

    async def _connect_one(self, cfg: dict) -> None:
        name = cfg["name"]
        self._server_configs[name] = cfg
        transport = cfg.get("transport", "stdio")
        try:
            if transport == "streamable_http":
                session = await self._connect_streamable_http(cfg)
            else:
                session = await self._connect_stdio(cfg)
            if session is None:
                return
            self._sessions[name] = session
            resp = await session.list_tools()
            for tool in resp.tools:
                key = _fn_name(name, tool.name)
                self._tools[key] = {
                    "server": name,
                    "tool_name": tool.name,
                    "fn_name": key,
                    "description": tool.description or "",
                    "input_schema": tool.inputSchema or {
                        "type": "object", "properties": {},
                    },
                }
        except Exception:
            self._sessions.pop(name, None)

    async def _connect_stdio(self, cfg: dict):
        params = StdioServerParameters(
            command=cfg["command"],
            args=cfg.get("args", []),
            env=cfg.get("env", None),
        )
        read, write = await self._exit_stack.enter_async_context(
            stdio_client(params, errlog=io.StringIO())
        )
        session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await session.initialize()
        return session

    async def _connect_streamable_http(self, cfg: dict):
        from mcp.client.streamable_http import streamable_http_client

        url = str(cfg["url"]).strip()
        http_client = _build_http_client(cfg)
        read, write, _get_session_id = await self._exit_stack.enter_async_context(
            streamable_http_client(url, http_client=http_client)
        )
        session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await session.initialize()
        return session

    def _reconnect_server(self, server_name: str) -> bool:
        cfg = self._server_configs.get(server_name)
        if cfg is None or not cfg.get("reconnect", True):
            return False
        if not self._loop:
            return False
        future = asyncio.run_coroutine_threadsafe(self._reconnect_one(server_name), self._loop)
        try:
            return bool(future.result(timeout=30))
        except Exception:
            return False

    async def _reconnect_one(self, server_name: str) -> bool:
        cfg = self._server_configs.get(server_name)
        if cfg is None:
            return False
        self._sessions.pop(server_name, None)
        prefix = f"{server_name}__"
        for key in list(self._tools):
            if key.startswith(prefix):
                del self._tools[key]
        await self._connect_one(cfg)
        return server_name in self._sessions

    def call_tool(self, fn_name: str, args: dict, timeout: float = 60.0) -> str:
        if not self.ready:
            raise RuntimeError("MCPManager 尚未就绪")
        info = self._tools.get(fn_name)
        if info is None:
            raise ValueError(f"MCP 工具不存在：{fn_name}")

        attempts = max(1, self._reconnect_attempts + 1)
        last_exc: Exception | None = None
        for attempt in range(attempts):
            session = self._sessions.get(info["server"])
            if session is None:
                if attempt + 1 < attempts and self._reconnect_server(info["server"]):
                    continue
                raise RuntimeError(f"MCP server {info['server']!r} 未连接")
            try:
                future = asyncio.run_coroutine_threadsafe(
                    session.call_tool(info["tool_name"], args), self._loop
                )
                result = future.result(timeout=timeout)
                return _extract_text(result)
            except Exception as exc:
                last_exc = exc
                if attempt + 1 < attempts and self._reconnect_server(info["server"]):
                    continue
                raise
        if last_exc:
            raise last_exc
        raise RuntimeError(f"MCP 工具调用失败：{fn_name}")

    def make_deferred_registry(self) -> MCPDeferredSkillRegistry:
        return MCPDeferredSkillRegistry(self, self._tools)

    def make_skill_modules(self) -> dict:
        """Backward-compatible eager materialization."""
        return {
            key: _make_module(info, self)
            for key, info in self._tools.items()
        }

    def stop(self) -> None:
        if self._loop and self._exit_stack:
            future = asyncio.run_coroutine_threadsafe(
                self._exit_stack.__aexit__(None, None, None), self._loop
            )
            try:
                future.result(timeout=10)
            except Exception:
                pass
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)


def connect_remote_mcp(
    url: str,
    *,
    name: str = "remote",
    auth: dict | None = None,
    timeout: float = 30.0,
) -> MCPManager:
    """Connect one streamable HTTP MCP server and return a ready manager."""
    cfg: dict[str, Any] = {
        "name": name,
        "transport": "streamable_http",
        "url": url,
    }
    if auth:
        cfg.update(auth)
    manager = MCPManager()
    manager.start([cfg], timeout=timeout)
    return manager


def _extract_text(result: Any) -> str:
    parts: list[str] = []
    for block in getattr(result, "content", []):
        if hasattr(block, "text"):
            parts.append(block.text)
        elif hasattr(block, "data"):
            parts.append(f"[binary, {len(block.data)} bytes]")
    return "\n".join(parts) if parts else "(empty)"


def _make_module(info: dict, manager: MCPManager) -> types.ModuleType:
    key = info["fn_name"]
    mod = types.ModuleType(f"mcp_skill_{key}")
    mod.SKILL = {
        "name": key,
        "description": f"[MCP:{info['server']}] {info['description']}",
        "version": "mcp",
        "mcp_server": info["server"],
        "mcp_tool": info["tool_name"],
        "risk": "medium",
        "default_timeout": 60,
    }

    schema_params = info["input_schema"]

    def _schema(
        _key=key, _desc=info["description"], _params=schema_params
    ) -> dict:
        return {
            "type": "function",
            "function": {
                "name": _key,
                "description": _desc,
                "parameters": _params,
            },
        }

    def _run(args: dict, _key=key, _mgr=manager) -> str:
        return _mgr.call_tool(_key, args)

    mod.schema = _schema
    mod.run = _run
    return mod


def load_from_config(cfg: dict) -> MCPManager | None:
    mcp_cfg = cfg.get("mcp", {})
    if not mcp_cfg.get("enabled", False):
        return None

    if not _MCP_AVAILABLE:
        print("[MCP] mcp 包未安装，已跳过。运行：pip install mcp", file=sys.stderr)
        return None

    servers = mcp_cfg.get("servers", [])
    if not servers:
        return None

    manager = MCPManager()
    try:
        manager.start(servers, mcp_cfg=mcp_cfg)
    except Exception as exc:
        print(f"[MCP] 初始化失败：{exc}", file=sys.stderr)
        return None
    return manager
