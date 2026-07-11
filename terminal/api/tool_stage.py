"""Tool selection, approval messaging, and execution receipt helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable


@dataclass(frozen=True, slots=True)
class ToolEventSummary:
    direct_obsidian_writes: list[str]
    tool_notes: list[str]


@dataclass(frozen=True, slots=True)
class ApprovalExecution:
    executed: bool
    output: str
    message: str
    work_receipt: dict | None = None
    raw_result: dict | None = None


@dataclass(frozen=True, slots=True)
class ApprovalPreparation:
    draft: dict | None
    fingerprint: str = ""
    reused_response: dict | None = None


def prepare_approval_draft(
    *, event_id: str, decision: str, draft: dict | None,
    idempotent_skills: set[str] | frozenset[str],
    fingerprint_for: Callable[[str, dict], str],
    get_fingerprint_result: Callable[[str], dict | None],
    permission_for: Callable[[str, dict], str],
) -> ApprovalPreparation:
    if not draft:
        return ApprovalPreparation(None)
    skill_name = str(draft.get("skillName") or "")
    if draft.get("kind") != "tool_request" or skill_name not in idempotent_skills:
        return ApprovalPreparation(draft)
    args = draft.get("args") if isinstance(draft.get("args"), dict) else {}
    fingerprint = fingerprint_for(skill_name, args)
    if decision != "approved":
        return ApprovalPreparation(draft, fingerprint)
    reused = reuse_fingerprint_approval(
        event_id, fingerprint, get_fingerprint_result(fingerprint),
        permission_level=permission_for(skill_name, args),
    )
    return ApprovalPreparation(draft, fingerprint, reused)


def parse_approval_decision(payload: dict) -> tuple[str, str]:
    event_id = str(payload.get("eventId", "")).strip()
    decision = str(payload.get("decision", "")).strip()
    if not event_id:
        raise ValueError("eventId is required")
    if decision not in ("approved", "denied"):
        raise ValueError("decision must be approved or denied")
    return event_id, decision


def reuse_cached_approval(event_id: str, get_result: Callable[[str], dict | None]) -> dict | None:
    cached_result = get_result(event_id)
    if not cached_result:
        return None
    cached_result["reused"] = True
    return cached_result


def reuse_fingerprint_approval(event_id: str, fingerprint: str, cached: dict | None, *, permission_level: str) -> dict | None:
    if not cached:
        return None
    response = dict(cached)
    response.update({"eventId": event_id, "reused": True, "fingerprint": fingerprint, "idempotencyReason": "same_fingerprint", "permissionLevel": permission_level})
    return response


def build_denied_response(event_id: str) -> dict:
    return {"ok": True, "eventId": event_id, "decision": "denied", "executed": False, "output": "", "message": "已取消，未执行。"}


def execute_approved_draft(
    draft: dict,
    *,
    execute_tool_request: Callable[[dict], dict],
    append_obsidian: Callable[[dict], str],
    execute_shell: Callable[[str, int], dict],
    execute_github: Callable[[dict], str],
) -> ApprovalExecution:
    if draft.get("kind") == "tool_request":
        result = execute_tool_request(draft)
        executed = bool(result.get("executed"))
        receipt = result.get("workReceipt") if isinstance(result.get("workReceipt"), dict) else None
        return ApprovalExecution(
            executed,
            str(result.get("output", "")),
            str(result.get("summary") or ("tool executed" if executed else "tool execution failed")),
            receipt,
            result,
        )
    if "path" in draft:
        return ApprovalExecution(True, append_obsidian(draft), "draft approved and appended to Obsidian")
    if "command" in draft and "action" not in draft:
        result = execute_shell(str(draft["command"]), int(draft.get("timeout", 30)))
        return ApprovalExecution(bool(result["ok"]), str(result["output"]), "shell command executed" if result["ok"] else "shell command failed")
    if "action" in draft:
        return ApprovalExecution(True, execute_github(draft), "github operation executed")
    return ApprovalExecution(False, "", "tool execution failed")


def build_approval_response(
    *, event_id: str, decision: str, execution: ApprovalExecution,
    draft: dict, fingerprint: str = "", permission_level: str = "",
) -> dict:
    response = {
        "ok": True, "eventId": event_id, "decision": decision,
        "executed": execution.executed, "output": execution.output,
        "message": execution.message,
    }
    if execution.work_receipt:
        response["workReceipt"] = execution.work_receipt
        response["receipt"] = execution.work_receipt
    if permission_level:
        response["permissionLevel"] = permission_level
    if fingerprint:
        response["fingerprint"] = fingerprint
    trace_id = str(draft.get("traceId") or "").strip()
    if trace_id:
        response["traceId"] = trace_id
    return response


def persist_approval_response(
    response: dict, *, event_id: str, decision: str, draft: dict,
    fingerprint: str, record_audit: Callable, set_event_result: Callable,
    set_fingerprint_result: Callable,
) -> dict:
    record_audit(event_id=event_id, decision=decision, draft=draft, response=response)
    set_event_result(event_id, response)
    if fingerprint and decision == "approved" and response.get("executed"):
        set_fingerprint_result(fingerprint, response)
    return response


def apply_approval_followup(
    draft: dict,
    execution: ApprovalExecution,
    *,
    deploy: Callable[..., tuple[object, str]],
) -> ApprovalExecution:
    """Apply the existing Hugo deploy follow-up without owning approval dispatch."""
    if not execution.executed or draft.get("kind") != "tool_request":
        return execution
    skill_name = str(draft.get("skillName") or "")
    args = draft.get("args") if isinstance(draft.get("args"), dict) else {}
    deploy_args: dict | None = None
    title = "博客文章"
    if skill_name == "hugo_blog" and str(args.get("action") or "") == "new":
        result = execution.raw_result or {}
        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        filename = str(metadata.get("filename") or "").strip()
        created_path = str(metadata.get("createdFile") or "").strip()
        deploy_args = {"action": "deploy"}
        if filename or created_path:
            deploy_args["filename"] = Path(filename or created_path).name
        else:
            match = re.search(r"文章已创建：(.+?\.md)", execution.output)
            if match:
                deploy_args["filename"] = Path(match.group(1)).name
        if "filename" not in deploy_args and args.get("slug"):
            deploy_args["slug"] = args["slug"]
        title = str(args.get("title") or title)
    elif skill_name == "file_ops":
        target = str(args.get("path") or "")
        if "/yivxer-blog/content/posts/" in target and args.get("action") == "write":
            deploy_args = {"action": "deploy", "filename": Path(target).name}
            title = Path(target).stem or title
    if deploy_args is None:
        return execution
    try:
        deploy_result, workflow_summary = deploy(title=title, deploy_args=deploy_args)
        output = execution.output + "\n\n" + str(deploy_result)
        if workflow_summary and workflow_summary not in output:
            output += "\n\n" + workflow_summary
        verified = "单页验证成功" in str(deploy_result) or "验证：" in workflow_summary
        message = execution.message + (" | hugo deploy 已自动执行并验证单页可访问" if verified else " | hugo deploy 已自动执行")
        return ApprovalExecution(True, output, message, execution.work_receipt, execution.raw_result)
    except Exception as exc:
        return ApprovalExecution(True, execution.output + f"\n\n部署失败：{exc}", execution.message + " | 部署失败", execution.work_receipt, execution.raw_result)


def summarize_api_tool_events(
    events: list[dict],
    *,
    resolve_obsidian_path: Callable[[str], str] | None = None,
) -> ToolEventSummary:
    direct_obsidian_writes: list[str] = []
    tool_notes: list[str] = []
    for event in events:
        tool_event = event.get("toolEvent", {}) if isinstance(event, dict) else {}
        name = str(tool_event.get("name", ""))
        raw_draft = tool_event.get("draft")
        draft = raw_draft if isinstance(raw_draft, dict) else {}
        if name == "obsidian_write" and tool_event.get("status") == "complete":
            raw_path = str(draft.get("path") or "未指定")
            target_path = raw_path
            if resolve_obsidian_path is not None:
                try:
                    target_path = str(resolve_obsidian_path(raw_path))
                except Exception:
                    target_path = raw_path
            direct_obsidian_writes.append(target_path)
            tool_notes.append(f"已直接写入 Obsidian；目标路径：{target_path}。")
        elif name == "hugo_blog" and tool_event.get("status") in ("waiting", "ready"):
            tool_notes.append(
                "hugo_blog 工具可用——可以在回复中自然撰写 Markdown 格式的博客文章。"
                "客户端会在你回复完成后自动创建文章并直接部署到枫弋札记（无需确认卡片）。"
                "如需新建文章请给出标题（## 开头）、分类和正文；如需部署已有文章请说明文件名。"
            )
        elif tool_event.get("requiresApproval") and "obsidian" in name:
            nested_args = draft.get("args") if isinstance(draft.get("args"), dict) else {}
            target_path = draft.get("path") or nested_args.get("path") or "未指定"
            tool_notes.append(
                "已生成 Obsidian 写入草稿，正在等待用户在工具卡片点击「写入」确认；"
                f"目标路径：{target_path}。"
            )
        elif tool_event.get("requiresApproval") and name:
            tool_notes.append(f"已生成 {name} 工具草稿，正在等待用户确认。")
    return ToolEventSummary(direct_obsidian_writes, tool_notes)
