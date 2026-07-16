"""P5.11 — Remote MCP + deferred loading tests."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from core.mcp import (
    MCPDeferredSkillRegistry,
    MCPManager,
    _build_http_headers,
    _normalize_server_config,
    connect_remote_mcp,
)
from skills.loader import ChainSkillRegistry


def test_normalize_streamable_http_server():
    cfg = _normalize_server_config(
        {
            "name": "remote",
            "transport": "streamable_http",
            "url": "https://example.com/mcp",
            "auth_type": "bearer",
            "auth_token": "secret",
        }
    )
    assert cfg is not None
    assert cfg["transport"] == "streamable_http"
    assert cfg["url"] == "https://example.com/mcp"


def test_normalize_stdio_requires_command():
    assert _normalize_server_config({"name": "x"}) is None
    cfg = _normalize_server_config({"name": "fs", "command": "npx", "args": []})
    assert cfg["transport"] == "stdio"


def test_build_http_headers_bearer():
    headers = _build_http_headers(
        {"auth_type": "bearer", "auth_token": "abc123", "headers": {"X-Team": "archer"}}
    )
    assert headers["Authorization"] == "Bearer abc123"
    assert headers["X-Team"] == "archer"


def test_deferred_registry_lazy_modules():
    mgr = MagicMock()
    info = {
        "fetch__get_url": {
            "server": "fetch",
            "tool_name": "get_url",
            "fn_name": "fetch__get_url",
            "description": "Fetch",
            "input_schema": {"type": "object", "properties": {}},
        }
    }
    registry = MCPDeferredSkillRegistry(mgr, info)
    assert registry.module_count() == 0
    mod = registry["fetch__get_url"]
    assert mod.SKILL["name"] == "fetch__get_url"
    assert registry.module_count() == 1


def test_chain_registry_does_not_eager_load_overlay():
    base = {"alpha": MagicMock()}
    overlay_info = {
        "remote__tool": {
            "server": "remote",
            "tool_name": "tool",
            "fn_name": "remote__tool",
            "description": "Tool",
            "input_schema": {"type": "object", "properties": {}},
        }
    }
    mgr = MagicMock()
    overlay = MCPDeferredSkillRegistry(mgr, overlay_info)
    chain = ChainSkillRegistry(base, overlay)

    assert "alpha" in chain
    assert "remote__tool" in chain
    assert overlay.module_count() == 0
    assert chain["alpha"] is base["alpha"]


def test_connect_streamable_http_uses_client():
    async def _run():
        mgr = MCPManager()
        from contextlib import AsyncExitStack

        stack = AsyncExitStack()
        await stack.__aenter__()
        mgr._exit_stack = stack

        fake_session = MagicMock()
        fake_session.initialize = AsyncMock()
        tool = MagicMock()
        tool.name = "ping"
        tool.description = "Ping"
        tool.inputSchema = {}
        fake_session.list_tools = AsyncMock(return_value=MagicMock(tools=[tool]))

        class FakeTransport:
            async def __aenter__(self):
                return ("read", "write", lambda: "sid")

            async def __aexit__(self, *args):
                return False

        class FakeSessionCtx:
            async def __aenter__(self):
                return fake_session

            async def __aexit__(self, *args):
                return False

        with patch("core.mcp._build_http_client", return_value=MagicMock()):
            with patch("core.mcp.ClientSession", return_value=FakeSessionCtx()):
                with patch(
                    "mcp.client.streamable_http.streamable_http_client",
                    return_value=FakeTransport(),
                ):
                    await mgr._connect_one(
                        {
                            "name": "remote",
                            "enabled": True,
                            "transport": "streamable_http",
                            "url": "https://example.com/mcp",
                            "tool_permissions": {"ping": "read"},
                            "allowed_domains": ["example.com"],
                        }
                    )

        assert "remote" in mgr._sessions
        assert "remote__ping" in mgr._tools

    asyncio.run(_run())


def test_connect_registers_only_explicitly_allowed_tools():
    async def _run():
        mgr = MCPManager()
        fake_session = MagicMock()
        allowed = MagicMock(name="allowed")
        allowed.name = "fetch_url"
        allowed.description = "Fetch"
        allowed.inputSchema = {}
        denied = MagicMock(name="denied")
        denied.name = "publish"
        denied.description = "Publish"
        denied.inputSchema = {}
        fake_session.list_tools = AsyncMock(return_value=MagicMock(tools=[allowed, denied]))
        mgr._connect_stdio = AsyncMock(return_value=fake_session)

        await mgr._connect_one({
            "name": "fetch",
            "enabled": True,
            "transport": "stdio",
            "command": "uvx",
            "tool_permissions": {"fetch_url": "read"},
            "allowed_domains": ["example.com"],
        })

        assert set(mgr._tools) == {"fetch__fetch_url"}
        assert mgr._tools["fetch__fetch_url"]["permission"] == "read"

    asyncio.run(_run())


def test_connect_remote_mcp_starts_manager():
    with patch("core.mcp._MCP_AVAILABLE", True):
        with patch.object(MCPManager, "start") as start:
            mgr = connect_remote_mcp("https://example.com/mcp", auth={"auth_type": "bearer", "auth_token": "x"})
    start.assert_called_once()
    assert isinstance(mgr, MCPManager)


def test_call_tool_reconnects_and_retries():
    mgr = MCPManager()
    mgr.ready = True
    mgr._loop = MagicMock()
    mgr._reconnect_attempts = 1
    mgr._tools = {
        "remote__ping": {
            "server": "remote",
            "tool_name": "ping",
            "fn_name": "remote__ping",
            "description": "Ping",
            "input_schema": {"type": "object", "properties": {}},
        }
    }
    mgr._server_configs = {
        "remote": {
            "name": "remote",
            "transport": "streamable_http",
            "url": "https://example.com/mcp",
            "reconnect": True,
        }
    }

    session = MagicMock()
    session.call_tool = AsyncMock(return_value=MagicMock(content=[MagicMock(text="pong", spec=[])]))
    mgr._sessions = {"remote": session}

    calls = {"reconnect": 0}

    def fake_reconnect(name: str) -> bool:
        calls["reconnect"] += 1
        return True

    results = [RuntimeError("disconnected"), MagicMock(content=[MagicMock(text="pong", spec=[])])]

    def fake_result(timeout=None):
        value = results.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    mgr._reconnect_server = fake_reconnect
    with patch("asyncio.run_coroutine_threadsafe", side_effect=lambda coro, loop: MagicMock(result=fake_result)):
        text = mgr.call_tool("remote__ping", {})
    assert text == "pong"
    assert calls["reconnect"] == 1
