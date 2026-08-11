"""Approval decision orchestration for legacy Background Job tools."""
from __future__ import annotations

from datetime import datetime
from typing import Mapping, MutableMapping

from core.job_approval import (
    JobApprovalFingerprintMismatchError,
    LegacyJobApprovalClaim,
    approval_decision_is_current,
    claim_legacy_job_approval,
    legacy_job_pending_tool_fingerprint,
    mark_approval_manual_uncertain,
    restore_legacy_job_approval_metadata,
)
from core.job_execution_adapter import (
    JobCommand,
    JobCommandCollisionError,
    JobCommandContractError,
    JobCommandStaleSnapshotError,
)
from core.job_terminal_finalize import JobTerminalFinalizeStaleError
from terminal.api.job_cancellation import job_cancellation_response
from terminal.api.job_result_evidence import complete_legacy_job_result


def pending_tool_fingerprint(pending_tool: Mapping[str, object]) -> str:
    return legacy_job_pending_tool_fingerprint(pending_tool)


def restore_legacy_job_approval(
    raw: Mapping[str, object],
    job: MutableMapping[str, object],
) -> None:
    restore_legacy_job_approval_metadata(raw, job)


def _execute_approved_tool(
    tool_name: str,
    draft: Mapping[str, object],
) -> tuple[str, str]:
    try:
        if tool_name == "shell.execute":
            from terminal.api._tools import _execute_shell_command

            return f"[shell] {_execute_shell_command(dict(draft))[:500]}", ""
        if tool_name == "obsidian_write":
            from terminal.api._tools import _append_obsidian_draft

            target = _append_obsidian_draft(dict(draft))
            return f"[obsidian_write] 已写入: {target}", ""
        if tool_name == "github":
            from terminal.api._tools import _execute_github_operation

            output = _execute_github_operation(dict(draft))
            return f"[github] {output[:500]}", ""
        if tool_name == "hugo_blog":
            from skills.hugo_blog import run as hugo_blog_run

            args = draft.get("args")
            action = str(args.get("action", "")) if isinstance(args, dict) else ""
            if action == "deploy":
                output = hugo_blog_run(args)
                return f"[hugo_blog] {str(output)[:500]}", ""
            return f"[hugo_blog] action={action} approved, check tool output", ""
        if tool_name == "file_ops":
            from skills.file_ops import run as file_ops_run

            args = draft.get("args")
            output = file_ops_run(args if isinstance(args, dict) else {})
            return f"[file_ops] {str(output)[:500]}", ""
        return f"[{tool_name}] tool approved (no auto-executor for this tool type)", ""
    except Exception as exc:
        return "", f"tool execution failed: {exc}"


def _approval_claim(
    job_id: str,
    payload: Mapping[str, object],
) -> tuple[LegacyJobApprovalClaim, dict[str, object] | None]:
    from terminal.api import job_routes as store

    with store.BACKGROUND_JOB_LOCK:
        store._load_jobs_locked()
        claim = claim_legacy_job_approval(
            store.BACKGROUND_JOBS,
            job_id,
            payload,
            decided_at=datetime.now().isoformat(),
        )
        pending_tool = (
            dict(store.BACKGROUND_JOBS[job_id].get("pendingTool") or {})
            if claim.execute_tool
            else None
        )
        if claim.accepted:
            store._persist_jobs_locked()
        return claim, pending_tool


def _finalize_approved_tool(
    job_id: str,
    receipt_id: str,
    result_text: str,
    error_text: str,
) -> dict[str, object] | None:
    from terminal.api import job_routes as store

    with store.BACKGROUND_JOB_LOCK:
        job = store.BACKGROUND_JOBS.get(job_id)
        if job is None:
            return None
        if not approval_decision_is_current(job, receipt_id):
            mark_approval_manual_uncertain(
                job,
                decided_at=datetime.now().isoformat(),
                reason="approval decision changed during Tool execution",
            )
            store._persist_jobs_locked()
            return dict(job)
        job.pop("pendingTool", None)
        if error_text:
            job["status"] = "failed"
            job["result"] = ""
            job["error"] = error_text
            job["failureKeyword"] = "job_approval_tool_failed"
            job["updatedAt"] = datetime.now().isoformat()
            store._persist_jobs_locked()
            return dict(job)
        job["approvalDisposition"] = "execution_pending_verification"
        store._persist_jobs_locked()
    try:
        completed = complete_legacy_job_result(
            job_id,
            result_text,
            source="approval_tool",
        )
    except JobTerminalFinalizeStaleError:
        with store.BACKGROUND_JOB_LOCK:
            current = store.BACKGROUND_JOBS.get(job_id)
            if current is not None:
                mark_approval_manual_uncertain(
                    current,
                    decided_at=datetime.now().isoformat(),
                    reason="approval Tool result finalize snapshot changed",
                )
                store._persist_jobs_locked()
                return dict(current)
        return None
    if completed is None:
        return store._job_detail(job_id)
    with store.BACKGROUND_JOB_LOCK:
        current = store.BACKGROUND_JOBS.get(job_id)
        if current and current.get("status") == "complete":
            current["approvalDisposition"] = "executed_verified"
            store._persist_jobs_locked()
            return dict(current)
    return completed


def approve_legacy_job_tool(
    job_id: str,
    payload: Mapping[str, object],
) -> dict[str, object]:
    from terminal.api import job_routes as store

    with store.BACKGROUND_JOB_LOCK:
        store._load_jobs_locked()
        if job_id not in store.BACKGROUND_JOBS:
            return LegacyJobApprovalClaim(
                False,
                False,
                False,
                None,
                reason="job_not_found",
            ).to_dict()
    cancellation = job_cancellation_response(
        job_id,
        stage="before_approval_decision",
        side_effect_started=False,
    )
    if cancellation:
        return cancellation
    claim, pending_tool = _approval_claim(job_id, payload)
    result = claim.to_dict()
    if not claim.accepted or not claim.execute_tool:
        result["message"] = (
            "approval decision replayed"
            if claim.replayed
            else "tool denied" if claim.accepted else "job is not waiting approval"
        )
        return result
    tool_name = str((pending_tool or {}).get("toolName", ""))
    draft = (pending_tool or {}).get("draft")
    result_text, error_text = _execute_approved_tool(
        tool_name,
        draft if isinstance(draft, dict) else {},
    )
    cancellation = job_cancellation_response(
        job_id,
        stage="after_approval_tool",
        side_effect_started=True,
    )
    if cancellation:
        return cancellation
    result["job"] = _finalize_approved_tool(
        job_id,
        str(claim.receipt_id),
        result_text,
        error_text,
    )
    result["message"] = "tool executed" if not error_text else error_text
    return result


def approve_legacy_job_tool_response(
    job_id: str,
    payload: Mapping[str, object],
    runtime_context=None,
) -> tuple[int, dict[str, object]]:
    if runtime_context is not None:
        from terminal.api.job_cutover_shadow import observe_legacy_job_command

        command = (
            JobCommand.DENY
            if str(payload.get("decision", "")).strip() == "denied"
            else JobCommand.APPROVE
        )
        observe_legacy_job_command(runtime_context, job_id, command, payload)
    try:
        result = approve_legacy_job_tool(job_id, payload)
    except JobCommandContractError as exc:
        return 400, {
            "ok": False,
            "error": "invalid_job_approval_command",
            "message": str(exc),
        }
    except JobCommandCollisionError as exc:
        return 409, {
            "ok": False,
            "error": "job_command_collision",
            "message": str(exc),
            "commandId": exc.command_id,
        }
    except JobApprovalFingerprintMismatchError as exc:
        return 409, {
            "ok": False,
            "error": "job_approval_fingerprint_mismatch",
            "message": str(exc),
        }
    except JobCommandStaleSnapshotError as exc:
        return 409, {
            "ok": False,
            "error": "job_snapshot_stale",
            "message": str(exc),
        }
    if runtime_context is not None:
        from terminal.api.job_cutover_shadow import observe_legacy_job_result

        observe_legacy_job_result(runtime_context, result)
    return (200 if result.get("ok") else 404), result
