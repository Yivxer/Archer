"""
tests/test_browser_automation.py
测试 browser_automation 的 URL 校验、direction 校验、session 管理、schema。
mock subprocess，不依赖真实浏览器。
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import importlib
mod = importlib.import_module("skills.browser_automation")


# ── 1. _navigate URL 校验 ──────────────────────────────────────────────

def test_navigate_invalid_scheme():
    """URL 不是 http/https/file 开头时返回错误。"""
    result = mod._navigate("ftp://example.com", "dummy-session")
    assert "错误" in result or "URL" in result


def test_navigate_valid_http():
    """http URL 通过校验（后续取决于 mock）。"""
    with patch("skills.browser_automation._run", return_value=(0, "ok", "")):
        result = mod._navigate("http://example.com", "s1")
    assert "✅" in result or "已打开" in result


def test_navigate_valid_https():
    with patch("skills.browser_automation._run", return_value=(0, "ok", "")):
        result = mod._navigate("https://example.com", "s1")
    assert "✅" in result or "已打开" in result


def test_navigate_valid_file():
    with patch("skills.browser_automation._run", return_value=(0, "ok", "")):
        result = mod._navigate("file:///tmp/test.html", "s1")
    assert "✅" in result or "已打开" in result


def test_navigate_subprocess_failure():
    with patch("skills.browser_automation._run", return_value=(1, "", "导航失败")):
        result = mod._navigate("https://example.com", "s1")
    assert "失败" in result or "错误" in result


# ── 2. _scroll direction 校验 ─────────────────────────────────────────

def test_scroll_valid_directions():
    for direction in ("down", "up", "top", "bottom"):
        with patch("skills.browser_automation._run", return_value=(0, "ok", "")):
            result = mod._scroll(direction, 1, "s1")
        assert "✅" in result or "滚动" in result


def test_scroll_invalid_direction():
    result = mod._scroll("left", 1, "s1")
    assert "错误" in result or "必须是" in result


def test_scroll_subprocess_failure():
    with patch("skills.browser_automation._run", return_value=(1, "", "滚动失败")):
        result = mod._scroll("down", 1, "s1")
    assert "失败" in result or "错误" in result


# ── 3. session 管理 ─────────────────────────────────────────────────────

def test_ensure_session_creates():
    """新 session_id 生成 session name。"""
    sid = "test-session-001"
    name = mod._ensure_session(sid)
    assert name.startswith("archer-")
    assert sid[:8] in name


def test_ensure_session_reuse():
    """同一 session_id 返回相同 name。"""
    sid = "test-session-002"
    name1 = mod._ensure_session(sid)
    name2 = mod._ensure_session(sid)
    assert name1 == name2


def test_new_session_unique():
    """_new_session 生成唯一 ID。"""
    s1 = mod._new_session()
    s2 = mod._new_session()
    assert s1 != s2
    assert len(s1) == 8


def test_session_cmd_format():
    """_session_cmd 返回正确的参数列表。"""
    result = mod._session_cmd("abc12345", ["open", "https://example.com"])
    assert result[0] == "--session"
    assert "archer-abc12345" in result[1]
    assert result[2] == "open"


# ── 4. _run 函数 ──────────────────────────────────────────────────────

def test_run_timeout():
    """超时返回特定错误信息。"""
    import subprocess
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 1)):
        code, out, err = mod._run(["open", "https://example.com"], timeout=1)
    assert code == -1
    assert "超时" in err


def test_run_file_not_found():
    """uvx 未安装时返回提示。"""
    with patch("subprocess.run", side_effect=FileNotFoundError):
        code, out, err = mod._run(["open", "https://example.com"])
    assert code == -1
    assert "uvx" in err or "未找到" in err


def test_run_success():
    import subprocess
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "ok"
    mock_result.stderr = ""
    with patch("subprocess.run", return_value=mock_result):
        code, out, err = mod._run(["open", "https://example.com"])
    assert code == 0


# ── 5. schema() ────────────────────────────────────────────────────────

def test_schema_structure():
    s = mod.schema()
    assert s["type"] == "function"
    f = s["function"]
    assert f["name"] == "browser_automation"
    assert "action" in f["parameters"]["properties"]
    assert f["parameters"]["required"] == ["action"]


def test_schema_action_enum():
    s = mod.schema()
    f = s["function"]
    enum_values = f["parameters"]["properties"]["action"]["enum"]
    assert "navigate" in enum_values
    assert "click" in enum_values
    assert "screenshot" in enum_values
    assert "close" in enum_values


def test_schema_direction_enum():
    s = mod.schema()
    f = s["function"]
    assert "down" in f["parameters"]["properties"]["direction"]["enum"]


# ── 6. run() 参数校验 ─────────────────────────────────────────────────

def test_run_no_action():
    result = mod.run({})
    assert "未知" in result or "错误" in result


def test_run_navigate_no_url():
    result = mod.run({"action": "navigate"})
    assert "url" in result.lower() and ("需要" in result or "参数" in result)


def test_run_navigate_invalid_url():
    result = mod.run({"action": "navigate", "url": "ftp://x.com"})
    assert "错误" in result or "URL" in result


def test_run_click_no_selector():
    result = mod.run({"action": "click", "session_id": "s1"})
    assert "selector" in result.lower() and ("需要" in result or "参数" in result)


def test_run_type_text_missing_args():
    result = mod.run({"action": "type_text", "session_id": "s1", "selector": "#inp"})
    assert "text" in result.lower() and ("需要" in result or "参数" in result)


def test_run_valid_navigate_mock():
    with patch("skills.browser_automation._run", return_value=(0, "ok", "")):
        result = mod.run({"action": "navigate", "url": "https://example.com"})
    assert "session_id" in result or "✅" in result or "已打开" in result


def test_run_close_no_session():
    """close 在没有 session 时也能调用（不报错）。"""
    # 清空 _SESSIONS
    mod._SESSIONS.clear()
    result = mod.run({"action": "close"})
    assert "✅" in result or "关闭" in result


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
