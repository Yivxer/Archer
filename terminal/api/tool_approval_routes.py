"""Tool approval domain: dispatch, outbox integration, and Hugo follow-up.

Extracted from ``terminal/api/_routes.py`` so that file can shrink back to a
pure compatibility dispatcher. The nine historic private names are
re-exported from ``_routes`` for callers that still import them there.
"""

from __future__ import annotations

from typing import Any

from core.permission_levels import permission_level_for_tool
from terminal.api._config import (
    _load_config,
    get_tool_draft,
    get_tool_fingerprint_result,
    get_tool_result,
    pop_tool_draft,
    record_tool_approval_audit,
    set_tool_fingerprint_result,
    set_tool_result,
    tool_request_fingerprint,
)
from terminal.api._tools import (
    _append_obsidian_draft,
    _execute_github_operation,
    _execute_shell_command,
    _run_hugo_publish_workflow,
)


IDEMPOTENT_TOOL_SKILLS = {"obsidian_write", "hugo_blog", "file_ops"}


def _run_hugo_deploy_followup(*, title: str, deploy_args: dict) -> tuple[str, str]:
    workflow_events, workflow_summary = _run_hugo_publish_workflow(
        title=title,
        actions=[("deploy", deploy_args)],
    )
    deploy_output = ""
    for event in reversed(workflow_events):
        tool_event = event.get("toolEvent", {})
        if tool_event.get("name") == "hugo_blog":
            deploy_output = str(tool_event.get("detail") or "")
            break
    return deploy_output, workflow_summary


def _build_hugo_approval_draft(event_id: str) -> dict:
    from core.api_tool_service import make_tool_request
    from skills.loader import load_skills
    return make_tool_request(
        "hugo_blog", {"action": "deploy"}, load_skills(), cfg=_load_config(),
        event_id=event_id, display_name="hugo_blog",
        extra={"action": "deploy", "title": "部署枫弋札记"}, force_approval=False,
    )


def _run_approved_draft(draft: dict):
    from core.api_tool_service import execute_tool_request
    from skills.loader import load_skills
    from terminal.api.tool_stage import apply_approval_followup, execute_approved_draft
    execution = execute_approved_draft(
        draft,
        execute_tool_request=lambda request: execute_tool_request(
            request, load_skills(), cfg=_load_config()
        ),
        append_obsidian=_append_obsidian_draft,
        execute_shell=_execute_shell_command,
        execute_github=_execute_github_operation,
    )
    return apply_approval_followup(draft, execution, deploy=_run_hugo_deploy_followup)


def _finalize_approval(event_id: str, decision: str, draft: dict, execution, fingerprint: str) -> dict:
    from terminal.api.tool_stage import build_approval_response, persist_approval_response
    permission_level = ""
    if draft.get("kind") == "tool_request":
        args = draft.get("args") if isinstance(draft.get("args"), dict) else {}
        permission_level = permission_level_for_tool(str(draft.get("skillName", "")), args)
    response = build_approval_response(
        event_id=event_id, decision=decision, execution=execution, draft=draft,
        fingerprint=fingerprint, permission_level=permission_level,
    )
    return persist_approval_response(
        response, event_id=event_id, decision=decision, draft=draft,
        fingerprint=fingerprint, record_audit=record_tool_approval_audit,
        set_event_result=set_tool_result, set_fingerprint_result=set_tool_fingerprint_result,
    )


def _tool_approval(payload: dict, runtime_context: Any = None) -> dict:
    from terminal.api.tool_stage import build_denied_response, parse_approval_decision, reuse_cached_approval
    event_id, decision = parse_approval_decision(payload)

    cached_result = reuse_cached_approval(event_id, get_tool_result)
    if cached_result:
        return cached_result

    from terminal.api.tool_stage import resolve_approval_draft
    draft = resolve_approval_draft(
        event_id,
        payload.get("draftFallback"),
        get_draft=get_tool_draft,
        build_fallback=_tool_draft_from_approval_fallback,
        build_hugo_deploy=_build_hugo_approval_draft,
    )
    if draft:
        pop_tool_draft(event_id)
        from terminal.api.tool_stage import prepare_approval_draft
        prepared = prepare_approval_draft(
            event_id=event_id,
            decision=decision,
            draft=draft,
            idempotent_skills=IDEMPOTENT_TOOL_SKILLS,
            fingerprint_for=tool_request_fingerprint,
            get_fingerprint_result=get_tool_fingerprint_result,
            permission_for=permission_level_for_tool,
        )
        request_fingerprint = prepared.fingerprint
        if prepared.reused_response:
            record_tool_approval_audit(event_id=event_id, decision=decision, draft=draft, response=prepared.reused_response)
            set_tool_result(event_id, prepared.reused_response)
            return prepared.reused_response
        outbox_item = _prepare_tool_outbox(
            event_id, decision, draft, request_fingerprint, runtime_context,
        )
        executed = False
        result_output = ""
        work_receipt = None
        message = ""
        if decision == "approved":
            if outbox_item and outbox_item.get("status") == "sent":
                cached = dict(outbox_item.get("result") or {})
                cached["eventId"] = event_id
                trace_id = str(draft.get("traceId") or "").strip()
                if trace_id:
                    cached["traceId"] = trace_id
                cached["reused"] = True
                cached["outbox"] = _outbox_receipt(outbox_item)
                return cached
            if outbox_item:
                from infrastructure.outbox import claim_for_sending

                outbox_item = claim_for_sending(
                    runtime_context.db_path, outbox_item["id"], now=runtime_context.now(),
                )
                if outbox_item is None:
                    return {
                        "ok": True, "eventId": event_id, "decision": decision,
                        "executed": False, "message": "该副作用正在发送或尚未到重试时间。",
                    }
            try:
                execution = _run_approved_draft(draft)
            except Exception as exc:
                if outbox_item:
                    from infrastructure.outbox import mark_failed

                    mark_failed(
                        runtime_context.db_path, outbox_item["id"], str(exc),
                        now=runtime_context.now(),
                    )
                raise
            executed = execution.executed
            result_output = execution.output
            message = execution.message
            work_receipt = execution.work_receipt
        else:
            response = build_denied_response(event_id, trace_id=str(draft.get("traceId") or "").strip())
            if outbox_item:
                response["outbox"] = _outbox_receipt(outbox_item)
            record_tool_approval_audit(event_id=event_id, decision=decision, draft=draft, response=response)
            set_tool_result(event_id, response)
            return response
        from terminal.api.tool_stage import ApprovalExecution
        response = _finalize_approval(
            event_id, decision, draft,
            ApprovalExecution(executed, result_output, message, work_receipt),
            request_fingerprint,
        )
        if outbox_item:
            if executed:
                from infrastructure.outbox import mark_sent

                final_item = mark_sent(
                    runtime_context.db_path, outbox_item["id"], response,
                    now=runtime_context.now(),
                )
            else:
                from infrastructure.outbox import mark_failed

                final_item = mark_failed(
                    runtime_context.db_path, outbox_item["id"], message,
                    now=runtime_context.now(),
                )
            response["outbox"] = _outbox_receipt(final_item)
        return response

    return {
        "ok": True, "eventId": event_id, "decision": decision,
        "executed": False,
        "message": (
            "未找到待执行草稿（可能 API 已重启或确认卡已过期）。"
            "请重新说「部署枫弋札记」，或直接点当前确认卡上的发布按钮。"
        ),
    }


def _prepare_tool_outbox(event_id: str, decision: str, draft: dict, fingerprint: str, runtime_context):
    if runtime_context is None or draft.get("kind") != "tool_request":
        return None
    from infrastructure.outbox import approve, cancel, enqueue

    idempotency_key = (
        f"tool:{fingerprint}"
        if fingerprint
        else f"tool-event:{event_id}"
    )
    stored_draft = dict(draft)
    if fingerprint:
        stored_draft.pop("eventId", None)
        stored_draft.pop("traceId", None)
    item = enqueue(
        runtime_context.db_path,
        kind="tool.execute",
        payload={"draft": stored_draft},
        idempotency_key=idempotency_key,
        now=runtime_context.now(),
    )
    if item["status"] == "pending":
        item = (
            approve(runtime_context.db_path, item["id"], now=runtime_context.now())
            if decision == "approved"
            else cancel(runtime_context.db_path, item["id"], now=runtime_context.now())
        )
    return item


def _outbox_receipt(item: dict | None) -> dict | None:
    if not item:
        return None
    return {
        key: item.get(key)
        for key in (
            "id", "kind", "status", "attempts", "maxAttempts", "nextAttemptAt",
            "lastError", "createdAt", "updatedAt", "approvedAt", "sentAt",
        )
    }


def _retry_tool_outbox(item_id: str, runtime_context) -> dict:
    if runtime_context is None:
        return {"ok": False, "error": "runtime_context_required"}
    from infrastructure.outbox import claim_for_sending, get_item, mark_failed, mark_sent
    from terminal.api.tool_stage import ApprovalExecution

    item = get_item(runtime_context.db_path, item_id)
    if item is None:
        return {"ok": False, "error": "outbox_not_found", "id": item_id}
    if item["kind"] != "tool.execute":
        return {"ok": False, "error": "unsupported_outbox_kind", "kind": item["kind"]}
    if item["status"] == "sent":
        return {
            **dict(item.get("result") or {}),
            "reused": True,
            "outbox": _outbox_receipt(item),
        }
    claimed = claim_for_sending(
        runtime_context.db_path, item_id, now=runtime_context.now(), force=True,
    )
    if claimed is None:
        return {"ok": False, "error": "outbox_not_retryable", "outbox": _outbox_receipt(item)}
    payload = claimed.get("payload") or {}
    draft = payload.get("draft") if isinstance(payload, dict) else None
    if not isinstance(draft, dict):
        failed = mark_failed(
            runtime_context.db_path, item_id, "stored draft is missing",
            now=runtime_context.now(),
        )
        return {"ok": False, "error": "stored_draft_missing", "outbox": _outbox_receipt(failed)}
    event_id = str(draft.get("eventId") or item_id)
    try:
        execution = _run_approved_draft(draft)
    except Exception as exc:
        failed = mark_failed(
            runtime_context.db_path, item_id, str(exc), now=runtime_context.now(),
        )
        return {"ok": False, "error": str(exc), "outbox": _outbox_receipt(failed)}
    response = _finalize_approval(
        event_id, "approved", draft,
        ApprovalExecution(
            execution.executed, execution.output, execution.message,
            execution.work_receipt, execution.raw_result,
        ),
        "",
    )
    if execution.executed:
        final_item = mark_sent(
            runtime_context.db_path, item_id, response, now=runtime_context.now(),
        )
    else:
        final_item = mark_failed(
            runtime_context.db_path, item_id, execution.message, now=runtime_context.now(),
        )
    response["outbox"] = _outbox_receipt(final_item)
    return response


def _tool_draft_from_approval_fallback(event_id: str, fallback: object) -> dict | None:
    if not isinstance(fallback, dict):
        return None
    skill_name = str(fallback.get("skillName") or "").strip()
    args = fallback.get("args")
    if not skill_name or not isinstance(args, dict):
        return None

    from core.api_tool_service import make_tool_request
    from skills.loader import load_skills

    skills = load_skills()
    if skill_name not in skills:
        return None
    display_name = str(fallback.get("displayName") or skill_name)
    extra = {
        key: value
        for key, value in fallback.items()
        if key not in {"kind", "eventId", "skillName", "displayName", "args", "argsPreview", "policy", "permissionLevel", "requiresApproval", "blocked"}
    }
    return make_tool_request(
        skill_name,
        args,
        skills,
        cfg=_load_config(),
        event_id=event_id,
        display_name=display_name,
        extra=extra,
        force_approval=False,
    )
