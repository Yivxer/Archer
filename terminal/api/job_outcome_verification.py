"""Independent business outcome verification for legacy Background Jobs."""
from __future__ import annotations

import sqlite3
from datetime import datetime

from core.job_execution_adapter import legacy_job_attempt_identity
from core.job_outcome_verification import verify_legacy_job_outcome


def _outcome_binding(job: dict) -> tuple[str, str, str]:
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
    return attempt_id, artifact_id, verification_id


def _vault_reflection_facts() -> dict[str, object]:
    try:
        from workflows.vault_reflection import list_recent_reflections

        records = list_recent_reflections(limit=100)
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return {"resolverStatus": "unavailable", "reflectionRecords": []}
    return {
        "resolverStatus": "available",
        "reflectionRecords": records,
    }


def _observed_outcome_facts(job: dict) -> dict[str, object]:
    if job.get("kind") == "vault_reflection":
        return _vault_reflection_facts()
    return {"resolverStatus": "not_required"}


def _persist_outcome_receipt(
    job_id: str,
    binding: tuple[str, str, str],
    receipt: dict[str, object],
) -> dict[str, object] | None:
    from terminal.api import job_routes as store

    with store.BACKGROUND_JOB_LOCK:
        current = store.BACKGROUND_JOBS.get(job_id)
        if current is None or _outcome_binding(current) != binding:
            return None
        existing = current.get("outcomeVerification")
        if isinstance(existing, dict) and existing.get("id") == receipt["id"]:
            return dict(existing)
        if isinstance(existing, dict):
            history = current.setdefault("outcomeVerificationHistory", [])
            if not isinstance(history, list):
                history = []
                current["outcomeVerificationHistory"] = history
            history.append(dict(existing))
        current["outcomeVerification"] = receipt
        current["updatedAt"] = datetime.now().isoformat()
        store._persist_jobs_locked()
        return dict(receipt)


def verify_and_persist_legacy_job_outcome(
    job_id: str,
) -> dict[str, object] | None:
    from terminal.api import job_routes as store

    with store.BACKGROUND_JOB_LOCK:
        job = store.BACKGROUND_JOBS.get(job_id)
        if job is None:
            return None
        snapshot = dict(job)
        binding = _outcome_binding(snapshot)
    receipt = verify_legacy_job_outcome(
        snapshot,
        _observed_outcome_facts(snapshot),
        verified_at=datetime.now().isoformat(),
    )
    return _persist_outcome_receipt(job_id, binding, receipt)
