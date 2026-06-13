"""Tests for Desktop TS skill bridge subprocess integration."""
from __future__ import annotations

import json
from unittest.mock import patch

from core.tool_runtime import invoke
from core.ts_skill_bridge import list_ts_local_skills, try_execute_ts_skill


def test_try_execute_ts_skill_returns_none_without_runner():
    with patch("core.ts_skill_bridge._runner_path", return_value=None):
        assert try_execute_ts_skill("obsidian_read", {"path": "x.md"}) is None


def test_list_ts_local_skills_empty_without_runner():
    with patch("core.ts_skill_bridge._runner_path", return_value=None):
        assert list_ts_local_skills() == []


def test_try_execute_ts_skill_parses_success_payload():
    payload = {"ok": True, "output": "note body"}
    proc = type("Proc", (), {"stdout": json.dumps(payload), "returncode": 0})()

    with patch("core.ts_skill_bridge._runner_path", return_value=__import__("pathlib").Path("/tmp/runLocalSkill.js")), \
         patch("core.ts_skill_bridge.shutil.which", return_value="node"), \
         patch("core.ts_skill_bridge.subprocess.run", return_value=proc):
        result = try_execute_ts_skill("obsidian_read", {"path": "Archer/x.md"})

    assert result is not None
    assert result.ok is True
    assert "note body" in result.content_preview


def test_try_execute_ts_skill_honors_fallback_marker():
    proc = type("Proc", (), {"stdout": json.dumps({"fallback": True}), "returncode": 0})()

    with patch("core.ts_skill_bridge._runner_path", return_value=__import__("pathlib").Path("/tmp/runLocalSkill.js")), \
         patch("core.ts_skill_bridge.shutil.which", return_value="node"), \
         patch("core.ts_skill_bridge.subprocess.run", return_value=proc):
        assert try_execute_ts_skill("file_ops", {"action": "write", "path": "/tmp/x.md"}) is None


def test_runtime_invoke_uses_ts_bridge_before_python():
    payload = {"ok": True, "output": "from ts"}
    proc = type("Proc", (), {"stdout": json.dumps(payload), "returncode": 0})()

    with patch("core.ts_skill_bridge._runner_path", return_value=__import__("pathlib").Path("/tmp/runLocalSkill.js")), \
         patch("core.ts_skill_bridge.shutil.which", return_value="node"), \
         patch("core.ts_skill_bridge.subprocess.run", return_value=proc):
        result = invoke("file_ops", {"action": "read", "path": "/tmp/demo.txt"}, {})

    assert result.ok is True
    assert "from ts" in result.content_preview
