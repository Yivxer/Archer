"""Tests for Desktop TS skill bridge subprocess integration."""
from __future__ import annotations

import json
import types
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


def test_python_runtime_wins_even_when_ts_bridge_can_execute():
    python_skill = types.ModuleType("file_ops")
    python_skill.SKILL = {"name": "file_ops", "default_timeout": 5}
    python_skill.run = lambda _args: "from python"

    with patch(
        "core.ts_skill_bridge.try_execute_ts_skill",
        return_value=type("Result", (), {"ok": True, "content_preview": "from ts"})(),
    ) as ts_execute:
        result = invoke(
            "file_ops",
            {"action": "read", "path": "/tmp/demo.txt"},
            {"file_ops": python_skill},
        )

    assert result.ok is True
    assert result.content_preview == "from python"
    assert result.meta.get("runtime") == "py"
    ts_execute.assert_not_called()


def test_runner_mode_reports_built_or_dev():
    mode = runner_mode()
    assert mode in {"built", "dev", "unavailable"}
