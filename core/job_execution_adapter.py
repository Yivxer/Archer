"""Pure authority contract for a future Runtime-owned legacy Job adapter."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Collection, Mapping, MutableMapping

from core.run_contract import RunState, StepState

JOB_EXECUTION_ADAPTER_CONTRACT_VERSION = 1
LEGACY_JOB_V0_ADAPTER_ID = "legacy.background_job.v0"


class JobCommand(StrEnum):
    CREATE = "create"
    START = "start"
    RETRY = "retry"
    CANCEL = "cancel"
    APPROVE = "approve"
    DENY = "deny"


class JobExecutionCapability(StrEnum):
    STABLE_COMMAND_ID = "stable_command_id"
    CREATE_IDEMPOTENCY = "create_idempotency"
    START_COMPARE_AND_SET = "start_compare_and_set"
    ATTEMPT_IDENTITY = "attempt_identity"
    COOPERATIVE_CANCELLATION = "cooperative_cancellation"
    APPROVAL_FINGERPRINT = "approval_fingerprint"
    CANCELLATION_SAFE_FINALIZE = "cancellation_safe_finalize"
    RESTART_RECONCILIATION = "restart_reconciliation"
    RESULT_VERIFICATION = "result_verification"
    OUTCOME_VERIFICATION = "outcome_verification"


class JobCommandContractError(ValueError):
    """Raised when a Runtime Job command lacks concurrency or authority data."""


class JobCommandCollisionError(ValueError):
    """A persisted Job command ID was reused with a different payload."""

    def __init__(self, command_id: str, *, command: JobCommand = JobCommand.CREATE) -> None:
        super().__init__(f"job {command.value} command collision: {command_id}")
        self.command_id = command_id


class JobCommandStaleSnapshotError(ValueError):
    """A Job command no longer matches the authoritative legacy snapshot."""


COMMAND_REQUIREMENTS: dict[JobCommand, frozenset[JobExecutionCapability]] = {
    JobCommand.CREATE: frozenset({
        JobExecutionCapability.STABLE_COMMAND_ID,
        JobExecutionCapability.CREATE_IDEMPOTENCY,
        JobExecutionCapability.RESTART_RECONCILIATION,
        JobExecutionCapability.RESULT_VERIFICATION,
        JobExecutionCapability.OUTCOME_VERIFICATION,
    }),
    JobCommand.START: frozenset({
        JobExecutionCapability.STABLE_COMMAND_ID,
        JobExecutionCapability.START_COMPARE_AND_SET,
        JobExecutionCapability.RESTART_RECONCILIATION,
        JobExecutionCapability.RESULT_VERIFICATION,
        JobExecutionCapability.OUTCOME_VERIFICATION,
    }),
    JobCommand.RETRY: frozenset({
        JobExecutionCapability.STABLE_COMMAND_ID,
        JobExecutionCapability.ATTEMPT_IDENTITY,
        JobExecutionCapability.START_COMPARE_AND_SET,
        JobExecutionCapability.RESTART_RECONCILIATION,
        JobExecutionCapability.RESULT_VERIFICATION,
        JobExecutionCapability.OUTCOME_VERIFICATION,
    }),
    JobCommand.CANCEL: frozenset({
        JobExecutionCapability.STABLE_COMMAND_ID,
        JobExecutionCapability.COOPERATIVE_CANCELLATION,
        JobExecutionCapability.CANCELLATION_SAFE_FINALIZE,
    }),
    JobCommand.APPROVE: frozenset({
        JobExecutionCapability.STABLE_COMMAND_ID,
        JobExecutionCapability.APPROVAL_FINGERPRINT,
        JobExecutionCapability.CANCELLATION_SAFE_FINALIZE,
        JobExecutionCapability.RESULT_VERIFICATION,
        JobExecutionCapability.OUTCOME_VERIFICATION,
    }),
    JobCommand.DENY: frozenset({
        JobExecutionCapability.STABLE_COMMAND_ID,
        JobExecutionCapability.APPROVAL_FINGERPRINT,
    }),
}

# Persistence and polling exist, but none of the execution-authority guarantees do.
LEGACY_JOB_V0_CAPABILITIES: frozenset[JobExecutionCapability] = frozenset()


@dataclass(frozen=True, slots=True)
class JobAuthorityDecision:
    adapter_id: str
    command: JobCommand
    permitted: bool
    missing_capabilities: tuple[JobExecutionCapability, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "adapter_id": self.adapter_id,
            "command": self.command.value,
            "permitted": self.permitted,
            "missing_capabilities": [
                capability.value for capability in self.missing_capabilities
            ],
        }


@dataclass(frozen=True, slots=True)
class JobStateProjection:
    run_state: RunState
    step_state: StepState
    terminal: bool
    verification_required: bool


@dataclass(frozen=True, slots=True)
class JobCommandEnvelope:
    command_id: str
    run_id: str
    step_id: str
    command: JobCommand
    requested_at: str
    legacy_job_id: str | None = None
    expected_job_status: str | None = None
    expected_job_updated_at: str | None = None
    attempt_id: str | None = None
    approval_event_id: str | None = None
    approval_fingerprint: str | None = None

    def validate(self) -> None:
        _validate_command_envelope(self)


@dataclass(frozen=True, slots=True)
class LegacyJobStartClaim:
    claimed: bool
    replayed: bool
    job: dict[str, object] | None
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.job is not None,
            "job": self.job,
            "claimed": self.claimed,
            "replayed": self.replayed,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class LegacyJobRetryClaim:
    claimed: bool
    replayed: bool
    job: dict[str, object] | None
    attempt_id: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.job is not None,
            "job": self.job,
            "claimed": self.claimed,
            "replayed": self.replayed,
            "attemptId": self.attempt_id,
            "reason": self.reason,
        }


def job_command_id(
    run_id: str,
    step_id: str,
    command: JobCommand,
    attempt_id: str,
) -> str:
    material = "\0".join((run_id, step_id, command.value, attempt_id))
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"job-command-{digest}"


def legacy_create_command_identity(
    payload: Mapping[str, object],
    *,
    timeout_seconds: int,
    stale_seconds: int | None,
) -> tuple[str | None, str | None]:
    command_id = str(payload.get("commandId", "")).strip()
    if not command_id:
        return None, None
    if len(command_id) > 200:
        raise JobCommandContractError("commandId must be at most 200 characters")
    canonical_payload = {
        "autoStart": payload.get("autoStart", True) is not False,
        "kind": str(payload.get("kind", "")).strip() or "analysis",
        "parentJobId": str(payload.get("parentJobId", "")).strip() or None,
        "prompt": str(payload.get("prompt", "")).strip(),
        "staleSeconds": stale_seconds,
        "timeoutSeconds": timeout_seconds,
        "title": str(payload.get("title", "")).strip(),
        "vaultArgs": payload.get("vaultArgs") if isinstance(payload.get("vaultArgs"), dict) else None,
    }
    encoded = json.dumps(
        canonical_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return command_id, hashlib.sha256(encoded).hexdigest()


LEGACY_JOB_COMMAND_METADATA_FIELDS = (
    "createCommandId",
    "createPayloadFingerprint",
    "startCommandId",
    "startCommandFingerprint",
    "startExpectedStatus",
    "startExpectedUpdatedAt",
    "startClaimedAt",
    "attemptId",
    "attemptIdentitySource",
)


def restore_legacy_job_command_metadata(
    raw: Mapping[str, object],
    job: MutableMapping[str, object],
) -> None:
    for field in LEGACY_JOB_COMMAND_METADATA_FIELDS:
        value = str(raw.get(field, "")).strip()
        if value:
            job[field] = value
    claims = raw.get("retryClaims")
    if isinstance(claims, list):
        job["retryClaims"] = [
            dict(claim)
            for claim in claims
            if isinstance(claim, dict)
        ]


def legacy_job_attempt_identity(
    job: Mapping[str, object],
) -> tuple[str, str]:
    artifact = job.get("resultArtifact")
    if isinstance(artifact, dict):
        artifact_attempt = str(artifact.get("attemptId", "")).strip()
        if artifact_attempt:
            return artifact_attempt, str(
                artifact.get("attemptIdentitySource", "result_artifact")
            )
    attempt_id = str(job.get("attemptId", "")).strip()
    if attempt_id:
        return attempt_id, str(
            job.get("attemptIdentitySource", "retry_command")
        )
    start_command_id = str(job.get("startCommandId", "")).strip()
    if start_command_id:
        return start_command_id, "start_command"
    material = "\0".join((
        str(job.get("id", "")),
        str(job.get("createdAt", "")),
    ))
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"legacy-attempt-{digest}", "legacy_snapshot"


def _restart_claim_integrity(
    raw: Mapping[str, object],
    job_id: str,
) -> tuple[str, str | None]:
    fields = {
        field: str(raw.get(field, "")).strip()
        for field in LEGACY_JOB_COMMAND_METADATA_FIELDS
        if field.startswith("start")
    }
    if not any(fields.values()):
        return "legacy_unclaimed", None
    if not all(fields.values()):
        return "invalid", fields["startCommandId"] or None
    expected = _start_command_fingerprint(
        job_id,
        fields["startExpectedStatus"],
        fields["startExpectedUpdatedAt"],
    )
    integrity = "valid" if fields["startCommandFingerprint"] == expected else "invalid"
    return integrity, fields["startCommandId"]


def _restart_reconciliation_id(
    job_id: str,
    previous_status: str,
    previous_updated_at: str,
    start_command_id: str | None,
) -> str:
    material = "\0".join((
        job_id,
        previous_status,
        previous_updated_at,
        start_command_id or "",
    ))
    return f"job-reconcile-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def reconcile_legacy_job_restart(
    raw: Mapping[str, object],
    job: MutableMapping[str, object],
    *,
    reconciled_at: str,
) -> None:
    existing = raw.get("restartReconciliation")
    if isinstance(existing, dict):
        job["restartReconciliation"] = dict(existing)
    previous_status = str(raw.get("status", "")).strip()
    if previous_status not in {"running", "waiting_approval"}:
        return
    previous_updated_at = str(raw.get("updatedAt", "")).strip()
    integrity, start_command_id = _restart_claim_integrity(raw, str(job["id"]))
    disposition = "failed_closed"
    reason = "execution_interrupted"
    if integrity == "invalid" or previous_status == "waiting_approval":
        disposition = "manual"
        reason = "claim_invalid" if integrity == "invalid" else "approval_interrupted"
    receipt = {
        "id": _restart_reconciliation_id(
            str(job["id"]),
            previous_status,
            previous_updated_at,
            start_command_id,
        ),
        "recordedAt": reconciled_at,
        "previousStatus": previous_status,
        "previousUpdatedAt": previous_updated_at,
        "disposition": disposition,
        "reason": reason,
        "claimIntegrity": integrity,
        "startCommandId": start_command_id,
    }
    job["restartReconciliation"] = receipt
    job["status"] = "failed"
    job["error"] = "job interrupted by API restart"
    job["failureKeyword"] = "job_restart_interrupted"
    job["updatedAt"] = reconciled_at


def _start_command_fingerprint(
    job_id: str,
    expected_status: str,
    expected_updated_at: str,
) -> str:
    material = json.dumps(
        {
            "jobId": job_id,
            "expectedStatus": expected_status,
            "expectedUpdatedAt": expected_updated_at,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _resolve_start_command(
    jobs: Mapping[str, dict],
    job_id: str,
    command_id: str | None,
    expected_status: str | None,
    expected_updated_at: str | None,
) -> tuple[str, str | None, LegacyJobStartClaim | None]:
    command_values = (command_id, expected_status, expected_updated_at)
    if any(value is not None for value in command_values) and not all(command_values):
        raise JobCommandContractError("start command requires identity and expected snapshot")
    stable_command_id = str(command_id or "").strip()
    if not stable_command_id:
        return "", None, None
    if len(stable_command_id) > 200:
        raise JobCommandContractError("commandId must be at most 200 characters")
    if expected_status != "queued":
        raise JobCommandContractError("start command expected status must be queued")
    fingerprint = _start_command_fingerprint(
        job_id,
        str(expected_status),
        str(expected_updated_at),
    )
    existing = next(
        (item for item in jobs.values() if item.get("startCommandId") == stable_command_id),
        None,
    )
    if existing is None:
        return stable_command_id, fingerprint, None
    if existing.get("startCommandFingerprint") != fingerprint:
        raise JobCommandCollisionError(stable_command_id, command=JobCommand.START)
    replay = LegacyJobStartClaim(False, True, dict(existing), "claim_replayed")
    return stable_command_id, fingerprint, replay


def claim_legacy_job_start(
    jobs: MutableMapping[str, dict],
    job_id: str,
    *,
    claimed_at: str,
    command_id: str | None = None,
    expected_status: str | None = None,
    expected_updated_at: str | None = None,
) -> LegacyJobStartClaim:
    stable_command_id, fingerprint, replay = _resolve_start_command(
        jobs,
        job_id,
        command_id,
        expected_status,
        expected_updated_at,
    )
    if replay is not None:
        return replay
    job = jobs.get(job_id)
    if job is None:
        return LegacyJobStartClaim(False, False, None, "job_not_found")
    if stable_command_id and (
        job.get("status") != expected_status
        or job.get("updatedAt") != expected_updated_at
    ):
        raise JobCommandStaleSnapshotError(
            f"job start snapshot is stale: {stable_command_id}"
        )
    if job.get("status") != "queued":
        return LegacyJobStartClaim(False, False, dict(job), "job_not_queued")
    job["status"] = "running"
    job["updatedAt"] = claimed_at
    if stable_command_id and fingerprint:
        job.update({
            "startCommandId": stable_command_id,
            "startCommandFingerprint": fingerprint,
            "startExpectedStatus": str(expected_status),
            "startExpectedUpdatedAt": str(expected_updated_at),
            "startClaimedAt": claimed_at,
        })
    return LegacyJobStartClaim(True, False, dict(job))


def _retry_command_identity(
    job_id: str,
    command_id: str | None,
    expected_status: str | None,
    expected_updated_at: str | None,
    prior_attempt_id: str | None,
) -> tuple[str, str, str] | None:
    values = (
        command_id,
        expected_status,
        expected_updated_at,
        prior_attempt_id,
    )
    if any(value is not None for value in values) and not all(values):
        raise JobCommandContractError(
            "retry command requires identity, expected snapshot, and prior attempt"
        )
    stable_command_id = str(command_id or "").strip()
    if not stable_command_id:
        return None
    if len(stable_command_id) > 200:
        raise JobCommandContractError("commandId must be at most 200 characters")
    if expected_status not in {"complete", "failed", "cancelled"}:
        raise JobCommandContractError(
            "retry command expected status must be terminal"
        )
    material = json.dumps(
        {
            "jobId": job_id,
            "expectedStatus": expected_status,
            "expectedUpdatedAt": expected_updated_at,
            "priorAttemptId": prior_attempt_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    fingerprint = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return stable_command_id, fingerprint, str(prior_attempt_id)


def _existing_retry_claim(
    jobs: Mapping[str, dict],
    command_id: str,
) -> tuple[dict, dict] | None:
    for job in jobs.values():
        claims = job.get("retryClaims")
        if not isinstance(claims, list):
            continue
        for claim in claims:
            if isinstance(claim, dict) and claim.get("commandId") == command_id:
                return job, claim
    return None


def _retry_attempt_id(
    job_id: str,
    command_id: str,
    prior_attempt_id: str,
) -> str:
    material = "\0".join((job_id, command_id, prior_attempt_id))
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"job-attempt-{digest}"


def _archive_result_evidence(
    job: MutableMapping[str, object],
    *,
    archived_for_attempt_id: str,
) -> None:
    artifact = job.get("resultArtifact")
    verification = job.get("resultVerification")
    outcome = job.get("outcomeVerification")
    outcome_history = job.get("outcomeVerificationHistory")
    if (
        isinstance(artifact, dict)
        or isinstance(verification, dict)
        or isinstance(outcome, dict)
    ):
        history = job.setdefault("resultEvidenceHistory", [])
        if not isinstance(history, list):
            history = []
            job["resultEvidenceHistory"] = history
        history.append({
            "artifact": dict(artifact) if isinstance(artifact, dict) else None,
            "verification": (
                dict(verification)
                if isinstance(verification, dict)
                else None
            ),
            "outcomeVerification": (
                dict(outcome) if isinstance(outcome, dict) else None
            ),
            "outcomeVerificationHistory": (
                [dict(item) for item in outcome_history if isinstance(item, dict)]
                if isinstance(outcome_history, list)
                else []
            ),
            "archivedForAttemptId": archived_for_attempt_id,
        })
    job.pop("resultArtifact", None)
    job.pop("resultVerification", None)
    job.pop("outcomeVerification", None)
    job.pop("outcomeVerificationHistory", None)


def _retry_replay(
    jobs: Mapping[str, dict],
    identity: tuple[str, str, str] | None,
) -> LegacyJobRetryClaim | None:
    if identity is None:
        return None
    command_id, fingerprint, _ = identity
    existing = _existing_retry_claim(jobs, command_id)
    if existing is None:
        return None
    existing_job, existing_claim = existing
    if existing_claim.get("fingerprint") != fingerprint:
        raise JobCommandCollisionError(command_id, command=JobCommand.RETRY)
    return LegacyJobRetryClaim(
        False,
        True,
        dict(existing_job),
        str(existing_claim.get("attemptId", "")) or None,
        "claim_replayed",
    )


def _apply_retry_claim(
    job: MutableMapping[str, object],
    job_id: str,
    claimed_at: str,
    actual_prior: str,
    identity: tuple[str, str, str] | None,
) -> LegacyJobRetryClaim:
    stable_command_id, fingerprint, _ = identity or ("", "", "")
    claim_command_id = stable_command_id or _retry_attempt_id(
        job_id, claimed_at, actual_prior
    )
    attempt_id = _retry_attempt_id(job_id, claim_command_id, actual_prior)
    _archive_result_evidence(job, archived_for_attempt_id=attempt_id)
    claim = {
        "commandId": claim_command_id,
        "fingerprint": fingerprint or _retry_attempt_id(
            job_id, str(job.get("updatedAt", "")), actual_prior
        ),
        "expectedStatus": str(job.get("status", "")),
        "expectedUpdatedAt": str(job.get("updatedAt", "")),
        "priorAttemptId": actual_prior,
        "attemptId": attempt_id,
        "claimedAt": claimed_at,
        "identitySource": (
            "retry_command" if stable_command_id else "legacy_retry"
        ),
    }
    claims = job.setdefault("retryClaims", [])
    if not isinstance(claims, list):
        claims = []
        job["retryClaims"] = claims
    claims.append(claim)
    job.update({
        "attemptId": attempt_id,
        "attemptIdentitySource": str(claim["identitySource"]),
        "status": "queued",
        "result": "",
        "updatedAt": claimed_at,
    })
    job.pop("error", None)
    job.pop("failureKeyword", None)
    return LegacyJobRetryClaim(True, False, dict(job), attempt_id)


def claim_legacy_job_retry(
    jobs: MutableMapping[str, dict],
    job_id: str,
    *,
    claimed_at: str,
    command_id: str | None = None,
    expected_status: str | None = None,
    expected_updated_at: str | None = None,
    prior_attempt_id: str | None = None,
) -> LegacyJobRetryClaim:
    identity = _retry_command_identity(
        job_id,
        command_id,
        expected_status,
        expected_updated_at,
        prior_attempt_id,
    )
    replay = _retry_replay(jobs, identity)
    if replay is not None:
        return replay
    job = jobs.get(job_id)
    if job is None:
        return LegacyJobRetryClaim(False, False, None, reason="job_not_found")
    actual_prior, _ = legacy_job_attempt_identity(job)
    stable_command_id, _, expected_prior = identity or ("", "", "")
    if identity is not None and (
        job.get("status") != expected_status
        or job.get("updatedAt") != expected_updated_at
        or actual_prior != expected_prior
    ):
        raise JobCommandStaleSnapshotError(
            f"job retry snapshot is stale: {stable_command_id}"
        )
    if job.get("status") not in {"complete", "failed", "cancelled"}:
        return LegacyJobRetryClaim(
            False, False, dict(job), actual_prior, "job_not_terminal"
        )
    return _apply_retry_claim(
        job, job_id, claimed_at, actual_prior, identity
    )


def _validate_command_envelope(envelope: JobCommandEnvelope) -> None:
    required = (
        envelope.command_id,
        envelope.run_id,
        envelope.step_id,
        envelope.requested_at,
    )
    if not all(value.strip() for value in required):
        raise JobCommandContractError("command identity fields must not be empty")
    if envelope.command is JobCommand.CREATE:
        if envelope.legacy_job_id is not None:
            raise JobCommandContractError("create must not target an existing Job")
        return
    if not all((
        envelope.legacy_job_id,
        envelope.expected_job_status,
        envelope.expected_job_updated_at,
    )):
        raise JobCommandContractError(
            "existing Job commands require an expected snapshot"
        )
    if envelope.command is JobCommand.RETRY and not envelope.attempt_id:
        raise JobCommandContractError("retry requires a stable attempt_id")
    if envelope.command in {JobCommand.APPROVE, JobCommand.DENY} and not all((
        envelope.approval_event_id,
        envelope.approval_fingerprint,
    )):
        raise JobCommandContractError(
            "approval commands require event identity and fingerprint"
        )


def evaluate_job_authority(
    adapter_id: str,
    command: JobCommand,
    capabilities: Collection[JobExecutionCapability],
) -> JobAuthorityDecision:
    provided = frozenset(capabilities)
    missing = tuple(sorted(COMMAND_REQUIREMENTS[command] - provided))
    return JobAuthorityDecision(
        adapter_id=adapter_id,
        command=command,
        permitted=not missing,
        missing_capabilities=missing,
    )


def audit_legacy_job_v0() -> tuple[JobAuthorityDecision, ...]:
    return tuple(
        evaluate_job_authority(
            LEGACY_JOB_V0_ADAPTER_ID,
            command,
            LEGACY_JOB_V0_CAPABILITIES,
        )
        for command in JobCommand
    )


def project_authoritative_job_state(
    legacy_status: str,
    *,
    result_verified: bool | None = None,
    outcome_verified: bool | None = None,
) -> JobStateProjection:
    if legacy_status == "queued":
        return JobStateProjection(RunState.EXECUTING, StepState.READY, False, False)
    if legacy_status == "running":
        return JobStateProjection(RunState.EXECUTING, StepState.RUNNING, False, False)
    if legacy_status == "waiting_approval":
        return JobStateProjection(
            RunState.WAITING_APPROVAL,
            StepState.WAITING_APPROVAL,
            False,
            False,
        )
    if legacy_status == "complete":
        if result_verified is False:
            return JobStateProjection(
                RunState.FAILED,
                StepState.FAILED,
                True,
                False,
            )
        if result_verified is None or outcome_verified is None:
            return JobStateProjection(
                RunState.VERIFYING,
                StepState.VERIFYING,
                False,
                True,
            )
        if outcome_verified:
            return JobStateProjection(
                RunState.COMPLETED,
                StepState.COMPLETED,
                True,
                False,
            )
    if legacy_status in {"complete", "failed"}:
        return JobStateProjection(RunState.FAILED, StepState.FAILED, True, False)
    if legacy_status == "cancelled":
        return JobStateProjection(RunState.CANCELLED, StepState.CANCELLED, True, False)
    raise ValueError(f"unsupported legacy Job status: {legacy_status}")
