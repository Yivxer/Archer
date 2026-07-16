import types

from core.api_tool_service import execute_tool_request, make_tool_request


def _skill(name, output="ok", risk="low", requires_confirmation=False):
    mod = types.ModuleType(name)
    mod.SKILL = {
        "name": name,
        "risk": risk,
        "requires_confirmation": requires_confirmation,
        "default_timeout": 5,
    }
    mod.schema = lambda: {}
    mod.run = lambda _args: output
    return mod


def test_make_tool_request_uses_policy_allow():
    skills = {"safe_tool": _skill("safe_tool")}
    req = make_tool_request("safe_tool", {"value": "x"}, skills)
    assert req["kind"] == "tool_request"
    assert req["skillName"] == "safe_tool"
    assert req["policy"]["decision"] == "allow"
    assert req["requiresApproval"] is False
    assert req["blocked"] is False


def test_make_tool_request_can_force_approval_for_api_draft():
    skills = {"safe_tool": _skill("safe_tool")}
    req = make_tool_request("safe_tool", {"value": "x"}, skills, force_approval=True)
    assert req["policy"]["decision"] == "allow"
    assert req["requiresApproval"] is True


def test_make_mcp_write_request_reports_write_permission():
    skill = _skill("remote__publish")
    skill.SKILL.update({"version": "mcp", "mcp_permission": "write"})
    req = make_tool_request(
        "remote__publish",
        {},
        {"remote__publish": skill},
        force_approval=True,
    )
    assert req["permissionLevel"] == "write-local"


def test_make_tool_request_preserves_work_intent():
    skills = {"safe_tool": _skill("safe_tool")}
    work_intent = {
        "workflowName": "obsidian_write",
        "action": "append",
        "targets": [{"label": "目标笔记", "path": "/tmp/note.md"}],
        "steps": ["读取原文件", "追加内容", "返回回执"],
        "verifyPlan": "确认文件存在",
        "rollbackPlan": "保留写入前备份",
    }

    req = make_tool_request(
        "safe_tool",
        {"value": "x"},
        skills,
        extra={"workIntent": work_intent},
        force_approval=True,
    )

    assert req["requiresApproval"] is True
    assert req["workIntent"] == work_intent


def test_make_tool_request_records_policy_denial():
    skills = {"shell": _skill("shell", risk="high", requires_confirmation=True)}
    req = make_tool_request("shell", {"command": "rm -rf /"}, skills, force_approval=True)
    assert req["policy"]["decision"] == "deny"
    assert req["blocked"] is True
    assert req["requiresApproval"] is False


def test_execute_tool_request_uses_runtime():
    skills = {"safe_tool": _skill("safe_tool", output="done")}
    req = make_tool_request("safe_tool", {"value": "x"}, skills)
    result = execute_tool_request(req, skills)
    assert result["ok"] is True
    assert result["executed"] is True
    assert result["output"] == "done"


def test_execute_tool_request_preserves_structured_skill_metadata():
    mod = _skill("safe_tool", output="legacy")
    mod.run_structured = lambda _args: {
        "ok": True,
        "summary": "created",
        "output": "created ok",
        "metadata": {"filename": "test.md"},
    }
    skills = {"safe_tool": mod}
    req = make_tool_request("safe_tool", {"value": "x"}, skills)

    result = execute_tool_request(req, skills)

    assert result["ok"] is True
    assert result["executed"] is True
    assert result["summary"] == "created"
    assert result["output"] == "created ok"
    assert result["metadata"] == {"filename": "test.md"}


def test_execute_tool_request_promotes_work_receipt_from_metadata():
    receipt = {
        "done": "写入完成",
        "source": "用户输入",
        "target": "/tmp/note.md",
        "verification": "文件存在",
        "rollback": "备份：/tmp/note.md.bak",
        "traceId": "trace-1",
    }
    mod = _skill("safe_tool", output="legacy")
    mod.run_structured = lambda _args: {
        "ok": True,
        "summary": "done",
        "output": "done ok",
        "metadata": {"workReceipt": receipt},
    }
    skills = {"safe_tool": mod}
    req = make_tool_request("safe_tool", {"value": "x"}, skills)

    result = execute_tool_request(req, skills)

    assert result["ok"] is True
    assert result["workReceipt"] == receipt


def test_execute_tool_request_rechecks_policy_before_running():
    skills = {"shell": _skill("shell", risk="high", requires_confirmation=True)}
    req = {
        "kind": "tool_request",
        "skillName": "shell",
        "args": {"command": "rm -rf /"},
    }
    result = execute_tool_request(req, skills)
    assert result["ok"] is False
    assert result["executed"] is False
    assert result["policy"]["decision"] == "deny"
