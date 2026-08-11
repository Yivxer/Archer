"""Pure contracts for terminalizing legacy Background Jobs."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping, MutableMapping, Sequence

from core.job_execution_adapter import legacy_job_attempt_identity

ACTIVE_JOB_STATUSES = frozenset({"queued", "running", "waiting_approval"})
TERMINAL_JOB_STATUSES = frozenset({"complete", "failed", "cancelled"})


class JobTerminalFinalizeStaleError(ValueError):
    """A terminal write no longer matches the active Job attempt or snapshot."""


@dataclass(frozen=True, slots=True)
class LegacyJobFinalizeSnapshot:
    attempt_id: str
    status: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class LegacyChildRollupAssessment:
    ready: bool
    terminal: bool
    reason: str


def legacy_job_finalize_snapshot(
    job: Mapping[str, object],
) -> LegacyJobFinalizeSnapshot:
    attempt_id, _ = legacy_job_attempt_identity(job)
    return LegacyJobFinalizeSnapshot(
        attempt_id=attempt_id,
        status=str(job.get("status", "")),
        updated_at=str(job.get("updatedAt", "")),
    )


def assert_legacy_job_finalize_snapshot(
    job: Mapping[str, object],
    *,
    expected_attempt_id: str | None = None,
    expected_updated_at: str | None = None,
    allowed_statuses: frozenset[str] = ACTIVE_JOB_STATUSES,
) -> LegacyJobFinalizeSnapshot:
    snapshot = legacy_job_finalize_snapshot(job)
    if snapshot.status not in allowed_statuses:
        raise JobTerminalFinalizeStaleError(
            f"job status {snapshot.status or 'missing'} cannot be finalized"
        )
    if expected_attempt_id and snapshot.attempt_id != expected_attempt_id:
        raise JobTerminalFinalizeStaleError("job finalize attempt is stale")
    if expected_updated_at and snapshot.updated_at != expected_updated_at:
        raise JobTerminalFinalizeStaleError("job finalize snapshot is stale")
    return snapshot


def legacy_job_result_is_verified(job: Mapping[str, object]) -> bool:
    if job.get("status") != "complete":
        return False
    artifact = job.get("resultArtifact")
    verification = job.get("resultVerification")
    if not isinstance(artifact, dict) or not isinstance(verification, dict):
        return False
    explicit_attempt_id = str(
        job.get("attemptId") or job.get("startCommandId") or ""
    ).strip()
    return (
        bool(str(job.get("result", "")).strip())
        and (
            not explicit_attempt_id
            or artifact.get("attemptId") == explicit_attempt_id
        )
        and verification.get("artifactId") == artifact.get("id")
        and verification.get("status") == "verified"
    )


def assess_legacy_child_rollup(
    children: Sequence[Mapping[str, object] | None],
) -> LegacyChildRollupAssessment:
    if not children or any(child is None for child in children):
        return LegacyChildRollupAssessment(False, True, "child_missing")
    concrete = [child for child in children if child is not None]
    if any(child.get("status") in ACTIVE_JOB_STATUSES for child in concrete):
        return LegacyChildRollupAssessment(False, False, "child_active")
    if any(child.get("status") != "complete" for child in concrete):
        return LegacyChildRollupAssessment(False, True, "child_not_complete")
    if any(not legacy_job_result_is_verified(child) for child in concrete):
        return LegacyChildRollupAssessment(
            False,
            True,
            "child_result_unverified",
        )
    return LegacyChildRollupAssessment(True, True, "children_verified")


def _terminal_receipt_identity(
    job: Mapping[str, object],
    status: str,
    source: str,
) -> tuple[str, str, str, str]:
    attempt_id, _ = legacy_job_attempt_identity(job)
    artifact = job.get("resultArtifact")
    verification = job.get("resultVerification")
    artifact_id = (
        str(artifact.get("id", "")) if isinstance(artifact, dict) else ""
    )
    verification_id = (
        str(verification.get("id", ""))
        if isinstance(verification, dict)
        else ""
    )
    material = "\0".join((
        str(job.get("id", "")),
        attempt_id,
        status,
        source,
        artifact_id,
        verification_id,
        str(job.get("failureKeyword", "")),
    ))
    receipt_id = (
        f"job-finalize-{hashlib.sha256(material.encode()).hexdigest()[:24]}"
    )
    return receipt_id, attempt_id, artifact_id, verification_id


def record_legacy_job_terminal_finalize(
    job: MutableMapping[str, object],
    *,
    status: str,
    source: str,
    finalized_at: str,
) -> dict[str, object]:
    if status not in TERMINAL_JOB_STATUSES:
        raise ValueError(f"invalid terminal Job status: {status}")
    receipt_id, attempt_id, artifact_id, verification_id = (
        _terminal_receipt_identity(job, status, source)
    )
    receipts = job.setdefault("terminalFinalizations", [])
    if not isinstance(receipts, list):
        receipts = []
        job["terminalFinalizations"] = receipts
    existing = next(
        (
            item
            for item in receipts
            if isinstance(item, dict) and item.get("id") == receipt_id
        ),
        None,
    )
    if existing is None:
        existing = {
            "id": receipt_id,
            "jobId": str(job.get("id", "")),
            "attemptId": attempt_id,
            "status": status,
            "source": source,
            "artifactId": artifact_id or None,
            "verificationId": verification_id or None,
            "finalizedAt": finalized_at,
        }
        receipts.append(existing)
    job["activeTerminalFinalizationId"] = receipt_id
    return dict(existing)


def restore_legacy_job_terminal_metadata(
    raw: Mapping[str, object],
    job: MutableMapping[str, object],
) -> None:
    active_id = str(raw.get("activeTerminalFinalizationId", "")).strip()
    if active_id:
        job["activeTerminalFinalizationId"] = active_id
    receipts = raw.get("terminalFinalizations")
    if isinstance(receipts, list):
        job["terminalFinalizations"] = [
            dict(item) for item in receipts if isinstance(item, dict)
        ]
