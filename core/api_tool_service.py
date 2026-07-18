"""Shared tool request helpers for local API surfaces.

This module is intentionally small: it lets API/UI layers prepare a tool request,
show the same policy decision as the terminal, and execute through ToolRuntime
after user approval.
"""
from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

from core.policy import Decision, check as policy_check
from core.permission_levels import PermissionLevel, permission_level_for_tool
from core.tool_runtime import ToolResult, invoke as runtime_invoke


def _preview_args(args: dict, max_chars: int = 500) -> str:
    parts: list[str] = []
    for key, value in args.items():
        text = str(value).replace("\n", "↵")
        if len(text) > 120:
            text = text[:117] + "..."
        parts.append(f"{key}={text}")
    preview = "  ".join(parts)
    return preview[:max_chars]


def _permission_level(skill_name: str, args: dict, skills: Mapping[str, object]) -> PermissionLevel:
    mod = skills.get(skill_name)
    meta = getattr(mod, "SKILL", {}) if mod else {}
    return permission_level_for_tool(skill_name, args, meta)


def make_tool_request(
    skill_name: str,
    args: dict,
    skills: Mapping[str, object],
    cfg: dict | None = None,
    *,
    event_id: str | None = None,
    display_name: str | None = None,
    extra: dict | None = None,
    force_approval: bool = False,
) -> dict:
    """Build a serializable tool request draft with a current policy decision."""
    pr = policy_check(skill_name, args, skills, cfg=cfg)
    blocked = pr.decision == Decision.DENY
    request = {
        "kind": "tool_request",
        "eventId": event_id or f"{skill_name}-{uuid4().hex[:8]}",
        "skillName": skill_name,
        "displayName": display_name or skill_name,
        "args": dict(args),
        "argsPreview": _preview_args(args),
        "policy": {
            "decision": pr.decision.value,
            "risk": pr.risk,
            "reason": pr.reason,
        },
        "permissionLevel": _permission_level(skill_name, args, skills),
        "requiresApproval": (not blocked) and (
            force_approval or pr.decision in (Decision.CONFIRM, Decision.STRONG_CONFIRM)
        ),
        "blocked": blocked,
    }
    if extra:
        request.update(extra)
    return request


def execute_tool_request(request: dict, skills: Mapping[str, object], cfg: dict | None = None) -> dict:
    """Execute an approved tool request through the shared policy/runtime path."""
    if request.get("kind") != "tool_request":
        raise ValueError("not a tool request")

    skill_name = str(request.get("skillName", "")).strip()
    args = request.get("args")
    if not skill_name or not isinstance(args, dict):
        raise ValueError("tool request missing skillName or args")

    pr = policy_check(skill_name, args, skills, cfg=cfg)
    if pr.decision == Decision.DENY:
        return {
            "ok": False,
            "executed": False,
            "skillName": skill_name,
            "summary": f"策略拒绝：{pr.reason}",
            "output": f"[策略拒绝] {pr.reason}",
            "policy": {"decision": pr.decision.value, "risk": pr.risk, "reason": pr.reason},
        }

    tr = runtime_invoke(skill_name, args, skills)
    return _tool_result_payload(skill_name, args, tr, pr, skills)


def _tool_result_payload(skill_name: str, args: dict, tr: ToolResult, pr, skills: Mapping[str, object]) -> dict:
    output = tr.content_preview or tr.summary
    if tr.truncated and tr.artifact_path:
        output = f"{output}\n[完整结果已保存：{tr.artifact_path}]"
    metadata = dict(tr.meta.get("metadata") or {})
    work_receipt = metadata.get("workReceipt")
    return {
        "ok": tr.ok,
        "executed": tr.ok,
        "skillName": skill_name,
        "summary": tr.summary,
        "output": output,
        "artifactPath": str(tr.artifact_path) if tr.artifact_path else "",
        "truncated": tr.truncated,
        "runtime": tr.meta.get("runtime", "py"),
        "runner": tr.meta.get("runner", ""),
        "metadata": metadata,
        "workReceipt": work_receipt if isinstance(work_receipt, dict) else None,
        "policy": {"decision": pr.decision.value, "risk": pr.risk, "reason": pr.reason},
        "permissionLevel": _permission_level(skill_name, args, skills),
        "error": tr.error,
    }
