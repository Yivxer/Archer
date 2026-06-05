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
