"""Runtime Closure adapter for approval-gated Obsidian writes."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from core.checkpoint_store import record_checkpoint
from core.outcome_store import list_artifacts, record_artifact, record_verification
from core.run_contract import (
    ArtifactRecord,
    RunCheckpoint,
    RunRecord,
    RunState,
    StepRecord,
    StepState,
    StopReason,
    VerificationReceipt,
    VerificationStatus,
)
from core.run_store import create_run, transition_run
from core.runtime_cancellation import CancellationRegistry
from core.step_store import create_step, transition_step

SUCCESS_CRITERIA = (
    "approval_fingerprint_bound",
    "prewrite_conflict_checked",
    "path_exists",
    "content_matches",
)


class ApprovalFingerprintMismatch(ValueError):
    """Raised before execution when approval no longer matches the staged write."""


class RuntimeBindingMismatch(ValueError):
    """Raised before execution when a persisted Run/Step binding is stale or mixed."""


class VerificationRetryUnavailable(ValueError):
    """Raised when a Run cannot be safely reverified without another write."""


class RuntimeCancellationUnavailable(ValueError):
    """Raised when an Obsidian Run cannot accept cancellation."""


@dataclass(frozen=True, slots=True)
class ObsidianRuntimeBinding:
    run_id: str
    step_id: str
    approval_fingerprint: str
    trace_id: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "runId": self.run_id,
            "stepId": self.step_id,
            "approvalFingerprint": self.approval_fingerprint,
            "traceId": self.trace_id,
        }

    @classmethod
    def from_draft(cls, draft: dict) -> ObsidianRuntimeBinding | None:
        raw = draft.get("runtimeContract")
        if not isinstance(raw, dict):
            return None
        run_id = str(raw.get("runId") or "")
        step_id = str(raw.get("stepId") or "")
        fingerprint = str(raw.get("approvalFingerprint") or "")
        if not run_id or not step_id or not fingerprint:
            return None
        return cls(run_id, step_id, fingerprint, str(raw.get("traceId") or ""))


def _event_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _transition_run(
    db_path: str | Path,
    record: RunRecord,
    target: RunState,
    now: str,
    *,
    stop_reason: StopReason | None = None,
) -> RunRecord:
    return transition_run(
        db_path,
        record.id,
        target,
        expected_version=record.version,
        event_id=_event_id("runtime"),
        updated_at=now,
        stop_reason=stop_reason,
    )


def _transition_step(
    db_path: str | Path,
    record: StepRecord,
    target: StepState,
    now: str,
) -> StepRecord:
    return transition_step(
        db_path,
        record.id,
        target,
        expected_state=record.state,
        event_id=_event_id("runtime"),
        transitioned_at=now,
    )


def stage_obsidian_write(
    db_path: str | Path,
    *,
    objective: str,
    approval_fingerprint: str,
    now: str,
    trace_id: str = "",
) -> ObsidianRuntimeBinding:
    run_id = f"run-{uuid4().hex}"
    step_id = f"step-{uuid4().hex}"
    run = RunRecord(
        id=run_id,
        objective=objective,
        source="desktop.obsidian_write",
        current_step_id=step_id,
        context_receipt_id=approval_fingerprint,
        created_at=now,
        updated_at=now,
    )
    create_run(db_path, run, event_id=_event_id("runtime"))
    step = StepRecord(
        id=step_id,
        run_id=run_id,
        ordinal=1,
        title="受控写入 Obsidian",
        kind="tool",
        capability="obsidian_write",
        requires_approval=True,
        success_criteria=SUCCESS_CRITERIA,
    )
    create_step(db_path, step, event_id=_event_id("runtime"), created_at=now)
    run = _transition_run(db_path, run, RunState.UNDERSTANDING, now)
    run = _transition_run(db_path, run, RunState.PLANNING, now)
    _transition_run(db_path, run, RunState.WAITING_APPROVAL, now)
    step = _transition_step(db_path, step, StepState.READY, now)
    _transition_step(db_path, step, StepState.WAITING_APPROVAL, now)
    return ObsidianRuntimeBinding(run_id, step_id, approval_fingerprint, trace_id)


def begin_approved_write(
    db_path: str | Path,
    binding: ObsidianRuntimeBinding,
    *,
    actual_fingerprint: str,
    now: str,
) -> None:
    if actual_fingerprint != binding.approval_fingerprint:
        raise ApprovalFingerprintMismatch("approval fingerprint does not match staged write")
    from core.run_store import get_run
    from core.step_store import get_step

    run = get_run(db_path, binding.run_id)
    step = get_step(db_path, binding.step_id)
    if (
        run is None
        or step is None
        or run.source != "desktop.obsidian_write"
        or run.current_step_id != step.id
        or step.run_id != run.id
        or run.context_receipt_id != binding.approval_fingerprint
        or step.capability != "obsidian_write"
        or run.state is not RunState.WAITING_APPROVAL
        or step.state is not StepState.WAITING_APPROVAL
    ):
        raise RuntimeBindingMismatch("runtime binding does not match persisted Run/Step")
    _transition_run(db_path, run, RunState.EXECUTING, now)
    _transition_step(db_path, step, StepState.RUNNING, now)


def cancel_write(
    db_path: str | Path,
    binding: ObsidianRuntimeBinding,
    *,
    now: str,
) -> None:
    from core.run_store import get_run
    from core.step_store import get_step

    step = get_step(db_path, binding.step_id)
    run = get_run(db_path, binding.run_id)
    if step.state not in {
        StepState.COMPLETED,
        StepState.FAILED,
        StepState.SKIPPED,
        StepState.CANCELLED,
    }:
        _transition_step(db_path, step, StepState.CANCELLED, now)
    if run.state is not RunState.CANCELLING:
        run = _transition_run(db_path, run, RunState.CANCELLING, now)
    _transition_run(
        db_path,
        run,
        RunState.CANCELLED,
        now,
        stop_reason=StopReason.USER_CANCELLED,
    )


def request_write_cancellation(
    db_path: str | Path,
    run_id: str,
    cancellations: CancellationRegistry,
    *,
    now: str,
) -> RunRecord:
    from core.run_store import RunVersionConflict, get_run

    token = cancellations.token(run_id)
    with token.request_guard():
        run = get_run(db_path, run_id)
        if run is None or run.source != "desktop.obsidian_write":
            raise RuntimeCancellationUnavailable("run has no cancellation adapter")
        if not run.current_step_id:
            raise RuntimeCancellationUnavailable("run has no active step")
        binding = ObsidianRuntimeBinding(
            run.id,
            run.current_step_id,
            run.context_receipt_id or "",
        )
        if run.state in {
            RunState.WAITING_APPROVAL,
            RunState.UNCERTAIN,
            RunState.INTERRUPTED,
        }:
            cancel_write(db_path, binding, now=now)
        elif run.state is RunState.EXECUTING:
            try:
                _transition_run(db_path, run, RunState.CANCELLING, now)
            except RunVersionConflict as exc:
                current = get_run(db_path, run_id)
                if current is None or current.state not in {
                    RunState.CANCELLING,
                    RunState.UNCERTAIN,
                    RunState.CANCELLED,
                }:
                    raise RuntimeCancellationUnavailable(
                        "run completed before cancellation was accepted"
                    ) from exc
        elif run.state is not RunState.CANCELLING:
            raise RuntimeCancellationUnavailable(
                f"run cannot be cancelled from {run.state.value}"
            )
        current = get_run(db_path, run_id)
        if current is None:
            raise RuntimeCancellationUnavailable("run disappeared during cancellation")
        return current


def _actual_artifact(
    binding: ObsidianRuntimeBinding,
    path: Path,
    *,
    approval_fingerprint: str,
    verification_spec: dict[str, str | int],
) -> ArtifactRecord:
    content = path.read_bytes()
    return ArtifactRecord(
        id=f"artifact-{uuid4().hex}",
        run_id=binding.run_id,
        step_id=binding.step_id,
        kind="obsidian_markdown",
        uri_or_path=str(path),
        fingerprint=f"sha256:{hashlib.sha256(content).hexdigest()}",
        media_type="text/markdown",
        created_by="obsidian_write",
        metadata={
            "approvalFingerprint": approval_fingerprint,
            "size": len(content),
            "verificationSpec": verification_spec,
        },
    )


def _verification_spec(args: dict) -> dict[str, str | int]:
    content = str(args.get("content") or "")
    return {
        "mode": str(args.get("mode") or "append"),
        "contentLength": len(content),
        "contentSha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }


def _target_artifact(
    binding: ObsidianRuntimeBinding,
    path: Path,
    *,
    approval_fingerprint: str,
    verification_spec: dict[str, str | int],
) -> ArtifactRecord:
    return ArtifactRecord(
        id=f"artifact-{uuid4().hex}",
        run_id=binding.run_id,
        step_id=binding.step_id,
        kind="obsidian_verification_target",
        uri_or_path=str(path),
        fingerprint=f"sha256:{verification_spec['contentSha256']}",
        media_type="text/markdown",
        created_by="obsidian_runtime",
        metadata={
            "approvalFingerprint": approval_fingerprint,
            "verificationSpec": verification_spec,
        },
    )


def _content_matches(path: Path, args: dict) -> bool:
    actual = path.read_text(encoding="utf-8")
    expected = str(args.get("content") or "")
    mode = str(args.get("mode") or "append")
    return actual == expected if mode == "overwrite" else expected in actual


def _content_matches_spec(path: Path, spec: dict) -> bool:
    actual = path.read_text(encoding="utf-8")
    length = int(spec.get("contentLength") or 0)
    expected = str(spec.get("contentSha256") or "")
    mode = str(spec.get("mode") or "append")
    if length <= 0 or not expected:
        raise VerificationRetryUnavailable("verification target is incomplete")
    if mode == "overwrite":
        return hashlib.sha256(actual.encode("utf-8")).hexdigest() == expected
    return any(
        hashlib.sha256(actual[index : index + length].encode("utf-8")).hexdigest()
        == expected
        for index in range(max(0, len(actual) - length + 1))
    )


def _record_failed_receipt(
    db_path: str | Path,
    binding: ObsidianRuntimeBinding,
    *,
    now: str,
    summary: str,
    error_code: str,
) -> None:
    receipt = VerificationReceipt(
        id=f"verification-{uuid4().hex}",
        run_id=binding.run_id,
        step_id=binding.step_id,
        verifier="obsidian_runtime",
        status=VerificationStatus.FAILED,
        criteria=SUCCESS_CRITERIA,
        checked_at=now,
        error_code=error_code,
        summary=summary,
    )
    record_verification(db_path, receipt, event_id=_event_id("runtime"))


def _uncertain_receipt(
    binding: ObsidianRuntimeBinding,
    *,
    now: str,
    summary: str,
    evidence_refs: tuple[str, ...],
    tool_call_id: str | None = None,
) -> VerificationReceipt:
    return VerificationReceipt(
        id=f"verification-{uuid4().hex}",
        run_id=binding.run_id,
        step_id=binding.step_id,
        verifier="obsidian_runtime",
        status=VerificationStatus.UNCERTAIN,
        criteria=SUCCESS_CRITERIA,
        evidence_refs=evidence_refs,
        tool_call_id=tool_call_id,
        checked_at=now,
        error_code="verification_unavailable",
        summary=summary,
    )


def _record_uncertain(
    db_path: str | Path,
    binding: ObsidianRuntimeBinding,
    run: RunRecord,
    *,
    now: str,
    summary: str,
    evidence_refs: tuple[str, ...],
    tool_call_id: str | None = None,
) -> VerificationReceipt:
    receipt = _uncertain_receipt(
        binding,
        now=now,
        summary=summary,
        evidence_refs=evidence_refs,
        tool_call_id=tool_call_id,
    )
    checkpoint = RunCheckpoint(
        id=f"checkpoint-{uuid4().hex}",
        run_id=binding.run_id,
        step_id=binding.step_id,
        resume_state=RunState.VERIFYING,
        cursor={
            "kind": "obsidian_verification",
            "targetArtifactId": evidence_refs[0] if evidence_refs else "",
            "toolCallId": tool_call_id or "",
        },
        created_at=now,
    )
    record_checkpoint(
        db_path,
        checkpoint,
        expected_run_version=run.version,
        event_id=_event_id("runtime"),
    )
    record_verification(db_path, receipt, event_id=_event_id("runtime"))
    _transition_run(
        db_path,
        run,
        RunState.UNCERTAIN,
        now,
        stop_reason=StopReason.VERIFICATION_UNCERTAIN,
    )
    return receipt


def fail_write(
    db_path: str | Path,
    binding: ObsidianRuntimeBinding,
    *,
    now: str,
    summary: str,
    error_code: str,
) -> None:
    from core.run_store import get_run
    from core.step_store import get_step

    _record_failed_receipt(
        db_path, binding, now=now, summary=summary, error_code=error_code
    )
    step = get_step(db_path, binding.step_id)
    run = get_run(db_path, binding.run_id)
    _transition_step(db_path, step, StepState.FAILED, now)
    _transition_run(
        db_path,
        run,
        RunState.FAILED,
        now,
        stop_reason=StopReason.EXECUTOR_FAILED,
    )


def _verification_receipt(
    binding: ObsidianRuntimeBinding,
    artifact: ArtifactRecord,
    *,
    verified: bool,
    tool_call_id: str,
    now: str,
    error_code: str | None = None,
    summary: str = "",
) -> VerificationReceipt:
    return VerificationReceipt(
        id=f"verification-{uuid4().hex}",
        run_id=binding.run_id,
        step_id=binding.step_id,
        verifier="obsidian_runtime",
        status=(
            VerificationStatus.VERIFIED if verified else VerificationStatus.FAILED
        ),
        criteria=SUCCESS_CRITERIA,
        evidence_refs=(artifact.id,),
        tool_call_id=tool_call_id,
        checked_at=now,
        error_code=None if verified else (error_code or "content_mismatch"),
        summary=summary or (
            "Obsidian write verified" if verified else "written content mismatch"
        ),
    )


def _finish_verified_outcome(
    db_path: str | Path,
    *,
    step: StepRecord,
    run: RunRecord,
    verified: bool,
    now: str,
) -> None:
    step_target = StepState.COMPLETED if verified else StepState.FAILED
    run_target = RunState.COMPLETED if verified else RunState.FAILED
    stop_reason = (
        StopReason.GOAL_SATISFIED
        if verified
        else StopReason.VERIFICATION_FAILED
    )
    _transition_step(db_path, step, step_target, now)
    _transition_run(
        db_path,
        run,
        run_target,
        now,
        stop_reason=stop_reason,
    )


def _begin_write_verification(
    db_path: str | Path,
    binding: ObsidianRuntimeBinding,
    *,
    path: Path,
    args: dict,
    approval_fingerprint: str,
    now: str,
) -> tuple[StepRecord, RunRecord, dict[str, str | int], ArtifactRecord]:
    from core.run_store import get_run
    from core.step_store import get_step

    step = _transition_step(
        db_path, get_step(db_path, binding.step_id), StepState.VERIFYING, now
    )
    run = _transition_run(
        db_path, get_run(db_path, binding.run_id), RunState.VERIFYING, now
    )
    spec = _verification_spec(args)
    target = _target_artifact(
        binding,
        path,
        approval_fingerprint=approval_fingerprint,
        verification_spec=spec,
    )
    record_artifact(db_path, target, event_id=_event_id("runtime"), created_at=now)
    return step, run, spec, target


def complete_write(
    db_path: str | Path,
    binding: ObsidianRuntimeBinding,
    *,
    args: dict,
    target_path: str,
    approval_fingerprint: str,
    tool_call_id: str,
    now: str,
) -> VerificationReceipt:
    path = Path(target_path)
    step, run, spec, target = _begin_write_verification(
        db_path,
        binding,
        path=path,
        args=args,
        approval_fingerprint=approval_fingerprint,
        now=now,
    )
    try:
        artifact = _actual_artifact(
            binding,
            path,
            approval_fingerprint=approval_fingerprint,
            verification_spec=spec,
        )
        verified = _content_matches(path, args)
    except (OSError, UnicodeError) as exc:
        return _record_uncertain(
            db_path,
            binding,
            run,
            now=now,
            summary=f"verification unavailable: {exc}",
            evidence_refs=(target.id,),
            tool_call_id=tool_call_id,
        )
    record_artifact(db_path, artifact, event_id=_event_id("runtime"), created_at=now)
    receipt = _verification_receipt(
        binding,
        artifact,
        verified=verified,
        tool_call_id=tool_call_id,
        now=now,
    )
    record_verification(db_path, receipt, event_id=_event_id("runtime"))
    _finish_verified_outcome(db_path, step=step, run=run, verified=verified, now=now)
    return receipt


def suppress_late_write_result(
    db_path: str | Path,
    binding: ObsidianRuntimeBinding,
    *,
    args: dict,
    target_path: str,
    approval_fingerprint: str,
    tool_call_id: str,
    now: str,
) -> VerificationReceipt:
    from core.run_store import get_run
    from core.step_store import get_step

    path = Path(target_path)
    step = get_step(db_path, binding.step_id)
    run = get_run(db_path, binding.run_id)
    if step.state is StepState.RUNNING:
        _transition_step(db_path, step, StepState.VERIFYING, now)
    if run.state is RunState.EXECUTING:
        run = _transition_run(db_path, run, RunState.CANCELLING, now)
    if run.state is not RunState.CANCELLING:
        raise RuntimeCancellationUnavailable("late result run is not cancelling")
    spec = _verification_spec(args)
    target = _target_artifact(
        binding,
        path,
        approval_fingerprint=approval_fingerprint,
        verification_spec=spec,
    )
    record_artifact(db_path, target, event_id=_event_id("runtime"), created_at=now)
    return _record_uncertain(
        db_path,
        binding,
        run,
        now=now,
        summary="late tool result suppressed after cancellation request",
        evidence_refs=(target.id,),
        tool_call_id=tool_call_id,
    )


def _latest_verification_target(
    db_path: str | Path,
    step_id: str,
) -> ArtifactRecord:
    targets = [
        artifact
        for artifact in list_artifacts(db_path, step_id)
        if artifact.kind == "obsidian_verification_target"
    ]
    if not targets:
        raise VerificationRetryUnavailable("no verification target is available")
    return targets[-1]


def _retry_binding(
    run: RunRecord,
    target: ArtifactRecord,
) -> ObsidianRuntimeBinding:
    fingerprint = str(target.metadata.get("approvalFingerprint") or "")
    if not fingerprint:
        raise VerificationRetryUnavailable("approval fingerprint is unavailable")
    return ObsidianRuntimeBinding(run.id, target.step_id, fingerprint)


def _load_retry_context(
    db_path: str | Path,
    run_id: str,
) -> tuple[RunRecord, StepRecord, ArtifactRecord, ObsidianRuntimeBinding, dict]:
    from core.run_store import get_run
    from core.step_store import get_step

    run = get_run(db_path, run_id)
    if run.state is not RunState.UNCERTAIN or not run.current_step_id:
        raise VerificationRetryUnavailable("only uncertain runs can be reverified")
    step = get_step(db_path, run.current_step_id)
    if step.state is not StepState.VERIFYING:
        raise VerificationRetryUnavailable("verification step is not retryable")
    target = _latest_verification_target(db_path, step.id)
    binding = _retry_binding(run, target)
    spec = target.metadata.get("verificationSpec")
    if not isinstance(spec, dict):
        raise VerificationRetryUnavailable("verification spec is unavailable")
    return run, step, target, binding, spec


def _record_retry_result(
    db_path: str | Path,
    *,
    binding: ObsidianRuntimeBinding,
    artifact: ArtifactRecord,
    step: StepRecord,
    run: RunRecord,
    verified: bool,
    now: str,
) -> VerificationReceipt:
    receipt = _verification_receipt(
        binding,
        artifact,
        verified=verified,
        tool_call_id="runtime-verification-retry",
        now=now,
        summary=(
            "Obsidian artifact reverified"
            if verified
            else "Obsidian artifact retry did not match"
        ),
    )
    record_verification(db_path, receipt, event_id=_event_id("runtime"))
    _finish_verified_outcome(
        db_path, step=step, run=run, verified=verified, now=now
    )
    return receipt


def retry_obsidian_verification(
    db_path: str | Path,
    run_id: str,
    *,
    now: str,
) -> VerificationReceipt:
    run, step, target, binding, spec = _load_retry_context(db_path, run_id)
    run = _transition_run(db_path, run, RunState.VERIFYING, now)
    path = Path(target.uri_or_path)
    try:
        artifact = _actual_artifact(
            binding,
            path,
            approval_fingerprint=binding.approval_fingerprint,
            verification_spec=spec,
        )
        verified = path.exists() and _content_matches_spec(path, spec)
    except (OSError, UnicodeError) as exc:
        return _record_uncertain(
            db_path,
            binding,
            run,
            now=now,
            summary=f"verification retry unavailable: {exc}",
            evidence_refs=(target.id,),
            tool_call_id="runtime-verification-retry",
        )
    record_artifact(
        db_path, artifact, event_id=_event_id("runtime"), created_at=now
    )
    return _record_retry_result(
        db_path,
        binding=binding,
        artifact=artifact,
        step=step,
        run=run,
        verified=verified,
        now=now,
    )
