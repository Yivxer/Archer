"""Skill catalog contract: registration, permission, approval, and redaction."""
from __future__ import annotations

import types

from core.permission_levels import permission_level_for_tool
from core.policy import Decision, check
from skills.catalog import build_skill_catalog, contract_for_skill_name
from skills.loader import load_skill_full, register_all_skills, reset_skill_registry


def _rows(**kwargs):
    reset_skill_registry()
    return {row["name"]: row for row in build_skill_catalog(**kwargs)}


def test_catalog_names_match_production_registration():
    reset_skill_registry()
    registered = set(register_all_skills().metas())
    rows = _rows(include_audit=False)
    assert set(rows) == registered
    assert "run_shell" in registered
    assert rows["run_shell"]["name"] == "run_shell"


def test_annotated_assignment_is_part_of_registration():
    rows = _rows(include_audit=False)
    soul = rows["soul_evolution"]
    assert "进化" in soul["description"]
    assert soul["description"] != "soul_evolution"
    assert soul["risk"] == "unknown"
    assert "mode" in soul["inputSummary"]


def test_missing_risk_is_not_labeled_low():
    rows = _rows(include_audit=False)
    assert rows["site_check"]["risk"] == "unknown"
    assert rows["web_search"]["risk"] == "low"


def test_unclassified_name_is_not_presented_as_safe():
    contract = contract_for_skill_name("safe_tool")
    assert contract == {
        "permissionLevel": "unknown",
        "permissionBasis": "unknown",
        "approval": "unknown",
    }
    assert permission_level_for_tool("safe_tool", {}) == "unknown"


def test_registered_side_effects_are_not_labeled_read_only():
    rows = _rows(include_audit=False)
    for name in ("github_ops", "shell", "run_shell", "file_ops", "memory_save", "code_edit", "hugo_blog"):
        assert rows[name]["permissionLevel"] != "read-only", name
    assert rows["github_ops"]["permissionLevel"] == "deploy-remote"
    assert rows["github_ops"]["approval"] == "required"
    assert rows["obsidian_write"]["permissionLevel"] == "write-vault"
    assert rows["obsidian_write"]["approval"] == "conditional"
    assert rows["obsidian_read"]["permissionLevel"] == "read-only"
    assert rows["obsidian_read"]["approval"] == "not_required"
    assert rows["shell"]["approval"] == "conditional"
    assert rows["run_shell"]["approval"] == "conditional"
    assert rows["browser_automation"]["permissionLevel"] == "unknown"
    assert rows["browser_automation"]["approval"] == "not_required"


def test_run_shell_alias_is_loadable_and_shares_shell_policy():
    reset_skill_registry()
    register_all_skills()
    module = load_skill_full("run_shell")
    assert module.SKILL["name"] == "run_shell"
    assert module.schema()["function"]["name"] == "run_shell"
    assert check("run_shell", {"command": "ls"}, {}).decision == Decision.ALLOW
    assert check("shell", {"command": "ls"}, {}).decision == Decision.ALLOW
    assert check("run_shell", {"command": "sudo ls"}, {}).decision == Decision.STRONG_CONFIRM
    assert permission_level_for_tool("run_shell", {"command": "ls"}) == "write-local"
    assert permission_level_for_tool("run_shell", {"command": "git push origin main"}) == "deploy-remote"


def test_permission_level_matches_github_ops_actions():
    assert permission_level_for_tool("github_ops", {"action": "list_repos"}) == "read-only"
    assert permission_level_for_tool("github_ops", {"action": "create_issue"}) == "deploy-remote"
    assert permission_level_for_tool("github_ops", {"action": "run"}) == "deploy-remote"
    github = types.SimpleNamespace(SKILL={
        "name": "github_ops",
        "risk": "high",
        "requires_confirmation": True,
    })
    skills = {"github_ops": github}
    assert check("github_ops", {"action": "list_repos"}, skills).decision == Decision.CONFIRM
    assert check("github_ops", {"action": "run", "command": "repo view"}, skills).decision == Decision.STRONG_CONFIRM


def test_conditional_skills_follow_existing_policy_branches():
    assert check("hugo_blog", {"action": "list"}, {}).decision == Decision.ALLOW
    assert check("hugo_blog", {"action": "deploy"}, {}).decision == Decision.CONFIRM
    assert check("file_ops", {"action": "read", "path": "/tmp/archer-skill-catalog-note.txt"}, {}).decision == Decision.ALLOW
    assert check("file_ops", {"action": "write", "path": "/tmp/archer-skill-catalog-note.txt"}, {}).decision == Decision.CONFIRM
    assert check("obsidian_write", {"path": "Archer/note.md"}, {}).decision == Decision.ALLOW
    assert check("obsidian_write", {"path": "其他/note.md"}, {}).decision == Decision.CONFIRM
    installer = types.SimpleNamespace(SKILL={
        "name": "installer",
        "risk": "critical",
        "requires_confirmation": False,
    })
    assert check("installer", {}, {"installer": installer}).decision == Decision.ALLOW


def test_input_summaries_come_from_registered_schemas():
    rows = _rows(include_audit=False)
    assert rows["web_search"]["inputSummary"] == "必填 query；可选 max_results"
    assert "command" in rows["run_shell"]["inputSummary"]
    assert "action" in rows["hugo_blog"]["inputSummary"]
    assert rows["web_search"]["outputSummary"] == "未声明结构化输出"
    assert rows["web_search"]["ioDeclared"] is True


def test_recent_approval_redacts_private_fields():
    secret = "SECRET_PATH_/Users/example/vault/private.md"
    rows = _rows(
        audit_items=[
            {
                "skillName": "shell",
                "decision": "approved",
                "executed": True,
                "permissionLevel": "write-local",
                "timestamp": 10,
                "policyReason": secret,
                "message": secret,
                "args": {"command": secret},
                "fingerprint": secret,
            },
            {
                "skillName": "shell",
                "decision": "denied",
                "executed": False,
                "timestamp": 11,
                "policyReason": secret,
            },
            {
                "skillName": "web_search",
                "decision": "approved",
                "executed": False,
                "timestamp": 9,
            },
        ]
    )
    recent = rows["shell"]["recentApproval"]
    assert recent["state"] == "recorded"
    assert recent["count"] == 2
    assert recent["latest"] == {
        "decision": "denied",
        "executed": False,
        "permissionLevel": "unknown",
        "at": 11,
    }
    assert secret not in str(rows["shell"])
    assert rows["web_search"]["recentApproval"]["count"] == 1
    assert rows["memory_save"]["recentApproval"] == {"state": "none", "count": 0, "latest": None}


def test_unknown_recent_decision_is_not_turned_into_approval_free():
    rows = _rows(audit_items=[{
        "skillName": "memory_save",
        "decision": "allow",
        "executed": True,
        "message": "saved private note",
    }])
    latest = rows["memory_save"]["recentApproval"]["latest"]
    assert latest["decision"] == "unknown"
    assert "saved private note" not in str(rows["memory_save"])


def test_skills_route_projects_the_same_contract(monkeypatch):
    secret = "DO_NOT_LEAK_AUDIT_BODY"
    monkeypatch.setattr(
        "skills.catalog._default_audit_items",
        lambda: [{
            "skillName": "github_ops",
            "decision": "denied",
            "executed": False,
            "permissionLevel": "deploy-remote",
            "timestamp": 3,
            "policyReason": secret,
            "message": secret,
        }],
    )
    from terminal.api.profile_routes import _skills

    rows = {row["name"]: row for row in _skills()}
    assert rows["github_ops"]["approval"] == "required"
    assert rows["github_ops"]["recentApproval"]["latest"]["decision"] == "denied"
    assert secret not in str(rows["github_ops"])
    assert "path" not in rows["github_ops"]
    assert rows["github_ops"]["enabled"] is True
