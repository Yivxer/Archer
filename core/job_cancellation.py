"""Stable cancellation requests for authoritative legacy Background Jobs."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping, MutableMapping

from core.job_execution_adapter import (
    JobCommand,
    JobCommandCollisionError,
    JobCommandContractError,
    JobCommandStaleSnapshotError,
    legacy_job_attempt_identity,
)

ACTIVE_JOB_STATUSES = {"queued", "running", "waiting_approval"}


@dataclass(frozen=True, slots=True)
class LegacyJobCancellationClaim:
    accepted: bool
    replayed: bool
    job: dict[str, object] | None
    request_id: str | None = None
    disposition: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.job is not None,
            "job": self.job,
            "accepted": self.accepted,
            "replayed": self.replayed,
            "requestId": self.request_id,
            "disposition": self.disposition,
            "reason": self.reason,
        }


def _sha256(*parts: str) -> str:
    material = "\0".join(parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _cancellation_identity(
    job_id: str,
    command_id: str | None,
    expected_status: str | None,
    expected_updated_at: str | None,
    attempt_id: str | None,
) -> tuple[str, str, str] | None:
    values = (command_id, expected_status, expected_updated_at, attempt_id)
    if any(value is not None for value in values) and not all(values):
        raise JobCommandContractError(
            "cancel command requires identity, active snapshot, and attempt"
        )
    stable_command_id = str(command_id or "").strip()
    if not stable_command_id:
        return None
    if len(stable_command_id) > 200:
        raise JobCommandContractError("commandId must be at most 200 characters")
    if expected_status not in ACTIVE_JOB_STATUSES:
        raise JobCommandContractError(
            "cancel command expected status must be active"
        )
    payload = json.dumps(
        {
            "attemptId": attempt_id,
            "expectedStatus": expected_status,
            "expectedUpdatedAt": expected_updated_at,
            "jobId": job_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return stable_command_id, hashlib.sha256(payload.encode()).hexdigest(), str(attempt_id)


def _existing_cancellation_request(
    jobs: Mapping[str, dict],
    command_id: str,
) -> tuple[dict, dict] | None:
    for job in jobs.values():
        requests = job.get("cancellationRequests")
        if not isinstance(requests, list):
            continue
        for request in requests:
            if (
                isinstance(request, dict)
                and request.get("commandId") == command_id
            ):
                return job, request
    return None


def _cancellation_replay(
    jobs: Mapping[str, dict],
    identity: tuple[str, str, str] | None,
) -> LegacyJobCancellationClaim | None:
    if identity is None:
        return None
    command_id, fingerprint, _ = identity
    existing = _existing_cancellation_request(jobs, command_id)
    if existing is None:
        return None
    job, request = existing
    if request.get("fingerprint") != fingerprint:
        raise JobCommandCollisionError(command_id, command=JobCommand.CANCEL)
    return LegacyJobCancellationClaim(
        False,
        True,
        dict(job),
        str(request.get("id", "")) or None,
        str(request.get("disposition", "")) or None,
        "request_replayed",
    )


def _append_cancellation_request(
    job: MutableMapping[str, object],
    *,
    job_id: str,
    requested_at: str,
    actual_attempt_id: str,
    identity: tuple[str, str, str] | None,
) -> LegacyJobCancellationClaim:
    command_id, fingerprint, _ = identity or ("", "", "")
    request_command_id = command_id or (
        f"legacy-cancel-{_sha256(job_id, actual_attempt_id, requested_at)[:24]}"
    )
    request_id = (
        f"job-cancel-request-{_sha256(request_command_id, fingerprint)[:24]}"
    )
    cooperative = bool(command_id) and job.get("status") != "queued"
    disposition = "cooperative_pending" if cooperative else "cancelled_before_start"
    request = {
        "id": request_id,
        "commandId": request_command_id,
        "fingerprint": fingerprint or _sha256(
            job_id, str(job.get("updatedAt", "")), actual_attempt_id
        ),
        "expectedStatus": str(job.get("status", "")),
        "expectedUpdatedAt": str(job.get("updatedAt", "")),
        "attemptId": actual_attempt_id,
        "requestedAt": requested_at,
        "disposition": disposition,
        "identitySource": "cancel_command" if command_id else "legacy_cancel",
    }
    requests = job.setdefault("cancellationRequests", [])
    if not isinstance(requests, list):
        requests = []
        job["cancellationRequests"] = requests
    requests.append(request)
    job["activeCancellationRequestId"] = request_id
    job["updatedAt"] = requested_at
    if not cooperative:
        job["status"] = "cancelled"
        job["error"] = "job cancelled by user"
        job["cancellationDisposition"] = disposition
    return LegacyJobCancellationClaim(
        True, False, dict(job), request_id, disposition
    )


def claim_legacy_job_cancellation(
    jobs: MutableMapping[str, dict],
    job_id: str,
    *,
    requested_at: str,
    command_id: str | None = None,
    expected_status: str | None = None,
    expected_updated_at: str | None = None,
    attempt_id: str | None = None,
) -> LegacyJobCancellationClaim:
    identity = _cancellation_identity(
        job_id,
        command_id,
        expected_status,
        expected_updated_at,
        attempt_id,
    )
    replay = _cancellation_replay(jobs, identity)
    if replay is not None:
        return replay
    job = jobs.get(job_id)
    if job is None:
        return LegacyJobCancellationClaim(False, False, None, reason="job_not_found")
    actual_attempt_id, _ = legacy_job_attempt_identity(job)
    _, _, expected_attempt_id = identity or ("", "", "")
    if identity is not None and (
        job.get("status") != expected_status
        or job.get("updatedAt") != expected_updated_at
        or actual_attempt_id != expected_attempt_id
    ):
        raise JobCommandStaleSnapshotError(
            f"job cancel snapshot is stale: {command_id}"
        )
    if job.get("status") not in ACTIVE_JOB_STATUSES:
        return LegacyJobCancellationClaim(
            False, False, dict(job), reason="job_not_active"
        )
    return _append_cancellation_request(
        job,
        job_id=job_id,
        requested_at=requested_at,
        actual_attempt_id=actual_attempt_id,
        identity=identity,
    )


def pending_legacy_job_cancellation(
    job: Mapping[str, object],
) -> dict[str, object] | None:
    request_id = str(job.get("activeCancellationRequestId", "")).strip()
    requests = job.get("cancellationRequests")
    acknowledgements = job.get("cancellationAcknowledgements")
    if not request_id or not isinstance(requests, list):
        return None
    if isinstance(acknowledgements, list) and any(
        isinstance(item, dict) and item.get("requestId") == request_id
        for item in acknowledgements
    ):
        return None
    return next(
        (
            dict(item)
            for item in reversed(requests)
            if isinstance(item, dict) and item.get("id") == request_id
        ),
        None,
    )


def acknowledge_legacy_job_cancellation(
    job: MutableMapping[str, object],
    *,
    acknowledged_at: str,
    stage: str,
    side_effect_started: bool,
) -> bool:
    request = pending_legacy_job_cancellation(job)
    if request is None:
        return False
    request_id = str(request["id"])
    disposition = (
        "manual_uncertain" if side_effect_started else "cancelled_cooperatively"
    )
    acknowledgement = {
        "id": f"job-cancel-ack-{_sha256(request_id, stage, disposition)[:24]}",
        "requestId": request_id,
        "attemptId": request.get("attemptId"),
        "acknowledgedAt": acknowledged_at,
        "stage": stage,
        "sideEffectStarted": side_effect_started,
        "disposition": disposition,
    }
    acknowledgements = job.setdefault("cancellationAcknowledgements", [])
    if not isinstance(acknowledgements, list):
        acknowledgements = []
        job["cancellationAcknowledgements"] = acknowledgements
    acknowledgements.append(acknowledgement)
    job["cancellationDisposition"] = disposition
    job["status"] = "failed" if side_effect_started else "cancelled"
    job["error"] = (
        "job cancellation requires manual verification"
        if side_effect_started
        else "job cancelled cooperatively"
    )
    if side_effect_started:
        job["failureKeyword"] = "job_cancellation_uncertain"
    job["updatedAt"] = acknowledged_at
    return True


def restore_legacy_job_cancellation_metadata(
    raw: Mapping[str, object],
    job: MutableMapping[str, object],
) -> None:
    for field in ("activeCancellationRequestId", "cancellationDisposition"):
        value = str(raw.get(field, "")).strip()
        if value:
            job[field] = value
    for field in ("cancellationRequests", "cancellationAcknowledgements"):
        value = raw.get(field)
        if isinstance(value, list):
            job[field] = [
                dict(item) for item in value if isinstance(item, dict)
            ]
