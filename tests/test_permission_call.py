"""Per-call permission and policy for known, unknown, illegal, and alias skills."""
from __future__ import annotations

import types

from core.api_tool_service import make_tool_request
from core.permission_levels import permission_level_for_tool
from core.policy import Decision, check
from skills.catalog import build_skill_catalog
from skills.loader import load_skills, reset_skill_registry


def _skill(name, **skill_fields):
    mod = types.ModuleType(name)
    mod.SKILL = {"name": name, "risk": "low", **skill_fields}
    mod.schema = lambda: {}
    mod.run = lambda _args: "ok"
    return mod


def test_known_read_write_and_execute_levels_stay_specific():
    assert permission_level_for_tool("web_search", {}) == "read-only"
    assert permission_level_for_tool("obsidian_read", {}) == "read-only"
    assert permission_level_for_tool("file_ops", {"action": "read", "path": "/tmp/note.txt"}) == "read-only"
    assert permission_level_for_tool("file_ops", {"action": "write", "path": "/tmp/note.txt"}) == "write-local"
    assert permission_level_for_tool("code_edit", {}) == "write-local"
    assert permission_level_for_tool("memory_save", {}) == "write-local"
    assert permission_level_for_tool("npm_run", {}) == "write-local"
    assert permission_level_for_tool("installer", {}) == "write-local"
    assert permission_level_for_tool("browser_automation", {}) == "unknown"
    assert permission_level_for_tool("safe_tool", {}) == "unknown"
    assert permission_level_for_tool("", {}) == "unknown"


def test_shell_alias_and_github_granularity_remain():
    assert permission_level_for_tool("shell", {"command": "ls"}) == "write-local"
    assert permission_level_for_tool("run_shell", {"command": "git push"}) == "deploy-remote"
    assert permission_level_for_tool("shell_execute", {"command": "ls"}) == "write-local"
    assert permission_level_for_tool("github_ops", {"action": "list_repos"}) == "read-only"
    assert permission_level_for_tool("github_ops", {"action": "create_issue"}) == "deploy-remote"
    assert check("run_shell", {"command": "ls"}, {}).decision == Decision.ALLOW
    assert check("shell_execute", {"command": "sudo ls"}, {}).decision == Decision.STRONG_CONFIRM
    assert check("run_shell", {"command": "rm -rf /"}, {}).decision == Decision.DENY


def test_mcp_permission_must_be_explicit():
    assert permission_level_for_tool("remote__fetch", {}, {"version": "mcp", "mcp_permission": "read"}) == "read-only"
    assert permission_level_for_tool("remote__publish", {}, {"version": "mcp", "mcp_permission": "write"}) == "write-local"
    assert permission_level_for_tool("remote__fetch", {}, {"version": "mcp"}) == "unknown"
    assert permission_level_for_tool("remote__fetch", {}, {"version": "mcp", "mcp_permission": "admin"}) == "unknown"


def test_missing_or_illegal_metadata_requires_confirmation_and_does_not_raise():
    missing = make_tool_request("ghost_skill", {"command": "ls"}, {})
    assert missing["permissionLevel"] == "unknown"
    assert missing["policy"]["decision"] == "confirm"
    assert missing["requiresApproval"] is True
    assert missing["blocked"] is False

    illegal = _skill("custom_writer", risk="nope")
    illegal_request = make_tool_request("custom_writer", {}, {"custom_writer": illegal})
    assert illegal_request["permissionLevel"] == "unknown"
    assert illegal_request["policy"]["decision"] == "confirm"
    assert illegal_request["requiresApproval"] is True

    broken = types.ModuleType("broken_skill")
    broken.SKILL = ["not", "a", "dict"]
    broken_request = make_tool_request("broken_skill", {}, {"broken_skill": broken})
    assert broken_request["policy"]["decision"] == "confirm"
    assert broken_request["permissionLevel"] == "unknown"

    blank = _skill("blank_risk", risk="  ")
    blank_request = make_tool_request("blank_risk", {}, {"blank_risk": blank})
    assert blank_request["policy"]["decision"] == "confirm"


def test_explicit_product_policies_stay_in_place():
    cases = {
        "code_edit": ("medium", Decision.ALLOW, "write-local"),
        "memory_save": ("low", Decision.ALLOW, "write-local"),
        "npm_run": ("medium", Decision.ALLOW, "write-local"),
        "browser_automation": ("medium", Decision.ALLOW, "unknown"),
    }
    for name, (risk, decision, level) in cases.items():
        skill = _skill(name, risk=risk)
        request = make_tool_request(name, {}, {name: skill})
        assert request["policy"]["decision"] == decision.value, name
        assert request["requiresApproval"] is False, name
        assert request["permissionLevel"] == level, name

    installer = _skill("installer", risk="critical", requires_confirmation=False)
    request = make_tool_request("installer", {"action": "install"}, {"installer": installer})
    assert request["policy"]["decision"] == Decision.ALLOW.value
    assert request["requiresApproval"] is False
    assert request["permissionLevel"] == "write-local"


def test_live_registry_call_labels_and_skills_route_agree():
    reset_skill_registry()
    registry = load_skills()
    rows = {row["name"]: row for row in build_skill_catalog(include_audit=False)}
    assert set(rows) == set(registry)
    for name, row in rows.items():
        level = permission_level_for_tool(name, {})
        if name in {"file_ops", "github", "git", "git_ops"}:
            continue
        if name in {"shell", "run_shell", "shell_execute", "hugo_blog"}:
            assert level in {"write-local", "deploy-remote"}
            continue
        assert level == row["permissionLevel"], name
        assert level != "read-only" or row["permissionLevel"] == "read-only"

    from terminal.api.profile_routes import _skills

    routed = {row["name"]: row for row in _skills()}
    assert set(routed) == set(rows)
    assert routed["code_edit"]["permissionLevel"] == "write-local"
    assert routed["browser_automation"]["permissionLevel"] == "unknown"
    assert routed["run_shell"]["approval"] == "conditional"
    assert "run_shell" in registry
    assert registry["run_shell"].run is not None
    assert check("run_shell", {"command": "sudo true"}, registry).decision == Decision.STRONG_CONFIRM
