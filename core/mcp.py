"""
P2-E: MCP (Model Context Protocol) Adapter

允许 Archer 连接外部 MCP 服务器，将其工具动态注入为 Archer 技能。
所有 MCP 工具调用仍经过 Policy Layer 和 ToolRuntime。

工具命名规则：{server_name}__{tool_name}（双下划线，符合 function name 规范）
服务器配置在 archer.toml [mcp] 区块：

    [mcp]
    enabled = true

    [[mcp.servers]]
    name    = "fetch"
    command = "uvx"
    args    = ["mcp-server-fetch"]
"""
from __future__ import annotations

import asyncio
import sys
import threading
import types
from typing import Any

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False


def _fn_name(server: str, tool: str) -> str:
    """生成合法的 function name：server__tool（双下划线分隔）。"""
    return f"{server}__{tool}"


class MCPManager:
    """
    管理多个 MCP server 连接。

    - 后台 asyncio 事件循环运行在独立 daemon 线程中。
    - 对外提供同步接口，REPL 主循环无需感知 async。
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._sessions: dict[str, Any] = {}           # {server_name: ClientSession}
        self._exit_stack: Any = None
        self._tools: dict[str, dict] = {}             # {fn_name: tool_info}
        self.ready: bool = False

    # ── 启动 ───────────────────────────────────────────────────────────────────

    def start(self, server_configs: list[dict], timeout: float = 30.0) -> None:
        """
        启动后台事件循环并连接所有配置的 MCP 服务器。
        连接失败的服务器不影响其他服务器。
        """
        if not _MCP_AVAILABLE:
            raise ImportError("mcp 包未安装。请运行：pip install mcp")
        if not server_configs:
            self.ready = True
            return

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="archer-mcp"
        )
        self._thread.start()

        future = asyncio.run_coroutine_threadsafe(
            self._connect_all(server_configs), self._loop
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
            name    = cfg["name"]
            command = cfg["command"]
            args    = cfg.get("args", [])
            env     = cfg.get("env", None)
            try:
                params = StdioServerParameters(command=command, args=args, env=env)
                read, write = await self._exit_stack.enter_async_context(
                    stdio_client(params)
                )
                session = await self._exit_stack.enter_async_context(
                    ClientSession(read, write)
                )
                await session.initialize()
                self._sessions[name] = session

                resp = await session.list_tools()
                for tool in resp.tools:
                    key = _fn_name(name, tool.name)
                    self._tools[key] = {
                        "server":       name,
                        "tool_name":    tool.name,
                        "fn_name":      key,
                        "description":  tool.description or "",
                        "input_schema": tool.inputSchema or {
                            "type": "object", "properties": {},
                        },
                    }
            except Exception as exc:
                print(f"[MCP] 连接 {name!r} 失败：{exc}", file=sys.stderr)

    # ── 工具调用 ────────────────────────────────────────────────────────────────

    def call_tool(self, fn_name: str, args: dict, timeout: float = 60.0) -> str:
        """同步调用 MCP 工具，返回文本结果。"""
        if not self.ready:
            raise RuntimeError("MCPManager 尚未就绪")
        info = self._tools.get(fn_name)
        if info is None:
            raise ValueError(f"MCP 工具不存在：{fn_name}")
        session = self._sessions.get(info["server"])
        if session is None:
            raise RuntimeError(f"MCP server {info['server']!r} 未连接")

        future = asyncio.run_coroutine_threadsafe(
            session.call_tool(info["tool_name"], args), self._loop
        )
        result = future.result(timeout=timeout)
        return _extract_text(result)

    # ── 注入 Archer skills ──────────────────────────────────────────────────────

    def make_skill_modules(self) -> dict:
        """为每个 MCP 工具生成合成 skill 模块，供注入 Archer skills dict。"""
        return {
            key: _make_module(info, self)
            for key, info in self._tools.items()
        }

    # ── 关闭 ───────────────────────────────────────────────────────────────────

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


# ── 辅助 ───────────────────────────────────────────────────────────────────────

def _extract_text(result: Any) -> str:
    """把 MCP CallToolResult 转为纯文本字符串。"""
    parts: list[str] = []
    for block in getattr(result, "content", []):
        if hasattr(block, "text"):
            parts.append(block.text)
        elif hasattr(block, "data"):
            parts.append(f"[binary, {len(block.data)} bytes]")
    return "\n".join(parts) if parts else "(empty)"


def _make_module(info: dict, manager: MCPManager) -> types.ModuleType:
    """构造单个 MCP 工具的合成 skill 模块。"""
    key = info["fn_name"]
    mod = types.ModuleType(f"mcp_skill_{key}")
    mod.SKILL = {
        "name":         key,
        "description":  f"[MCP:{info['server']}] {info['description']}",
        "version":      "mcp",
        "risk":         "medium",
        "default_timeout": 60,
    }

    schema_params = info["input_schema"]

    def _schema(
        _key=key, _desc=info["description"], _params=schema_params
    ) -> dict:
        return {
            "type": "function",
            "function": {
                "name":        _key,
                "description": _desc,
                "parameters":  _params,
            },
        }

    def _run(args: dict, _key=key, _mgr=manager) -> str:
        return _mgr.call_tool(_key, args)

    mod.schema = _schema
    mod.run    = _run
    return mod


# ── 配置入口 ────────────────────────────────────────────────────────────────────

def load_from_config(cfg: dict) -> MCPManager | None:
    """
    从 archer.toml [mcp] 配置初始化并返回 MCPManager。
    disabled / 未配置 / mcp 包缺失时返回 None。
    """
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
        manager.start(servers)
    except Exception as exc:
        print(f"[MCP] 初始化失败：{exc}", file=sys.stderr)
        return None
    return manager
