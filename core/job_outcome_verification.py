"""Business outcome verification contracts for legacy Background Jobs."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePath
from typing import Mapping, Sequence

from core.job_execution_adapter import legacy_job_attempt_identity

OUTCOME_VERIFIER_ID = "legacy_job.outcome.v1"
VAULT_REFLECTION_VERIFIER_ID = "legacy_job.vault_reflection.record.v1"
OUTCOME_STATUSES = frozenset({"verified", "failed", "uncertain"})


@dataclass(frozen=True, slots=True)
class LegacyJobOutcomeDecision:
    status: str
    reason: str
    verifier: str
    evidence: tuple[dict[str, object], ...] = ()


def _parsed_datetime(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except (TypeError, ValueError):
        return None


def _reflection_records(
    observed_facts: Mapping[str, object],
) -> list[dict[str, object]]:
    records = observed_facts.get("reflectionRecords")
    if not isinstance(records, list):
        return []
    return [dict(item) for item in records if isinstance(item, dict)]


def _same_note_identity(expected_path: str, result_path: str) -> bool:
    if expected_path == result_path:
        return True
    expected = PurePath(expected_path)
    result = PurePath(result_path)
    if expected.is_absolute() == result.is_absolute():
        return False
    absolute, relative = (
        (expected, result) if expected.is_absolute() else (result, expected)
    )
    if not relative.parts or ".." in relative.parts:
        return False
    return absolute.parts[-len(relative.parts) :] == relative.parts


def _record_matches(
    record: Mapping[str, object],
    result: Mapping[str, object],
    *,
    note_path: str,
    created_at: object,
) -> bool:
    if str(record.get("note_path", "")) != note_path:
        return False
    job_created = _parsed_datetime(created_at)
    reflected_at = _parsed_datetime(record.get("reflected_at"))
    if job_created and (reflected_at is None or reflected_at < job_created):
        return False
    expected_pending = result.get("pending_ids")
    if isinstance(expected_pending, list):
        observed_pending = record.get("pending_ids")
        if not isinstance(observed_pending, list):
            return False
        if sorted(map(str, observed_pending)) != sorted(map(str, expected_pending)):
            return False
    expected_soul = result.get("soul_proposal_id")
    return expected_soul is None or record.get("soul_proposal_id") == expected_soul


def _match_reflection(
    records: Sequence[Mapping[str, object]],
    result: Mapping[str, object],
    *,
    note_path: str,
    created_at: object,
) -> dict[str, object] | None:
    return next(
        (
            dict(record)
            for record in records
            if _record_matches(
                record,
                result,
                note_path=note_path,
                created_at=created_at,
            )
        ),
        None,
    )


def _verify_single_reflection(
    job: Mapping[str, object],
    result: Mapping[str, object],
    records: Sequence[Mapping[str, object]],
) -> LegacyJobOutcomeDecision:
    vault_args = job.get("vaultArgs")
    expected_path = (
        str(vault_args.get("note_path", "")).strip()
        if isinstance(vault_args, dict)
        else ""
    )
    result_path = str(result.get("note_path", "")).strip()
    note_path = result_path or expected_path
    if not note_path or (
        expected_path
        and not _same_note_identity(expected_path, result_path)
    ):
        return LegacyJobOutcomeDecision(
            "failed",
            "reflection_note_path_mismatch",
            VAULT_REFLECTION_VERIFIER_ID,
        )
    matched = _match_reflection(
        records,
        result,
        note_path=note_path,
        created_at=job.get("createdAt"),
    )
    if matched is None:
        return LegacyJobOutcomeDecision(
            "failed",
            "reflection_record_missing",
            VAULT_REFLECTION_VERIFIER_ID,
        )
    return LegacyJobOutcomeDecision(
        "verified",
        "reflection_record_matches",
        VAULT_REFLECTION_VERIFIER_ID,
        (matched,),
    )


def _verify_reflection_batch(
    job: Mapping[str, object],
    result: Mapping[str, object],
    records: Sequence[Mapping[str, object]],
) -> LegacyJobOutcomeDecision:
    reflected = result.get("reflected")
    if not isinstance(reflected, list):
        return LegacyJobOutcomeDecision(
            "failed",
            "reflection_batch_invalid",
            VAULT_REFLECTION_VERIFIER_ID,
        )
    try:
        total = int(result.get("total", -1))
    except (TypeError, ValueError):
        total = -1
    if total != len(reflected):
        return LegacyJobOutcomeDecision(
            "failed",
            "reflection_batch_count_mismatch",
            VAULT_REFLECTION_VERIFIER_ID,
        )
    if not reflected:
        return LegacyJobOutcomeDecision(
            "uncertain",
            "no_reflection_records_to_verify",
            VAULT_REFLECTION_VERIFIER_ID,
        )
    return _match_reflection_batch(job, reflected, records)


def _match_reflection_batch(
    job: Mapping[str, object],
    reflected: Sequence[object],
    records: Sequence[Mapping[str, object]],
) -> LegacyJobOutcomeDecision:
    matched: list[dict[str, object]] = []
    for item in reflected:
        if not isinstance(item, dict):
            return LegacyJobOutcomeDecision(
                "failed",
                "reflection_batch_invalid",
                VAULT_REFLECTION_VERIFIER_ID,
            )
        record = _match_reflection(
            records,
            item,
            note_path=str(item.get("note_path", "")).strip(),
            created_at=job.get("createdAt"),
        )
        if record is None:
            return LegacyJobOutcomeDecision(
                "failed",
                "reflection_record_missing",
                VAULT_REFLECTION_VERIFIER_ID,
            )
        matched.append(record)
    return LegacyJobOutcomeDecision(
        "verified",
        "reflection_records_match",
        VAULT_REFLECTION_VERIFIER_ID,
        tuple(matched),
    )


def _verify_vault_reflection(
    job: Mapping[str, object],
    observed_facts: Mapping[str, object],
) -> LegacyJobOutcomeDecision:
    if observed_facts.get("resolverStatus") != "available":
        return LegacyJobOutcomeDecision(
            "uncertain",
            "reflection_evidence_unavailable",
            VAULT_REFLECTION_VERIFIER_ID,
        )
    try:
        result = json.loads(str(job.get("result", "")))
    except json.JSONDecodeError:
        return LegacyJobOutcomeDecision(
            "failed",
            "result_not_structured_json",
            VAULT_REFLECTION_VERIFIER_ID,
        )
    if not isinstance(result, dict) or result.get("ok") is not True:
        return LegacyJobOutcomeDecision(
            "failed",
            "workflow_result_not_successful",
            VAULT_REFLECTION_VERIFIER_ID,
        )
    records = _reflection_records(observed_facts)
    vault_args = job.get("vaultArgs")
    if isinstance(vault_args, dict) and vault_args.get("note_path"):
        return _verify_single_reflection(job, result, records)
    return _verify_reflection_batch(job, result, records)


def _outcome_decision(
    job: Mapping[str, object],
    observed_facts: Mapping[str, object],
) -> LegacyJobOutcomeDecision:
    artifact = job.get("resultArtifact")
    verification = job.get("resultVerification")
    if not isinstance(artifact, dict) or not isinstance(verification, dict):
        return LegacyJobOutcomeDecision(
            "uncertain",
            "persisted_result_evidence_missing",
            OUTCOME_VERIFIER_ID,
        )
    persisted_status = str(verification.get("status", "uncertain"))
    if persisted_status != "verified":
        status = "failed" if persisted_status == "failed" else "uncertain"
        return LegacyJobOutcomeDecision(
            status,
            "persisted_result_not_verified",
            OUTCOME_VERIFIER_ID,
        )
    if str(job.get("kind", "")) == "vault_reflection":
        return _verify_vault_reflection(job, observed_facts)
    return LegacyJobOutcomeDecision(
        "uncertain",
        "no_deterministic_verifier_for_kind",
        OUTCOME_VERIFIER_ID,
    )


def verify_legacy_job_outcome(
    job: Mapping[str, object],
    observed_facts: Mapping[str, object],
    *,
    verified_at: str,
) -> dict[str, object]:
    decision = _outcome_decision(job, observed_facts)
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
    evidence_json = json.dumps(
        decision.evidence,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    evidence_fingerprint = hashlib.sha256(evidence_json.encode()).hexdigest()
    material = "\0".join((
        str(job.get("id", "")),
        attempt_id,
        artifact_id,
        verification_id,
        decision.verifier,
        decision.status,
        decision.reason,
        evidence_fingerprint,
    ))
    receipt_id = hashlib.sha256(material.encode()).hexdigest()[:24]
    return {
        "id": f"job-outcome-{receipt_id}",
        "jobId": str(job.get("id", "")),
        "jobKind": str(job.get("kind", "")),
        "attemptId": attempt_id,
        "artifactId": artifact_id or None,
        "resultVerificationId": verification_id or None,
        "status": decision.status,
        "reason": decision.reason,
        "verifier": decision.verifier,
        "evidenceFingerprint": evidence_fingerprint,
        "verifiedAt": verified_at,
    }
