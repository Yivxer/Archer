"""Shared Desktop API tool request, policy, and event helpers."""

from __future__ import annotations

import subprocess

from terminal.api._config import _load_config
from core.desktop_tool_router import (
    filter_skills_for_intent as _filter_skills_for_intent,
    parse_obsidian_write_request as _parse_obsidian_write_request,
    plan_desktop_turn as _plan_desktop_turn,
)


# Shell execution
# ---------------------------------------------------------------------------

def _is_dangerous_shell(command: str) -> bool:
    from core.policy import score_shell_risk
    risk, _ = score_shell_risk(command)
    return risk in ("critical", "high")


def _execute_shell_command(command: str, timeout: int = 30) -> dict:
    if _is_dangerous_shell(command):
        return {
            "ok": False,
            "output": f"[拒绝] 检测到高风险命令，已阻止：{command}\n如需执行请直接在终端运行。",
        }
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=timeout,
        )
        output = (result.stdout + result.stderr).strip()
        return {"ok": True, "output": output or "(无输出)", "exitCode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "错误：命令超时（30s）"}
    except Exception as exc:
        return {"ok": False, "output": f"错误：{exc}"}


# ---------------------------------------------------------------------------
# Tool event construction
# ---------------------------------------------------------------------------

def _tool_event(
    event_id: str, name: str, status: str, risk: str,
    summary: str, detail: str, requires_approval: bool = False,
    draft: dict | None = None,
) -> dict:
    tool_event = {
        "id": event_id, "name": name, "status": status, "risk": risk,
        "summary": summary, "detail": detail,
        "requiresApproval": requires_approval,
    }
    if draft:
        tool_event["draft"] = draft
        if draft.get("permissionLevel"):
            tool_event["permissionLevel"] = draft.get("permissionLevel")
    return {"type": "tool_event", "toolEvent": tool_event}


def _obsidian_write_draft(query: str) -> dict:
    parsed = _parse_obsidian_write_request(query)
    content = parsed.body if parsed.mode == "overwrite" else (
        "\n<!-- Archer Desktop 自动写入 -->\n"
        f"{parsed.body}\n"
    )
    path = parsed.path
    # 计算 before/after 预览，供确认卡展示 diff
    try:
        from skills.obsidian_write import compute_preview
        preview = compute_preview({"path": path, "content": content, "mode": parsed.mode})
    except Exception:
        preview = None
    return {
        "path": path,
        "mode": parsed.mode,
        "contentPreview": content[:500],
        "content": content,
        "beforeText": preview["before"] if preview else "",
        "afterText": preview["after"] if preview else content[:2000],
        "previewMode": parsed.mode,
        "previewExists": preview["exists"] if preview else False,
        "expectedMtime": preview["mtime"] if preview else None,
        "expectedSize": preview["size"] if preview else None,
        "expectedFingerprint": preview["fingerprint"] if preview else None,
    }


def _make_api_tool_request(
    skill_name: str, args: dict, *, event_id: str, display_name: str,
    extra: dict | None = None, force_approval: bool = True,
) -> dict:
    from core.api_tool_service import make_tool_request
    from skills.loader import load_skills
    return make_tool_request(
        skill_name, args, load_skills(), cfg=_load_config(),
        event_id=event_id, display_name=display_name,
        extra=extra, force_approval=force_approval,
    )


def _obsidian_work_intent(path: str, mode: str, *, before_text: str = "") -> dict:
    original_lines = len(before_text.splitlines()) if before_text else 0
    return {
        "workflowName": "Obsidian 写入",
        "action": mode,
        "targets": [{"label": "目标笔记", "path": path}],
        "steps": ["读取当前文件状态", "校验文件指纹", "写入内容", "返回写入回执"],
        "verifyPlan": f"确认目标文件存在，原文件约 {original_lines} 行",
        "rollbackPlan": "写入前校验 expected_fingerprint；如文件已变化则拒绝写入",
    }


def _expert_scoped_skills(cfg: dict | None = None) -> dict:
    from core.experts import active_expert, filter_skills_for_expert
    from skills.loader import load_skills

    resolved = cfg or _load_config()
    return filter_skills_for_expert(load_skills(), active_expert(resolved))


def _select_api_skills(query: str, all_skills: dict | None = None) -> dict:
    if all_skills is None:
        all_skills = _expert_scoped_skills()
    return _plan_desktop_turn(
        query, all_skills, llm_fallback=False,
    ).raw_selected


def _filter_api_skills_for_intent(query: str, selected: dict, *, intent: str = "chat") -> dict:
    return _filter_skills_for_intent(query, selected, intent=intent)


def _tool_event_from_request(
    request: dict, *, summary: str, detail_prefix: str = "",
) -> dict:
    policy = request.get("policy", {})
    decision = policy.get("decision", "confirm")
    risk = policy.get("risk", "medium")
    reason = policy.get("reason", "")
    status = "blocked" if request.get("blocked") else "waiting"
    detail_parts = [
        f"id: {request['eventId']}",
        f"skill: {request.get('skillName', '')}",
        f"decision: {decision}",
    ]
    if detail_prefix:
        detail_parts.append(detail_prefix)
    if reason:
        detail_parts.append(str(reason)[:240])
    return _tool_event(
        request["eventId"],
        request.get("displayName") or request.get("skillName", "tool"),
        status, risk,
        summary if not request.get("blocked") else f"工具请求被策略阻止：{summary}",
        ", ".join(detail_parts),
        bool(request.get("requiresApproval")) and not request.get("blocked"),
        request,
    )


def _tool_event_from_result(
    event_id: str, name: str, result: dict, *, summary: str,
    draft: dict | None = None,
) -> dict:
    policy = result.get("policy", {})
    risk = policy.get("risk", "low")
    status = "complete" if result.get("ok") else "blocked"
    detail = str(result.get("output") or result.get("summary") or "")[:300]
    return _tool_event(
        event_id, name, status, risk,
        summary if result.get("ok") else f"{summary}失败",
        detail, False, draft,
    )


def _execute_api_tool_preview(
    skill_name: str, args: dict, *, event_id: str,
    display_name: str, summary: str,
) -> dict:
    from core.api_tool_service import execute_tool_request
    from skills.loader import load_skills
    skills = load_skills()
    request = _make_api_tool_request(
        skill_name, args, event_id=event_id,
        display_name=display_name, force_approval=False,
    )
    if request.get("blocked"):
        return _tool_event_from_request(request, summary=summary)
    result = execute_tool_request(request, skills, cfg=_load_config())
    return _tool_event_from_result(event_id, display_name, result, summary=summary)


# ---------------------------------------------------------------------------

