"""Cancellation request orchestration for legacy Background Jobs."""
from __future__ import annotations

import time
from collections.abc import MutableMapping
from datetime import datetime
from threading import Thread
from typing import Mapping

from core.job_cancellation import (
    acknowledge_legacy_job_cancellation,
    claim_legacy_job_cancellation,
    restore_legacy_job_cancellation_metadata,
)
from core.job_execution_adapter import (
    JobCommand,
    JobCommandCollisionError,
    JobCommandContractError,
    JobCommandStaleSnapshotError,
)


def _cancel_envelope(
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
        "attempt_id": optional_text("attemptId"),
    }


def restore_legacy_job_cancellation(
    raw: Mapping[str, object],
    job: MutableMapping[str, object],
    *,
    reconciled_at: str,
) -> None:
    restore_legacy_job_cancellation_metadata(raw, job)
    if raw.get("status") in {"running", "waiting_approval"}:
        acknowledge_legacy_job_cancellation(
            job,
            acknowledged_at=reconciled_at,
            stage="restart_reconciliation",
            side_effect_started=True,
        )


def request_legacy_job_cancellation(
    job_id: str,
    payload: Mapping[str, object],
) -> dict[str, object]:
    from terminal.api import job_routes as store

    with store.BACKGROUND_JOB_LOCK:
        store._load_jobs_locked()
        claim = claim_legacy_job_cancellation(
            store.BACKGROUND_JOBS,
            job_id,
            requested_at=datetime.now().isoformat(),
            **_cancel_envelope(payload),
        )
        if claim.accepted:
            store._persist_jobs_locked()
        result = claim.to_dict()
    if claim.disposition == "cooperative_pending":
        result["message"] = "job cancellation requested"
    elif claim.accepted:
        result["message"] = "job cancelled"
    elif claim.replayed:
        result["message"] = "job cancellation request replayed"
    elif claim.reason == "job_not_active":
        result["message"] = "job already finished"
    return result


def request_legacy_job_cancellation_response(
    job_id: str,
    payload: Mapping[str, object],
    runtime_context=None,
) -> tuple[int, dict[str, object]]:
    if runtime_context is not None:
        from terminal.api.job_cutover_shadow import observe_legacy_job_command

        observe_legacy_job_command(
            runtime_context, job_id, JobCommand.CANCEL, payload
        )
    try:
        result = request_legacy_job_cancellation(job_id, payload)
    except JobCommandContractError as exc:
        return 400, {
            "ok": False,
            "error": "invalid_job_cancel_command",
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


def job_cancellation_checkpoint(
    job_id: str,
    *,
    stage: str,
    side_effect_started: bool,
) -> bool:
    from terminal.api import job_routes as store

    with store.BACKGROUND_JOB_LOCK:
        job = store.BACKGROUND_JOBS.get(job_id)
        if not job:
            return True
        if job.get("status") == "cancelled":
            return True
        acknowledged = acknowledge_legacy_job_cancellation(
            job,
            acknowledged_at=datetime.now().isoformat(),
            stage=stage,
            side_effect_started=side_effect_started,
        )
        if acknowledged:
            store._persist_jobs_locked()
        return acknowledged


def job_cancellation_response(
    job_id: str,
    *,
    stage: str,
    side_effect_started: bool,
) -> dict[str, object] | None:
    from terminal.api import job_routes as store

    if not job_cancellation_checkpoint(
        job_id,
        stage=stage,
        side_effect_started=side_effect_started,
    ):
        return None
    return {
        "ok": True,
        "job": store._job_detail(job_id),
        "message": (
            "job cancellation requires manual verification"
            if side_effect_started
            else "job cancellation acknowledged"
        ),
    }


def wait_for_legacy_job_worker(
    job_id: str,
    worker: Thread,
    *,
    timeout_seconds: int,
    cancel_flag: MutableMapping[str, bool],
) -> str:
    deadline = time.monotonic() + timeout_seconds
    while worker.is_alive():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "timeout"
        worker.join(timeout=min(0.05, remaining))
        if job_cancellation_checkpoint(
            job_id,
            stage="worker_wait",
            side_effect_started=True,
        ):
            cancel_flag["cancelled"] = True
            return "cancelled"
    return "finished"
