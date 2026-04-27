"""
P2-E — MCP Adapter Tests

验证工具命名、schema 转换、合成 skill 模块、load_from_config 配置处理。
不需要真实 MCP 服务器：mock MCPManager 的内部状态。
"""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.mcp import (
    MCPManager, _extract_text, _fn_name, _make_module, load_from_config,
)


# ── _fn_name ──────────────────────────────────────────────────────────────────

def test_fn_name_basic():
    assert _fn_name("fetch", "get_url") == "fetch__get_url"

def test_fn_name_server_with_underscore():
    assert _fn_name("my_server", "read_file") == "my_server__read_file"

def test_fn_name_no_special_chars():
    name = _fn_name("filesystem", "read_file")
    import re
    assert re.fullmatch(r"[a-zA-Z0-9_]+", name), f"invalid fn_name: {name}"


# ── _extract_text ──────────────────────────────────────────────────────────────

def _text_block(text: str):
    b = MagicMock()
    b.text = text
    del b.data
    return b

def _binary_block(data: bytes):
    b = MagicMock(spec=[])
    b.data = data
    return b

def test_extract_text_single():
    result = MagicMock()
    result.content = [_text_block("hello world")]
    assert _extract_text(result) == "hello world"

def test_extract_text_multiple():
    result = MagicMock()
    result.content = [_text_block("line1"), _text_block("line2")]
    assert _extract_text(result) == "line1\nline2"

def test_extract_text_empty():
    result = MagicMock()
    result.content = []
    assert _extract_text(result) == "(empty)"

def test_extract_text_binary():
    result = MagicMock()
    result.content = [_binary_block(b"xyz")]
    text = _extract_text(result)
    assert "binary" in text
    assert "3" in text

def test_extract_text_no_content():
    result = MagicMock(spec=[])
    assert _extract_text(result) == "(empty)"


# ── _make_module ──────────────────────────────────────────────────────────────

def _sample_info():
    return {
        "server":       "fetch",
        "tool_name":    "get_url",
        "fn_name":      "fetch__get_url",
        "description":  "Fetch a URL",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    }

def test_make_module_has_skill():
    mgr = MagicMock()
    mod = _make_module(_sample_info(), mgr)
    assert hasattr(mod, "SKILL")
    assert mod.SKILL["name"] == "fetch__get_url"
    assert "fetch" in mod.SKILL["description"]

def test_make_module_schema_format():
    mgr = MagicMock()
    mod = _make_module(_sample_info(), mgr)
    s = mod.schema()
    assert s["type"] == "function"
    fn = s["function"]
    assert fn["name"] == "fetch__get_url"
    assert fn["description"] == "Fetch a URL"
    assert "url" in fn["parameters"]["properties"]

def test_make_module_run_calls_manager():
    mgr = MagicMock()
    mgr.call_tool.return_value = "fetched content"
    mod = _make_module(_sample_info(), mgr)
    result = mod.run({"url": "https://example.com"})
    mgr.call_tool.assert_called_once_with("fetch__get_url", {"url": "https://example.com"})
    assert result == "fetched content"

def test_make_module_has_schema_and_run():
    mgr = MagicMock()
    mod = _make_module(_sample_info(), mgr)
    assert callable(mod.schema)
    assert callable(mod.run)


# ── MCPManager.make_skill_modules ─────────────────────────────────────────────

def _manager_with_tools():
    mgr = MCPManager()
    mgr.ready = True
    mgr._tools = {
        "fetch__get_url": {
            "server": "fetch", "tool_name": "get_url", "fn_name": "fetch__get_url",
            "description": "Fetch a URL",
            "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}},
        },
        "fs__read_file": {
            "server": "fs", "tool_name": "read_file", "fn_name": "fs__read_file",
            "description": "Read a file",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
    }
    return mgr

def test_make_skill_modules_count():
    mgr = _manager_with_tools()
    modules = mgr.make_skill_modules()
    assert len(modules) == 2

def test_make_skill_modules_keys():
    mgr = _manager_with_tools()
    modules = mgr.make_skill_modules()
    assert "fetch__get_url" in modules
    assert "fs__read_file" in modules

def test_make_skill_modules_each_has_skill():
    mgr = _manager_with_tools()
    modules = mgr.make_skill_modules()
    for name, mod in modules.items():
        assert hasattr(mod, "SKILL")
        assert hasattr(mod, "schema")
        assert hasattr(mod, "run")

def test_make_skill_modules_empty():
    mgr = MCPManager()
    mgr.ready = True
    mgr._tools = {}
    assert mgr.make_skill_modules() == {}


# ── load_from_config ──────────────────────────────────────────────────────────

def test_load_disabled():
    cfg = {"mcp": {"enabled": False}}
    assert load_from_config(cfg) is None

def test_load_no_mcp_section():
    assert load_from_config({}) is None

def test_load_enabled_no_servers():
    cfg = {"mcp": {"enabled": True, "servers": []}}
    assert load_from_config(cfg) is None

def test_load_mcp_not_installed():
    cfg = {"mcp": {"enabled": True, "servers": [{"name": "x", "command": "x"}]}}
    with patch("core.mcp._MCP_AVAILABLE", False):
        assert load_from_config(cfg) is None

def test_load_start_failure_returns_none():
    cfg = {"mcp": {"enabled": True, "servers": [{"name": "x", "command": "x"}]}}
    with patch("core.mcp._MCP_AVAILABLE", True):
        with patch.object(MCPManager, "start", side_effect=RuntimeError("connect failed")):
            result = load_from_config(cfg)
    assert result is None

def test_load_success_returns_manager():
    cfg = {"mcp": {"enabled": True, "servers": [{"name": "x", "command": "x"}]}}
    with patch("core.mcp._MCP_AVAILABLE", True):
        with patch.object(MCPManager, "start"):
            result = load_from_config(cfg)
    assert isinstance(result, MCPManager)


# ── call_tool 错误处理 ─────────────────────────────────────────────────────────

def test_call_tool_not_ready():
    mgr = MCPManager()
    mgr.ready = False
    try:
        mgr.call_tool("x__y", {})
        assert False, "should raise"
    except RuntimeError as e:
        assert "就绪" in str(e)

def test_call_tool_unknown_tool():
    mgr = MCPManager()
    mgr.ready = True
    mgr._tools = {}
    try:
        mgr.call_tool("nonexistent__tool", {})
        assert False, "should raise"
    except ValueError as e:
        assert "nonexistent__tool" in str(e)
