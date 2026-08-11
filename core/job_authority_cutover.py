"""Non-executing authority cutover decision for legacy Background Jobs."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Mapping

from core.authority_migration import (
    AuthorityComparisonReceipt,
    AuthorityMigrationError,
    AuthorityVerdict,
    MigrationMode,
    build_authority_comparison,
    list_authority_comparisons,
    record_authority_comparison,
    snapshot_fingerprint,
)
from core.job_adapter_shadow import (
    LEGACY_JOB_V1_SHADOW_ADAPTER_ID,
    audit_job_adapter_v1_shadow,
)
from core.job_command_authority import (
    audit_job_command_reachability,
    resolve_job_command_migration_mode,
)
from core.job_execution_adapter import (
    JobCommand,
    JobCommandContractError,
    JobCommandEnvelope,
    JobExecutionCapability,
)
from core.run_contract import RunState, StepState
from core.run_store import get_run
from core.step_store import get_step
from core.task_plan_job_shadow import (
    TaskPlanJobObservation,
    list_task_plan_job_bindings,
    list_task_plan_job_observations,
)

BACKGROUND_JOB_DOMAIN = "background_job"
CUTOVER_REASON_PREFIX = "background_job_cutover_"
SHADOW_COMPARISON_REASONS = frozenset({
    "legacy_job_shadow_projection_aligned",
    "legacy_job_create_shadow_projection_aligned",
})

_COMMAND_STATUSES: dict[JobCommand, frozenset[str]] = {
    JobCommand.START: frozenset({"queued"}),
    JobCommand.RETRY: frozenset({"complete", "failed", "cancelled"}),
    JobCommand.CANCEL: frozenset({"queued", "running", "waiting_approval"}),
    JobCommand.APPROVE: frozenset({"waiting_approval"}),
    JobCommand.DENY: frozenset({"waiting_approval"}),
}


class JobCutoverStatus(StrEnum):
    CANDIDATE = "candidate"
    AUTHORITATIVE = "authoritative"
    FORBIDDEN = "forbidden"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class JobCutoverRequest:
    envelope: JobCommandEnvelope
    job_kind: str
    expected_run_version: int
    expected_run_state: RunState
    expected_step_state: StepState
    expected_attempt_id: str | None
    comparison_receipt_id: str


@dataclass(frozen=True, slots=True)
class JobCutoverDecision:
    status: JobCutoverStatus
    adapter_id: str
    domain: str
    mode: MigrationMode
    command: JobCommand
    command_id: str
    run_id: str
    step_id: str
    legacy_identity: str
    comparison_receipt_id: str | None
    missing_capabilities: tuple[JobExecutionCapability, ...]
    reason: str
    authority_enabled: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "adapterId": self.adapter_id,
            "domain": self.domain,
            "mode": self.mode.value,
            "command": self.command.value,
            "commandId": self.command_id,
            "runId": self.run_id,
            "stepId": self.step_id,
            "legacyIdentity": self.legacy_identity,
            "comparisonReceiptId": self.comparison_receipt_id,
            "missingCapabilities": [
                item.value for item in self.missing_capabilities
            ],
            "reason": self.reason,
            "authorityEnabled": self.authority_enabled,
        }


def _legacy_identity(request: JobCutoverRequest) -> str:
    if request.envelope.command is JobCommand.CREATE:
        return request.envelope.command_id
    return request.envelope.legacy_job_id or ""


def _decision(
    request: JobCutoverRequest,
    *,
    mode: MigrationMode,
    status: JobCutoverStatus,
    reason: str,
    receipt: AuthorityComparisonReceipt | None = None,
    missing: tuple[JobExecutionCapability, ...] = (),
) -> JobCutoverDecision:
    return JobCutoverDecision(
        status=status,
        adapter_id=LEGACY_JOB_V1_SHADOW_ADAPTER_ID,
        domain=BACKGROUND_JOB_DOMAIN,
        mode=mode,
        command=request.envelope.command,
        command_id=request.envelope.command_id,
        run_id=request.envelope.run_id,
        step_id=request.envelope.step_id,
        legacy_identity=_legacy_identity(request),
        comparison_receipt_id=receipt.id if receipt is not None else None,
        missing_capabilities=missing,
        reason=reason,
        authority_enabled=status is JobCutoverStatus.AUTHORITATIVE,
    )


def _latest_shadow_comparison(
    db_path: str | Path,
    request: JobCutoverRequest,
) -> AuthorityComparisonReceipt | None:
    identity = _legacy_identity(request)
    receipts = list_authority_comparisons(
        db_path,
        domain=BACKGROUND_JOB_DOMAIN,
        run_id=request.envelope.run_id,
    )
    candidates = [
        receipt
        for receipt in receipts
        if receipt.legacy_id == identity
        and receipt.reason in SHADOW_COMPARISON_REASONS
    ]
    if request.envelope.command is not JobCommand.CREATE:
        observation = _latest_job_observation(db_path, request)
        if observation is None:
            return None
        evidence = observation.evidence_summary
        latest_fingerprint = snapshot_fingerprint({
            "jobId": observation.legacy_job_id,
            "jobKind": request.job_kind,
            "status": observation.legacy_status,
            "updatedAt": observation.job_updated_at,
            "attemptId": evidence.get("attemptId"),
            "verificationId": evidence.get("verificationId"),
            "outcomeVerificationId": evidence.get("outcomeVerificationId"),
        })
        candidates = [
            receipt for receipt in candidates
            if receipt.legacy_snapshot_fingerprint == latest_fingerprint
        ]
    return candidates[-1] if candidates else None


def _latest_job_observation(
    db_path: str | Path,
    request: JobCutoverRequest,
):
    observations = list_task_plan_job_observations(
        db_path,
        request.envelope.run_id,
    )
    matching = [
        item
        for item in observations
        if item.legacy_job_id == request.envelope.legacy_job_id
    ]
    return max(
        matching,
        key=lambda item: (
            item.job_updated_at,
            item.observed_at,
            item.id,
        ),
        default=None,
    )


def _comparison_matches_request(
    request: JobCutoverRequest,
    receipt: AuthorityComparisonReceipt,
    observation: TaskPlanJobObservation | None,
) -> bool:
    envelope = request.envelope
    if envelope.command is JobCommand.CREATE:
        return (
            receipt.legacy_snapshot_fingerprint == snapshot_fingerprint({
                "commandId": envelope.command_id,
                "jobExists": False,
            })
            and receipt.runtime_snapshot_fingerprint == snapshot_fingerprint({
                "jobKind": request.job_kind,
            })
        )
    if observation is None:
        return False
    evidence = observation.evidence_summary
    return receipt.legacy_snapshot_fingerprint == snapshot_fingerprint({
        "jobId": observation.legacy_job_id,
        "jobKind": request.job_kind,
        "status": observation.legacy_status,
        "updatedAt": observation.job_updated_at,
        "attemptId": evidence.get("attemptId"),
        "verificationId": evidence.get("verificationId"),
        "outcomeVerificationId": evidence.get("outcomeVerificationId"),
    })


def evaluate_job_authority_cutover(
    db_path: str | Path,
    config: Mapping[str, object],
    request: JobCutoverRequest,
) -> JobCutoverDecision:
    try:
        mode = resolve_job_command_migration_mode(
            config,
            request.job_kind,
            request.envelope.command,
        )
    except AuthorityMigrationError:
        mode = MigrationMode.SHADOW
        return _decision(
            request,
            mode=mode,
            status=JobCutoverStatus.FORBIDDEN,
            reason="invalid_migration_mode",
        )
    try:
        request.envelope.validate()
    except JobCommandContractError:
        return _decision(
            request,
            mode=mode,
            status=JobCutoverStatus.FORBIDDEN,
            reason="invalid_command_envelope",
        )

    run = get_run(db_path, request.envelope.run_id)
    if run is None:
        return _decision(request, mode=mode, status=JobCutoverStatus.CONFLICT,
                         reason="run_not_found")
    if run.version != request.expected_run_version:
        return _decision(request, mode=mode, status=JobCutoverStatus.CONFLICT,
                         reason="run_version_stale")
    if run.state is not request.expected_run_state:
        return _decision(request, mode=mode, status=JobCutoverStatus.CONFLICT,
                         reason="run_state_stale")

    step = get_step(db_path, request.envelope.step_id)
    if step is None or step.run_id != run.id:
        return _decision(request, mode=mode, status=JobCutoverStatus.CONFLICT,
                         reason="step_not_current_for_run")
    if step.state is not request.expected_step_state:
        return _decision(request, mode=mode, status=JobCutoverStatus.CONFLICT,
                         reason="step_state_stale")

    envelope = request.envelope
    observation = None
    if envelope.command is JobCommand.CREATE:
        if request.expected_attempt_id is not None:
            return _decision(request, mode=mode,
                             status=JobCutoverStatus.CONFLICT,
                             reason="create_attempt_must_be_absent")
    else:
        if not request.expected_attempt_id:
            return _decision(request, mode=mode,
                             status=JobCutoverStatus.CONFLICT,
                             reason="expected_attempt_missing")
        if envelope.attempt_id != request.expected_attempt_id:
            return _decision(request, mode=mode,
                             status=JobCutoverStatus.CONFLICT,
                             reason="command_attempt_stale")
        observation = _latest_job_observation(db_path, request)
        if observation is None:
            return _decision(request, mode=mode,
                             status=JobCutoverStatus.CONFLICT,
                             reason="job_observation_missing")
        binding = next(
            (
                item
                for item in list_task_plan_job_bindings(db_path, run.id)
                if item.legacy_job_id == envelope.legacy_job_id
            ),
            None,
        )
        if binding is None or binding.job_kind != request.job_kind:
            return _decision(request, mode=mode,
                             status=JobCutoverStatus.CONFLICT,
                             reason="job_kind_binding_conflict")
        if (
            observation.legacy_status != envelope.expected_job_status
            or observation.job_updated_at != envelope.expected_job_updated_at
        ):
            return _decision(request, mode=mode,
                             status=JobCutoverStatus.CONFLICT,
                             reason="legacy_job_snapshot_stale")
        observed_attempt = observation.evidence_summary.get("attemptId")
        if observed_attempt != request.expected_attempt_id:
            return _decision(request, mode=mode,
                             status=JobCutoverStatus.CONFLICT,
                             reason="legacy_job_attempt_stale")
        allowed_statuses = _COMMAND_STATUSES[envelope.command]
        if observation.legacy_status not in allowed_statuses:
            return _decision(request, mode=mode,
                             status=JobCutoverStatus.CONFLICT,
                             reason="command_status_conflict")

    receipt = _latest_shadow_comparison(db_path, request)
    if receipt is None:
        return _decision(request, mode=mode, status=JobCutoverStatus.FORBIDDEN,
                         reason="shadow_comparison_missing")
    if receipt.id != request.comparison_receipt_id:
        return _decision(request, mode=mode, status=JobCutoverStatus.CONFLICT,
                         reason="comparison_receipt_stale", receipt=receipt)
    if not _comparison_matches_request(request, receipt, observation):
        return _decision(request, mode=mode, status=JobCutoverStatus.CONFLICT,
                         reason="comparison_snapshot_conflict", receipt=receipt)
    if receipt.verdict is not AuthorityVerdict.ALIGNED:
        return _decision(request, mode=mode, status=JobCutoverStatus.FORBIDDEN,
                         reason="shadow_comparison_drifted", receipt=receipt)

    reachability = audit_job_command_reachability(
        request.job_kind,
        request.envelope.command,
    )
    if not reachability.reachable:
        return _decision(
            request,
            mode=mode,
            status=JobCutoverStatus.FORBIDDEN,
            reason="command_not_reachable_for_job_kind",
            receipt=receipt,
        )

    audit = audit_job_adapter_v1_shadow(request.job_kind)
    command_decision = next(
        item for item in audit.command_decisions
        if item.command is request.envelope.command
    )
    if not command_decision.permitted:
        return _decision(
            request,
            mode=mode,
            status=JobCutoverStatus.FORBIDDEN,
            reason="command_capability_incomplete",
            receipt=receipt,
            missing=command_decision.missing_capabilities,
        )
    status = (
        JobCutoverStatus.AUTHORITATIVE
        if mode is MigrationMode.AUTHORITATIVE
        else JobCutoverStatus.CANDIDATE
    )
    return _decision(
        request,
        mode=mode,
        status=status,
        reason="authority_contract_satisfied",
        receipt=receipt,
    )


def record_job_authority_cutover_decision(
    db_path: str | Path,
    config: Mapping[str, object],
    request: JobCutoverRequest,
    *,
    recorded_at: str,
) -> tuple[JobCutoverDecision, AuthorityComparisonReceipt]:
    decision = evaluate_job_authority_cutover(db_path, config, request)
    envelope = request.envelope
    receipt = build_authority_comparison(
        run_id=envelope.run_id,
        domain=BACKGROUND_JOB_DOMAIN,
        legacy_id=_legacy_identity(request),
        mode=decision.mode,
        legacy_snapshot={
            "commandId": envelope.command_id,
            "jobId": envelope.legacy_job_id,
            "status": envelope.expected_job_status,
            "updatedAt": envelope.expected_job_updated_at,
            "attemptId": request.expected_attempt_id,
            "comparisonReceiptId": request.comparison_receipt_id,
        },
        runtime_snapshot={
            "runId": envelope.run_id,
            "runVersion": request.expected_run_version,
            "runState": request.expected_run_state.value,
            "stepId": envelope.step_id,
            "stepState": request.expected_step_state.value,
            **decision.to_dict(),
        },
        verdict=(
            AuthorityVerdict.ALIGNED
            if decision.status in {
                JobCutoverStatus.CANDIDATE,
                JobCutoverStatus.AUTHORITATIVE,
            }
            else AuthorityVerdict.DRIFTED
        ),
        reason=f"{CUTOVER_REASON_PREFIX}{decision.status.value}_{decision.reason}",
        recorded_at=recorded_at,
    )
    return decision, record_authority_comparison(db_path, receipt)
