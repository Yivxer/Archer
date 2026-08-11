"""Immutable evidence and post-persist verification for legacy Job results."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping, MutableMapping

from core.job_execution_adapter import legacy_job_attempt_identity

VERIFIER_ID = "legacy_job.persisted_result.v1"


class JobResultArtifactCollisionError(ValueError):
    """An immutable legacy Job result Artifact would be overwritten."""


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_legacy_job_result_artifact(
    job: Mapping[str, object],
    result: str,
    *,
    created_at: str,
) -> dict[str, object]:
    job_id = str(job.get("id", "")).strip()
    attempt_id, attempt_source = legacy_job_attempt_identity(job)
    fingerprint = _sha256(result)
    artifact_material = "\0".join((job_id, attempt_id, fingerprint))
    return {
        "id": f"job-result-{_sha256(artifact_material)[:24]}",
        "type": "legacy_job_result",
        "jobId": job_id,
        "startCommandId": str(job.get("startCommandId", "")).strip() or None,
        "attemptId": attempt_id,
        "attemptIdentitySource": attempt_source,
        "createdAt": created_at,
        "contentFingerprint": fingerprint,
        "contentLength": len(result),
        "immutable": True,
    }


def resolve_legacy_job_result_artifact(
    job: Mapping[str, object],
    result: str,
    *,
    created_at: str,
) -> tuple[dict[str, object], bool]:
    existing = job.get("resultArtifact")
    if not isinstance(existing, dict):
        return build_legacy_job_result_artifact(job, result, created_at=created_at), True
    if existing.get("contentFingerprint") != _sha256(result):
        raise JobResultArtifactCollisionError(
            f"job result artifact collision: {job.get('id', '')}"
        )
    return dict(existing), False


def _verification_receipt(
    artifact: Mapping[str, object],
    *,
    status: str,
    reason: str,
    verified_at: str,
    observed_fingerprint: str | None = None,
) -> dict[str, object]:
    identity = "\0".join((
        str(artifact.get("id", "")),
        status,
        reason,
        observed_fingerprint or "",
    ))
    return {
        "id": f"job-verification-{_sha256(identity)[:24]}",
        "artifactId": artifact.get("id"),
        "jobId": artifact.get("jobId"),
        "status": status,
        "reason": reason,
        "verifiedAt": verified_at,
        "verifier": VERIFIER_ID,
        "expectedFingerprint": artifact.get("contentFingerprint"),
        "observedFingerprint": observed_fingerprint,
    }


def _load_persisted_job(path: Path, job_id: str) -> dict | None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_jobs = payload.get("jobs", []) if isinstance(payload, dict) else payload
    if not isinstance(raw_jobs, list):
        return None
    return next(
        (
            item
            for item in raw_jobs
            if isinstance(item, dict) and str(item.get("id", "")) == job_id
        ),
        None,
    )


def _verify_loaded_job_result(
    job: Mapping[str, object],
    job_id: str,
    artifact_id: str,
    verified_at: str,
) -> dict[str, object]:
    artifact = job.get("resultArtifact")
    if not isinstance(artifact, dict) or artifact.get("id") != artifact_id:
        return _verification_receipt(
            {"id": artifact_id, "jobId": job_id},
            status="failed",
            reason="artifact_missing_or_replaced",
            verified_at=verified_at,
        )
    result = str(job.get("result", ""))
    observed = _sha256(result)
    status, reason = "verified", "persisted_result_matches"
    if not result:
        status, reason = "failed", "result_empty"
    elif observed != artifact.get("contentFingerprint"):
        status, reason = "failed", "result_fingerprint_mismatch"
    existing = job.get("resultVerification")
    if (
        isinstance(existing, dict)
        and existing.get("artifactId") == artifact_id
        and existing.get("status") == status
        and existing.get("observedFingerprint") == observed
    ):
        return dict(existing)
    return _verification_receipt(
        artifact,
        status=status,
        reason=reason,
        verified_at=verified_at,
        observed_fingerprint=observed,
    )


def verify_persisted_job_result(
    path: Path,
    job_id: str,
    artifact_id: str,
    *,
    verified_at: str,
) -> dict[str, object]:
    try:
        job = _load_persisted_job(path, job_id)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _verification_receipt(
            {"id": artifact_id, "jobId": job_id},
            status="uncertain",
            reason="persisted_job_unreadable",
            verified_at=verified_at,
        )
    if job is None:
        return _verification_receipt(
            {"id": artifact_id, "jobId": job_id},
            status="failed",
            reason="persisted_job_missing",
            verified_at=verified_at,
        )
    return _verify_loaded_job_result(job, job_id, artifact_id, verified_at)


def restore_legacy_job_result_evidence(
    raw: Mapping[str, object],
    job: MutableMapping[str, object],
) -> None:
    for field in (
        "resultArtifact",
        "resultVerification",
        "outcomeVerification",
    ):
        value = raw.get(field)
        if isinstance(value, dict):
            job[field] = dict(value)
    history = raw.get("resultEvidenceHistory")
    if isinstance(history, list):
        job["resultEvidenceHistory"] = [
            dict(entry)
            for entry in history
            if isinstance(entry, dict)
        ]
    outcome_history = raw.get("outcomeVerificationHistory")
    if isinstance(outcome_history, list):
        job["outcomeVerificationHistory"] = [
            dict(entry)
            for entry in outcome_history
            if isinstance(entry, dict)
        ]
