"""Tests for Desktop TS skill bridge subprocess integration."""
from __future__ import annotations

import json
from unittest.mock import patch

from core.tool_runtime import invoke
from core.ts_skill_bridge import list_ts_local_skills, runner_mode, try_execute_ts_skill


def test_try_execute_ts_skill_returns_none_without_runner():
    with patch("core.ts_skill_bridge._run_runner", return_value=None):
        assert try_execute_ts_skill("obsidian_read", {"path": "x.md"}) is None


def test_list_ts_local_skills_empty_without_runner():
    with patch("core.ts_skill_bridge._run_runner", return_value=None):
        assert list_ts_local_skills() == []


def test_try_execute_ts_skill_parses_success_payload():
    payload = {"ok": True, "output": "note body"}
    proc = type("Proc", (), {"stdout": json.dumps(payload), "returncode": 0})()

    with patch("core.ts_skill_bridge._run_runner", return_value=proc), \
         patch("core.ts_skill_bridge.runner_mode", return_value="built"):
        result = try_execute_ts_skill("obsidian_read", {"path": "Archer/x.md"})

    assert result is not None
    assert result.ok is True
    assert "note body" in result.content_preview
    assert result.meta.get("runtime") == "ts"
    assert result.meta.get("runner") == "built"


def test_try_execute_ts_skill_honors_fallback_marker():
    proc = type("Proc", (), {"stdout": json.dumps({"fallback": True}), "returncode": 0})()

    with patch("core.ts_skill_bridge._run_runner", return_value=proc):
        assert try_execute_ts_skill("file_ops", {"action": "write", "path": "/tmp/x.md"}) is None


def test_runtime_invoke_uses_ts_bridge_before_python():
    payload = {"ok": True, "output": "from ts"}
    proc = type("Proc", (), {"stdout": json.dumps(payload), "returncode": 0})()

    with patch("core.ts_skill_bridge._run_runner", return_value=proc), \
         patch("core.ts_skill_bridge.runner_mode", return_value="dev"):
        result = invoke("file_ops", {"action": "read", "path": "/tmp/demo.txt"}, {})

    assert result.ok is True
    assert "from ts" in result.content_preview
    assert result.meta.get("runtime") == "ts"


def test_runner_mode_reports_built_or_dev():
    mode = runner_mode()
    assert mode in {"built", "dev", "unavailable"}
