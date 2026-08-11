"""Bridge the existing approval route to the Runtime Closure Obsidian adapter."""
from __future__ import annotations

from typing import Any

from core.obsidian_runtime import (
    ApprovalFingerprintMismatch,
    ObsidianRuntimeBinding,
    begin_approved_write,
    cancel_write,
    complete_write,
    fail_write,
    suppress_late_write_result,
)
from core.runtime_cancellation import CancellationToken


def _binding(draft: dict) -> ObsidianRuntimeBinding | None:
    if str(draft.get("skillName") or "") != "obsidian_write":
        return None
    return ObsidianRuntimeBinding.from_draft(draft)


def _now(runtime_context: Any) -> str:
    return runtime_context.now().isoformat()


def begin_runtime_approval(
    draft: dict,
    *,
    fingerprint: str,
    runtime_context: Any,
) -> ObsidianRuntimeBinding | None:
    binding = _binding(draft)
    if binding is None or runtime_context is None:
        return None
    try:
        begin_approved_write(
            runtime_context.db_path,
            binding,
            actual_fingerprint=fingerprint,
            now=_now(runtime_context),
        )
    except ApprovalFingerprintMismatch:
        fail_write(
            runtime_context.db_path,
            binding,
            now=_now(runtime_context),
            summary="approval fingerprint does not match staged write",
            error_code="approval_fingerprint_mismatch",
        )
        raise
    return binding


def cancel_runtime_approval(draft: dict, *, runtime_context: Any) -> None:
    binding = _binding(draft)
    if binding is None or runtime_context is None:
        return
    cancel_write(runtime_context.db_path, binding, now=_now(runtime_context))


def fail_runtime_approval(
    draft: dict,
    *,
    runtime_context: Any,
    summary: str,
    error_code: str,
) -> None:
    binding = _binding(draft)
    if binding is None or runtime_context is None:
        return
    fail_write(
        runtime_context.db_path,
        binding,
        now=_now(runtime_context),
        summary=summary,
        error_code=error_code,
    )


def _target_path(draft: dict, execution) -> str:
    raw_result = execution.raw_result or {}
    raw_metadata = raw_result.get("metadata")
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    target = str(metadata.get("path") or "")
    if target:
        return target
    receipt = execution.work_receipt or {}
    target = str(receipt.get("target") or "")
    if target:
        return target
    args = draft.get("args") if isinstance(draft.get("args"), dict) else {}
    from skills.obsidian_write import _resolve_note_path

    return str(_resolve_note_path(str(args.get("path") or "")))


def finalize_runtime_execution(
    draft: dict,
    execution,
    *,
    fingerprint: str,
    event_id: str,
    runtime_context: Any,
) -> dict | None:
    binding = _binding(draft)
    if binding is None or runtime_context is None:
        return None
    if not execution.executed:
        conflict = (
            "写入已取消" in execution.output
            and "预览后" in execution.output
        )
        error_code = (
            "prewrite_conflict"
            if conflict or "文件已变化" in execution.output or "冲突" in execution.output
            else "obsidian_write_failed"
        )
        fail_runtime_approval(
            draft,
            runtime_context=runtime_context,
            summary=execution.output or execution.message,
            error_code=error_code,
        )
        return None
    args = draft.get("args") if isinstance(draft.get("args"), dict) else {}
    receipt = complete_write(
        runtime_context.db_path,
        binding,
        args=args,
        target_path=_target_path(draft, execution),
        approval_fingerprint=fingerprint,
        tool_call_id=event_id,
        now=_now(runtime_context),
    )
    return receipt.to_dict()


def finalize_runtime_cancellation(
    draft: dict,
    execution,
    cancellation_token: CancellationToken,
    *,
    fingerprint: str,
    event_id: str,
    runtime_context: Any,
) -> dict | None:
    binding = _binding(draft)
    if (
        binding is None
        or runtime_context is None
        or not cancellation_token.requested
    ):
        return None
    if not cancellation_token.effect_started:
        cancel_write(runtime_context.db_path, binding, now=_now(runtime_context))
        return {
            "cancelled": True,
            "lateResultSuppressed": False,
            "message": "执行已在副作用前取消。",
        }
    args = draft.get("args") if isinstance(draft.get("args"), dict) else {}
    receipt = suppress_late_write_result(
        runtime_context.db_path,
        binding,
        args=args,
        target_path=_target_path(draft, execution),
        approval_fingerprint=fingerprint,
        tool_call_id=event_id,
        now=_now(runtime_context),
    )
    return {
        "cancelled": False,
        "lateResultSuppressed": True,
        "message": "取消发生在副作用临界区后；迟到结果已抑制并等待重新验证。",
        "verificationReceipt": receipt.to_dict(),
    }


def recover_completed_runtime_execution(
    draft: dict,
    *,
    fingerprint: str,
    runtime_context: Any,
):
    """Rebuild delivery data from a verified terminal Run without replaying its write."""
    binding = _binding(draft)
    if binding is None or runtime_context is None:
        return None
    from core.outcome_store import get_artifact, list_verifications
    from core.run_contract import RunState, StepState, VerificationStatus
    from core.run_store import get_run
    from core.step_store import get_step
    from terminal.api.tool_stage import ApprovalExecution

    run = get_run(runtime_context.db_path, binding.run_id)
    step = get_step(runtime_context.db_path, binding.step_id)
    if run is None or step is None:
        return None
    if run.state is not RunState.COMPLETED or step.state is not StepState.COMPLETED:
        return None
    if (
        fingerprint != binding.approval_fingerprint
        or run.source != "desktop.obsidian_write"
        or run.current_step_id != step.id
        or step.run_id != run.id
        or run.context_receipt_id != fingerprint
        or step.capability != "obsidian_write"
    ):
        raise ValueError("completed runtime binding does not match persisted Run/Step")
    receipts = list_verifications(runtime_context.db_path, step.id)
    if not receipts or receipts[-1].status is not VerificationStatus.VERIFIED:
        raise ValueError("completed runtime has no verified receipt")
    receipt = receipts[-1]
    evidence = [
        artifact
        for artifact_id in receipt.evidence_refs
        if (artifact := get_artifact(runtime_context.db_path, artifact_id)) is not None
    ]
    if len(evidence) != len(receipt.evidence_refs) or not evidence:
        raise ValueError("completed runtime verification evidence is incomplete")
    artifact = evidence[-1]
    execution = ApprovalExecution(
        True,
        "Runtime 已验证写入结果；本次仅收敛 Outbox 投递状态。",
        "已从 Runtime Receipt 恢复投递结果。",
        {"target": artifact.uri_or_path, "fingerprint": artifact.fingerprint},
        {"runtimeReused": True},
    )
    return execution, receipt.to_dict()


def finalize_reused_runtime(
    draft: dict,
    reused: dict,
    *,
    fingerprint: str,
    event_id: str,
    runtime_context: Any,
) -> dict | None:
    from terminal.api.tool_stage import ApprovalExecution

    begin_runtime_approval(
        draft,
        fingerprint=fingerprint,
        runtime_context=runtime_context,
    )
    execution = ApprovalExecution(
        bool(reused.get("executed")),
        str(reused.get("output") or ""),
        str(reused.get("message") or ""),
        reused.get("workReceipt"),
        reused,
    )
    return finalize_runtime_execution(
        draft,
        execution,
        fingerprint=fingerprint,
        event_id=event_id,
        runtime_context=runtime_context,
    )


def close_reused_runtime_response(
    draft: dict,
    response: dict,
    *,
    fingerprint: str,
    event_id: str,
    runtime_context: Any,
) -> dict:
    receipt = finalize_reused_runtime(
        draft,
        response,
        fingerprint=fingerprint,
        event_id=event_id,
        runtime_context=runtime_context,
    )
    if receipt:
        response["verificationReceipt"] = receipt
        response["runtimeContract"] = draft.get("runtimeContract")
    return response


__all__ = [
    "ApprovalFingerprintMismatch",
    "begin_runtime_approval",
    "cancel_runtime_approval",
    "close_reused_runtime_response",
    "fail_runtime_approval",
    "finalize_reused_runtime",
    "finalize_runtime_cancellation",
    "finalize_runtime_execution",
    "recover_completed_runtime_execution",
]
