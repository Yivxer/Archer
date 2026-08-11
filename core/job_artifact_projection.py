"""Project verified legacy Job result identity into a shadow Runtime Run."""
from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from core.authority_migration import (
    AuthorityComparisonReceipt,
    AuthorityVerdict,
    MigrationMode,
    build_authority_comparison,
    record_authority_comparison,
)
from core.job_result_evidence import VERIFIER_ID
from core.outcome_store import get_artifact, record_artifact
from core.run_contract import ArtifactRecord
from core.run_store_support import connect
from core.step_store import list_steps_for_run

JOB_ARTIFACT_PROJECTION_CONTRACT_VERSION = 1
JOB_ARTIFACT_PROJECTOR_ID = "legacy.background_job.v1.shadow"


class JobArtifactProjectionConflict(RuntimeError):
    """Raised when an immutable Runtime Artifact identity collides."""


@dataclass(frozen=True, slots=True)
class JobArtifactProjection:
    status: str
    reason: str
    artifact: ArtifactRecord | None
    comparison: AuthorityComparisonReceipt


def _stable_id(prefix: str, *parts: str) -> str:
    material = "\0".join(parts)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _latest_observation_id(db_path: str | Path, legacy_job_id: str) -> str | None:
    conn = connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT id FROM runtime_task_plan_job_observations
            WHERE legacy_job_id = ?
            ORDER BY job_updated_at DESC, observed_at DESC, id DESC
            LIMIT 1
            """,
            (legacy_job_id,),
        ).fetchone()
    finally:
        conn.close()
    return str(row["id"]) if row is not None else None


def _result_anchor_step_id(db_path: str | Path, run_id: str) -> str | None:
    steps = list_steps_for_run(db_path, run_id)
    return max(steps, key=lambda item: item.ordinal).id if steps else None


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _validation_reason(
    *,
    current_observation: bool,
    legacy_status: str,
    evidence: Mapping[str, str],
    step_id: str | None,
) -> str | None:
    if not current_observation:
        return "legacy_job_observation_is_stale"
    if legacy_status != "complete":
        return "legacy_job_result_not_complete"
    if step_id is None:
        return "task_plan_has_no_result_anchor_step"
    required = (
        "artifactId",
        "contentFingerprint",
        "attemptId",
        "attemptIdentitySource",
        "verificationId",
        "verificationArtifactId",
        "verificationExpectedFingerprint",
        "verificationObservedFingerprint",
        "verificationStatus",
        "verifier",
    )
    if any(not evidence.get(field, "").strip() for field in required):
        return "persisted_result_evidence_incomplete"
    fingerprint = evidence["contentFingerprint"]
    if not _valid_sha256(fingerprint):
        return "legacy_artifact_fingerprint_invalid"
    if evidence["verificationStatus"] != "verified":
        return "persisted_result_not_verified"
    if evidence["verifier"] != VERIFIER_ID:
        return "persisted_result_verifier_untrusted"
    if evidence["verificationArtifactId"] != evidence["artifactId"]:
        return "verification_artifact_binding_mismatch"
    if evidence["verificationExpectedFingerprint"] != fingerprint:
        return "verification_expected_fingerprint_mismatch"
    if evidence["verificationObservedFingerprint"] != fingerprint:
        return "verification_observed_fingerprint_mismatch"
    return None


def _artifact_record(
    *,
    run_id: str,
    step_id: str,
    legacy_job_id: str,
    job_kind: str,
    evidence: Mapping[str, str],
) -> ArtifactRecord:
    artifact_id = _stable_id(
        "runtime-job-result",
        run_id,
        step_id,
        legacy_job_id,
        evidence["attemptId"],
        evidence["artifactId"],
        evidence["contentFingerprint"],
    )
    return ArtifactRecord(
        id=artifact_id,
        run_id=run_id,
        step_id=step_id,
        kind="legacy_job_result",
        uri_or_path=f"runtime://jobs/{legacy_job_id}/result",
        fingerprint=evidence["contentFingerprint"],
        media_type="text/plain",
        created_by=JOB_ARTIFACT_PROJECTOR_ID,
        metadata={
            "attemptId": evidence["attemptId"],
            "legacyArtifactId": evidence["artifactId"],
            "legacyVerificationId": evidence["verificationId"],
            "jobKind": job_kind,
        },
    )


def _record_artifact_idempotently(
    db_path: str | Path,
    artifact: ArtifactRecord,
    *,
    created_at: str,
) -> ArtifactRecord:
    existing = get_artifact(db_path, artifact.id)
    if existing is not None:
        if existing != artifact:
            raise JobArtifactProjectionConflict("Runtime Job Artifact collision")
        return existing
    try:
        record_artifact(
            db_path,
            artifact,
            event_id=f"event-{artifact.id}-recorded",
            created_at=created_at,
        )
    except sqlite3.IntegrityError as exc:
        existing = get_artifact(db_path, artifact.id)
        if existing != artifact:
            raise JobArtifactProjectionConflict(
                "Runtime Job Artifact concurrent collision"
            ) from exc
    return artifact


def _comparison(
    *,
    observation_id: str,
    run_id: str,
    legacy_job_id: str,
    job_kind: str,
    legacy_status: str,
    evidence: Mapping[str, str],
    artifact: ArtifactRecord | None,
    reason: str,
    recorded_at: str,
) -> AuthorityComparisonReceipt:
    return build_authority_comparison(
        run_id=run_id,
        domain="background_job",
        legacy_id=legacy_job_id,
        mode=MigrationMode.SHADOW,
        legacy_snapshot={
            "observationId": observation_id,
            "jobId": legacy_job_id,
            "jobKind": job_kind,
            "status": legacy_status,
            "attemptId": evidence.get("attemptId"),
            "artifactId": evidence.get("artifactId"),
            "contentFingerprint": evidence.get("contentFingerprint"),
            "verificationId": evidence.get("verificationId"),
        },
        runtime_snapshot={
            "artifactId": artifact.id if artifact else None,
            "stepId": artifact.step_id if artifact else None,
            "fingerprint": artifact.fingerprint if artifact else None,
            "authorityEnabled": False,
        },
        verdict=(AuthorityVerdict.ALIGNED if artifact else AuthorityVerdict.DRIFTED),
        reason=reason,
        recorded_at=recorded_at,
    )


def project_verified_job_result(
    db_path: str | Path,
    *,
    observation_id: str,
    run_id: str,
    legacy_job_id: str,
    job_kind: str,
    legacy_status: str,
    evidence_summary: Mapping[str, str],
    recorded_at: str,
) -> JobArtifactProjection:
    """Project identity only; never transition Run or Step state."""
    step_id = _result_anchor_step_id(db_path, run_id)
    reason = _validation_reason(
        current_observation=(
            _latest_observation_id(db_path, legacy_job_id) == observation_id
        ),
        legacy_status=legacy_status,
        evidence=evidence_summary,
        step_id=step_id,
    )
    artifact = None
    if reason is None and step_id is not None:
        artifact = _record_artifact_idempotently(
            db_path,
            _artifact_record(
                run_id=run_id,
                step_id=step_id,
                legacy_job_id=legacy_job_id,
                job_kind=job_kind,
                evidence=evidence_summary,
            ),
            created_at=recorded_at,
        )
        reason = "verified_legacy_job_result_projected"
    receipt = record_authority_comparison(
        db_path,
        _comparison(
            observation_id=observation_id,
            run_id=run_id,
            legacy_job_id=legacy_job_id,
            job_kind=job_kind,
            legacy_status=legacy_status,
            evidence=evidence_summary,
            artifact=artifact,
            reason=reason,
            recorded_at=recorded_at,
        ),
    )
    return JobArtifactProjection(
        status="projected" if artifact else "drifted",
        reason=reason,
        artifact=artifact,
        comparison=receipt,
    )
