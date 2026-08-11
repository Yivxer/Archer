"""Privacy-minimal receipts for real Background Job cutover observations."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.authority_migration import (
    AuthorityComparisonReceipt,
    AuthorityVerdict,
    build_authority_comparison,
    list_authority_comparisons,
    record_authority_comparison,
)
from core.job_authority_cutover import JobCutoverDecision, JobCutoverRequest
from core.job_execution_adapter import JobCommand

JOB_CUTOVER_OBSERVATION_PREFIX = "background_job_command_observation:"


@dataclass(frozen=True, slots=True)
class JobCutoverObservationCount:
    job_kind: str
    command: JobCommand
    status: str
    count: int


@dataclass(frozen=True, slots=True)
class JobCutoverObservation:
    receipt_id: str
    run_id: str
    job_kind: str
    command: JobCommand
    status: str
    verdict: AuthorityVerdict
    recorded_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "receiptId": self.receipt_id,
            "runId": self.run_id,
            "jobKind": self.job_kind,
            "command": self.command.value,
            "status": self.status,
            "verdict": self.verdict.value,
            "recordedAt": self.recorded_at,
        }


def _reason(job_kind: str, command: JobCommand, status: str) -> str:
    safe_kind = job_kind.strip().lower()
    if not safe_kind or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789_-"
        for character in safe_kind
    ):
        safe_kind = "generic"
    return ":".join((
        JOB_CUTOVER_OBSERVATION_PREFIX.rstrip(":"),
        safe_kind,
        command.value,
        status,
    ))


def record_job_cutover_observation(
    db_path: str | Path,
    request: JobCutoverRequest,
    decision: JobCutoverDecision,
    decision_receipt: AuthorityComparisonReceipt,
    *,
    recorded_at: str,
) -> AuthorityComparisonReceipt:
    """Record only safe command metadata; never persist Job prompt or result."""
    receipt = build_authority_comparison(
        run_id=decision.run_id,
        domain=decision.domain,
        legacy_id=decision.legacy_identity,
        mode=decision.mode,
        legacy_snapshot={
            "commandId": decision.command_id,
            "comparisonReceiptId": request.comparison_receipt_id,
            "decisionReceiptId": decision_receipt.id,
        },
        runtime_snapshot={
            "adapterId": decision.adapter_id,
            "jobKind": request.job_kind,
            "command": decision.command.value,
            "status": decision.status.value,
            "reason": decision.reason,
            "missingCapabilities": [
                capability.value for capability in decision.missing_capabilities
            ],
        },
        verdict=(
            AuthorityVerdict.ALIGNED
            if decision.authority_enabled or decision.status.value == "candidate"
            else AuthorityVerdict.DRIFTED
        ),
        reason=_reason(
            request.job_kind,
            decision.command,
            decision.status.value,
        ),
        recorded_at=recorded_at,
    )
    return record_authority_comparison(db_path, receipt)


def list_job_cutover_observation_counts(
    db_path: str | Path,
    *,
    run_id: str | None = None,
) -> list[JobCutoverObservationCount]:
    counts: dict[tuple[str, JobCommand, str], int] = {}
    for observation in list_job_cutover_observations(
        db_path,
        run_id=run_id,
    ):
        key = (observation.job_kind, observation.command, observation.status)
        counts[key] = counts.get(key, 0) + 1
    return [
        JobCutoverObservationCount(
            job_kind=job_kind,
            command=command,
            status=status,
            count=count,
        )
        for (job_kind, command, status), count in sorted(
            counts.items(),
            key=lambda item: (item[0][0], item[0][1].value, item[0][2]),
        )
    ]


def list_job_cutover_observations(
    db_path: str | Path,
    *,
    run_id: str | None = None,
) -> list[JobCutoverObservation]:
    observations: list[JobCutoverObservation] = []
    for receipt in list_authority_comparisons(
        db_path,
        domain="background_job",
        run_id=run_id,
    ):
        if not receipt.reason.startswith(JOB_CUTOVER_OBSERVATION_PREFIX):
            continue
        parts = receipt.reason.split(":")
        if len(parts) != 4:
            continue
        try:
            command = JobCommand(parts[2])
        except ValueError:
            continue
        observations.append(JobCutoverObservation(
            receipt_id=receipt.id,
            run_id=receipt.run_id,
            job_kind=parts[1],
            command=command,
            status=parts[3],
            verdict=receipt.verdict,
            recorded_at=receipt.recorded_at,
        ))
    return observations
