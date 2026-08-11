"""Persist and independently verify successful legacy Job results."""
from __future__ import annotations

from datetime import datetime

from core.job_cancellation import acknowledge_legacy_job_cancellation
from core.job_result_evidence import (
    resolve_legacy_job_result_artifact,
    verify_persisted_job_result,
)
from core.job_terminal_finalize import (
    ACTIVE_JOB_STATUSES,
    assert_legacy_job_finalize_snapshot,
    legacy_job_finalize_snapshot,
    record_legacy_job_terminal_finalize,
)


def _persist_result_artifact(
    job_id: str,
    result: str,
    *,
    expected_attempt_id: str | None,
    expected_updated_at: str | None,
) -> tuple[dict[str, object], str, str] | None:
    from terminal.api import job_routes as store

    with store.BACKGROUND_JOB_LOCK:
        store._load_jobs_locked()
        job = store.BACKGROUND_JOBS.get(job_id)
        if not job or job.get("status") in {"failed", "cancelled"}:
            return None
        assert_legacy_job_finalize_snapshot(
            job,
            expected_attempt_id=expected_attempt_id,
            expected_updated_at=expected_updated_at,
            allowed_statuses=ACTIVE_JOB_STATUSES | {"complete"},
        )
        if acknowledge_legacy_job_cancellation(
            job,
            acknowledged_at=datetime.now().isoformat(),
            stage="result_persist",
            side_effect_started=True,
        ):
            store._persist_jobs_locked()
            return None
        created_at = datetime.now().isoformat()
        artifact, created = resolve_legacy_job_result_artifact(
            job,
            result,
            created_at=created_at,
        )
        if created:
            job["result"] = result
            job["resultArtifact"] = artifact
            job["updatedAt"] = created_at
            store._persist_jobs_locked()
        snapshot = legacy_job_finalize_snapshot(job)
        return dict(artifact), snapshot.updated_at, snapshot.attempt_id


def _finalize_result_verification(
    job_id: str,
    artifact_id: str,
    receipt: dict[str, object],
    *,
    source: str,
    expected_attempt_id: str | None,
    expected_updated_at: str,
) -> dict | None:
    from terminal.api import job_routes as store

    with store.BACKGROUND_JOB_LOCK:
        job = store.BACKGROUND_JOBS.get(job_id)
        artifact = job.get("resultArtifact") if job else None
        if not job or job.get("status") == "cancelled":
            return None
        if not isinstance(artifact, dict) or artifact.get("id") != artifact_id:
            return None
        if acknowledge_legacy_job_cancellation(
            job,
            acknowledged_at=datetime.now().isoformat(),
            stage="result_finalize",
            side_effect_started=True,
        ):
            store._persist_jobs_locked()
            return None
        assert_legacy_job_finalize_snapshot(
            job,
            expected_attempt_id=expected_attempt_id,
            expected_updated_at=expected_updated_at,
            allowed_statuses=ACTIVE_JOB_STATUSES | {"complete"},
        )
        job["resultVerification"] = receipt
        status = str(receipt.get("status", "uncertain"))
        job["status"] = "complete" if status == "verified" else "failed"
        if status != "verified":
            job["error"] = f"job result verification {status}"
            job["failureKeyword"] = f"job_result_verification_{status}"
        else:
            job.pop("error", None)
            job.pop("failureKeyword", None)
        job["updatedAt"] = datetime.now().isoformat()
        record_legacy_job_terminal_finalize(
            job,
            status=str(job["status"]),
            source=source,
            finalized_at=str(job["updatedAt"]),
        )
        store._persist_jobs_locked()
        return dict(job)


def complete_legacy_job_result(
    job_id: str,
    result: str,
    *,
    source: str = "job_worker",
    expected_attempt_id: str | None = None,
    expected_updated_at: str | None = None,
) -> dict | None:
    from terminal.api import job_routes as store

    persisted = _persist_result_artifact(
        job_id,
        result,
        expected_attempt_id=expected_attempt_id,
        expected_updated_at=expected_updated_at,
    )
    if persisted is None:
        return None
    artifact, persisted_updated_at, persisted_attempt_id = persisted
    artifact_id = str(artifact["id"])
    receipt = verify_persisted_job_result(
        store.BACKGROUND_JOBS_PATH,
        job_id,
        artifact_id,
        verified_at=datetime.now().isoformat(),
    )
    finalized = _finalize_result_verification(
        job_id,
        artifact_id,
        receipt,
        source=source,
        expected_attempt_id=persisted_attempt_id,
        expected_updated_at=persisted_updated_at,
    )
    if finalized is None:
        return None
    from terminal.api.job_outcome_verification import (
        verify_and_persist_legacy_job_outcome,
    )

    verify_and_persist_legacy_job_outcome(job_id)
    return store._job_detail(job_id)
