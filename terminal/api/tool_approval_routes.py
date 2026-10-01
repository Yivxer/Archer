"""Tool approval domain: dispatch, outbox integration, and Hugo follow-up.

Extracted from ``terminal/api/_routes.py`` so that file can shrink back to a
pure compatibility dispatcher. The nine historic private names are
re-exported from ``_routes`` for callers that still import them there.
"""

from __future__ import annotations

from typing import Any

from core.permission_levels import permission_level_for_tool
from core.runtime_cancellation import CancellationToken
from terminal.api._config import (
    CACHE_CREATED_AT_FIELD,
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


def _run_approved_draft(
    draft: dict,
    cancellation_token: CancellationToken | None = None,
) -> Any:
    from core.api_tool_service import execute_tool_request
    from skills.loader import load_skills
    from terminal.api.tool_stage import apply_approval_followup, execute_approved_draft

    def execute_request(request: dict) -> dict:
        if cancellation_token is None:
            return execute_tool_request(request, load_skills(), cfg=_load_config())
        return execute_tool_request(
            request,
            load_skills(),
            cfg=_load_config(),
            cancellation_token=cancellation_token,
        )

    execution = execute_approved_draft(
        draft,
        execute_tool_request=execute_request,
        append_obsidian=_append_obsidian_draft,
        execute_shell=_execute_shell_command,
        execute_github=_execute_github_operation,
    )
    return apply_approval_followup(draft, execution, deploy=_run_hugo_deploy_followup)


def _finalize_approval(
    event_id: str,
    decision: str,
    draft: dict,
    execution,
    fingerprint: str,
    verification_receipt: dict | None = None,
) -> dict:
    from terminal.api.tool_stage import build_approval_response, persist_approval_response
    permission_level = ""
    if draft.get("kind") == "tool_request":
        args = draft.get("args") if isinstance(draft.get("args"), dict) else {}
        permission_level = permission_level_for_tool(str(draft.get("skillName", "")), args)
    response = build_approval_response(
        event_id=event_id, decision=decision, execution=execution, draft=draft,
        fingerprint=fingerprint, permission_level=permission_level,
    )
    if verification_receipt:
        response["verificationReceipt"] = verification_receipt
    if draft.get("runtimeContract"):
        response["runtimeContract"] = draft["runtimeContract"]
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
            from terminal.api.obsidian_runtime_bridge import (
                close_reused_runtime_response,
            )

            reused = close_reused_runtime_response(
                draft,
                prepared.reused_response,
                fingerprint=request_fingerprint,
                event_id=event_id,
                runtime_context=runtime_context,
            )
            record_tool_approval_audit(event_id=event_id, decision=decision, draft=draft, response=reused)
            set_tool_result(event_id, reused)
            return reused
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
                from terminal.api.obsidian_runtime_bridge import (
                    close_reused_runtime_response,
                )

                cached = close_reused_runtime_response(
                    draft,
                    cached,
                    fingerprint=request_fingerprint,
                    event_id=event_id,
                    runtime_context=runtime_context,
                )
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
            runtime_binding = None
            cancellation_token = None
            runtime_contract = draft.get("runtimeContract")
            runtime_run_id = (
                str(runtime_contract.get("runId") or "").strip()
                if isinstance(runtime_contract, dict)
                else ""
            )
            verification_receipt = None
            cancellation = None
            try:
                from terminal.api.obsidian_runtime_bridge import begin_runtime_approval

                runtime_binding = begin_runtime_approval(
                    draft,
                    fingerprint=request_fingerprint,
                    runtime_context=runtime_context,
                )
                cancellation_token = (
                    runtime_context.cancellations.token(runtime_binding.run_id)
                    if runtime_binding is not None and runtime_context is not None
                    else None
                )
                try:
                    execution = (
                        _run_approved_draft(
                            draft,
                            cancellation_token=cancellation_token,
                        )
                        if cancellation_token is not None
                        else _run_approved_draft(draft)
                    )
                except Exception as exc:
                    from terminal.api.obsidian_runtime_bridge import fail_runtime_approval

                    fail_runtime_approval(
                        draft,
                        runtime_context=runtime_context,
                        summary=str(exc),
                        error_code="obsidian_write_exception",
                    )
                    raise
                if cancellation_token is not None:
                    from terminal.api.obsidian_runtime_bridge import (
                        finalize_runtime_cancellation,
                        finalize_runtime_execution,
                    )

                    with cancellation_token.finalization_guard() as cancellation_requested:
                        if cancellation_requested:
                            cancellation = finalize_runtime_cancellation(
                                draft,
                                execution,
                                cancellation_token,
                                fingerprint=request_fingerprint,
                                event_id=event_id,
                                runtime_context=runtime_context,
                            )
                        else:
                            verification_receipt = finalize_runtime_execution(
                                draft,
                                execution,
                                fingerprint=request_fingerprint,
                                event_id=event_id,
                                runtime_context=runtime_context,
                            )
            except Exception as exc:
                if outbox_item:
                    from infrastructure.outbox import mark_failed

                    mark_failed(
                        runtime_context.db_path, outbox_item["id"], str(exc),
                        now=runtime_context.now(),
                    )
                raise
            finally:
                if runtime_context is not None:
                    release_run_id = (
                        runtime_binding.run_id
                        if runtime_binding is not None
                        else runtime_run_id
                    )
                    if release_run_id:
                        runtime_context.cancellations.release(release_run_id)
            if cancellation is not None:
                response = {
                    "ok": True,
                    "eventId": event_id,
                    "decision": decision,
                    "executed": False,
                    "runtimeContract": draft.get("runtimeContract"),
                    **(cancellation or {}),
                }
                if outbox_item:
                    from infrastructure.outbox import mark_failed

                    final_item = mark_failed(
                        runtime_context.db_path,
                        outbox_item["id"],
                        str(response.get("message") or "runtime cancelled"),
                        now=runtime_context.now(),
                    )
                    response["outbox"] = _outbox_receipt(final_item)
                record_tool_approval_audit(
                    event_id=event_id,
                    decision=decision,
                    draft=draft,
                    response=response,
                )
                set_tool_result(event_id, response)
                return response
            executed = execution.executed
            result_output = execution.output
            message = execution.message
            work_receipt = execution.work_receipt
        else:
            from terminal.api.obsidian_runtime_bridge import cancel_runtime_approval

            cancel_runtime_approval(draft, runtime_context=runtime_context)
            response = build_denied_response(event_id, trace_id=str(draft.get("traceId") or "").strip())
            if outbox_item:
                response["outbox"] = _outbox_receipt(outbox_item)
            record_tool_approval_audit(event_id=event_id, decision=decision, draft=draft, response=response)
            set_tool_result(event_id, response)
            return response
        from terminal.api.tool_stage import ApprovalExecution
        response = _finalize_approval(
            event_id, decision, draft,
            ApprovalExecution(
                executed,
                result_output,
                message,
                work_receipt,
                execution.raw_result,
            ),
            request_fingerprint,
            verification_receipt,
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


def _enqueue_tool_outbox(
    runtime_context: Any, stored_draft: dict, idempotency_key: str,
) -> dict:
    from infrastructure.outbox import enqueue, get_by_idempotency_key

    payload = {"draft": stored_draft}
    try:
        return enqueue(
            runtime_context.db_path, kind="tool.execute", payload=payload,
            idempotency_key=idempotency_key, now=runtime_context.now(),
        )
    except ValueError:
        # Older durable payloads include an ephemeral draft-cache timestamp.
        # Reuse only if every other field still matches; keep the old row intact.
        existing = get_by_idempotency_key(runtime_context.db_path, idempotency_key)
        if existing is None or existing["kind"] != "tool.execute":
            raise
        prior_payload = dict(existing["payload"])
        prior_draft = prior_payload.get("draft")
        if not isinstance(prior_draft, dict):
            raise
        prior_draft = dict(prior_draft)
        requested_draft = dict(stored_draft)
        prior_draft.pop(CACHE_CREATED_AT_FIELD, None)
        requested_draft.pop(CACHE_CREATED_AT_FIELD, None)
        prior_payload["draft"] = prior_draft
        if prior_payload != {"draft": requested_draft}:
            raise
        return {**existing, "reused": True}


def _prepare_tool_outbox(event_id: str, decision: str, draft: dict, fingerprint: str, runtime_context):
    if runtime_context is None or draft.get("kind") != "tool_request":
        return None
    from infrastructure.outbox import approve, cancel

    idempotency_key = (
        f"tool:{fingerprint}"
        if fingerprint
        else f"tool-event:{event_id}"
    )
    stored_draft = dict(draft)
    if fingerprint:
        stored_draft.pop("eventId", None)
        stored_draft.pop("traceId", None)
    item = _enqueue_tool_outbox(runtime_context, stored_draft, idempotency_key)
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


def _run_runtime_bound_outbox_draft(
    draft: dict,
    *,
    event_id: str,
    runtime_context: Any,
) -> tuple[Any, str, dict | None, dict | None]:
    from terminal.api.obsidian_runtime_bridge import (
        begin_runtime_approval,
        fail_runtime_approval,
        finalize_runtime_cancellation,
        finalize_runtime_execution,
        recover_completed_runtime_execution,
    )

    stored_fingerprint = str(draft.get("approvalFingerprint") or "").strip()
    args = draft.get("args") if isinstance(draft.get("args"), dict) else {}
    fingerprint = tool_request_fingerprint(
        str(draft.get("skillName") or ""),
        args,
    )
    if not stored_fingerprint or stored_fingerprint != fingerprint:
        raise ValueError("stored draft fingerprint does not match its arguments")
    recovered = recover_completed_runtime_execution(
        draft,
        fingerprint=fingerprint,
        runtime_context=runtime_context,
    )
    if recovered is not None:
        execution, receipt = recovered
        return execution, fingerprint, receipt, None
    binding = begin_runtime_approval(
        draft,
        fingerprint=fingerprint,
        runtime_context=runtime_context,
    )
    if binding is None:
        raise ValueError("stored runtime contract is invalid")
    token = runtime_context.cancellations.token(binding.run_id)
    try:
        try:
            execution = _run_approved_draft(draft, cancellation_token=token)
        except Exception as exc:
            fail_runtime_approval(
                draft,
                runtime_context=runtime_context,
                summary=str(exc),
                error_code="obsidian_write_exception",
            )
            raise
        with token.finalization_guard() as cancellation_requested:
            if cancellation_requested:
                cancellation = finalize_runtime_cancellation(
                    draft,
                    execution,
                    token,
                    fingerprint=fingerprint,
                    event_id=event_id,
                    runtime_context=runtime_context,
                )
                return execution, fingerprint, None, cancellation
            receipt = finalize_runtime_execution(
                draft,
                execution,
                fingerprint=fingerprint,
                event_id=event_id,
                runtime_context=runtime_context,
            )
            return execution, fingerprint, receipt, None
    finally:
        runtime_context.cancellations.release(binding.run_id)


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
    fingerprint = ""
    verification_receipt = None
    cancellation = None
    try:
        if "runtimeContract" in draft:
            execution, fingerprint, verification_receipt, cancellation = (
                _run_runtime_bound_outbox_draft(
                    draft,
                    event_id=event_id,
                    runtime_context=runtime_context,
                )
            )
        else:
            execution = _run_approved_draft(draft)
    except Exception as exc:
        failed = mark_failed(
            runtime_context.db_path, item_id, str(exc), now=runtime_context.now(),
        )
        return {"ok": False, "error": str(exc), "outbox": _outbox_receipt(failed)}
    if cancellation is not None:
        response = {
            "ok": True,
            "eventId": event_id,
            "decision": "approved",
            "executed": False,
            "runtimeContract": draft.get("runtimeContract"),
            **cancellation,
        }
        final_item = mark_failed(
            runtime_context.db_path,
            item_id,
            str(response.get("message") or "runtime cancelled"),
            now=runtime_context.now(),
        )
        response["outbox"] = _outbox_receipt(final_item)
        return response
    response = _finalize_approval(
        event_id, "approved", draft,
        ApprovalExecution(
            execution.executed, execution.output, execution.message,
            execution.work_receipt, execution.raw_result,
        ),
        fingerprint,
        verification_receipt,
    )
    if (
        isinstance(execution.raw_result, dict)
        and execution.raw_result.get("runtimeReused") is True
    ):
        response["reused"] = True
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
