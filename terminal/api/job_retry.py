"""Retry orchestration for the authoritative legacy Background Job store."""
from __future__ import annotations

from datetime import datetime
from typing import Mapping

from core.job_execution_adapter import (
    JobCommand,
    JobCommandCollisionError,
    JobCommandContractError,
    JobCommandStaleSnapshotError,
    claim_legacy_job_retry,
)


def _retry_envelope(
    payload: Mapping[str, object],
) -> dict[str, str | None]:
    def optional_text(field: str) -> str | None:
        value = payload.get(field)
        if value is None:
            return None
        return str(value).strip()

    return {
        "command_id": optional_text("commandId"),
        "expected_status": optional_text("expectedStatus"),
        "expected_updated_at": optional_text("expectedUpdatedAt"),
        "prior_attempt_id": optional_text("priorAttemptId"),
    }


def retry_legacy_job(
    job_id: str,
    payload: Mapping[str, object],
) -> dict[str, object]:
    from terminal.api import job_routes as store

    with store.BACKGROUND_JOB_LOCK:
        store._load_jobs_locked()
        claim = claim_legacy_job_retry(
            store.BACKGROUND_JOBS,
            job_id,
            claimed_at=datetime.now().isoformat(),
            **_retry_envelope(payload),
        )
        if claim.claimed:
            store._persist_jobs_locked()
        response = claim.to_dict()
    if claim.claimed:
        store._start_job(job_id)
        response["message"] = "job retry queued"
    elif claim.replayed:
        response["message"] = "job retry claim replayed"
    elif claim.reason == "job_not_terminal":
        response["message"] = "job is already active"
    return response


def retry_legacy_job_response(
    job_id: str,
    payload: Mapping[str, object],
    runtime_context=None,
) -> tuple[int, dict[str, object]]:
    if runtime_context is not None:
        from terminal.api.job_cutover_shadow import observe_legacy_job_command

        observe_legacy_job_command(
            runtime_context, job_id, JobCommand.RETRY, payload
        )
    try:
        result = retry_legacy_job(job_id, payload)
    except JobCommandContractError as exc:
        return 400, {
            "ok": False,
            "error": "invalid_job_retry_command",
            "message": str(exc),
        }
    except JobCommandCollisionError as exc:
        return 409, {
            "ok": False,
            "error": "job_command_collision",
            "message": str(exc),
            "commandId": exc.command_id,
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
