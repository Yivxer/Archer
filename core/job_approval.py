"""Stable approve/deny decisions for legacy Background Job tools."""
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


class JobApprovalFingerprintMismatchError(ValueError):
    """The approved pending Tool no longer matches the supplied fingerprint."""


@dataclass(frozen=True, slots=True)
class LegacyJobApprovalClaim:
    accepted: bool
    replayed: bool
    execute_tool: bool
    job: dict[str, object] | None
    receipt_id: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.job is not None,
            "job": self.job,
            "accepted": self.accepted,
            "replayed": self.replayed,
            "executeTool": self.execute_tool,
            "receiptId": self.receipt_id,
            "reason": self.reason,
        }


def _sha256(*parts: str) -> str:
    material = "\0".join(parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def legacy_job_pending_tool_fingerprint(
    pending_tool: Mapping[str, object],
) -> str:
    payload = {
        field: pending_tool.get(field)
        for field in (
            "eventId",
            "toolName",
            "displayName",
            "risk",
            "summary",
            "detail",
            "draft",
        )
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _decision_identity(
    job_id: str,
    payload: Mapping[str, object],
) -> tuple[str, str] | None:
    identity_fields = (
        "commandId",
        "expectedStatus",
        "expectedUpdatedAt",
        "attemptId",
        "approvalFingerprint",
    )
    identity_values = tuple(
        str(payload.get(field, "")).strip()
        if payload.get(field) is not None
        else None
        for field in identity_fields
    )
    if not any(value is not None for value in identity_values):
        return None
    if not all(identity_values):
        raise JobCommandContractError(
            "approval command requires identity, waiting snapshot, attempt, and event fingerprint"
        )
    command_id, expected_status, updated_at, attempt_id, approval_fp = (
        identity_values
    )
    event_id = str(payload.get("eventId", "")).strip()
    if not event_id:
        raise JobCommandContractError("approval command requires eventId")
    if len(str(command_id)) > 200:
        raise JobCommandContractError("commandId must be at most 200 characters")
    if expected_status != "waiting_approval":
        raise JobCommandContractError(
            "approval command expected status must be waiting_approval"
        )
    material = json.dumps(
        {
            "approvalFingerprint": approval_fp,
            "attemptId": attempt_id,
            "decision": str(payload.get("decision", "")),
            "eventId": event_id,
            "expectedStatus": expected_status,
            "expectedUpdatedAt": updated_at,
            "jobId": job_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return str(command_id), hashlib.sha256(material.encode()).hexdigest()


def _existing_approval_decision(
    jobs: Mapping[str, dict],
    command_id: str,
) -> tuple[dict, dict] | None:
    for job in jobs.values():
        decisions = job.get("approvalDecisions")
        if not isinstance(decisions, list):
            continue
        for decision in decisions:
            if (
                isinstance(decision, dict)
                and decision.get("commandId") == command_id
            ):
                return job, decision
    return None


def _approval_replay(
    jobs: Mapping[str, dict],
    identity: tuple[str, str] | None,
) -> LegacyJobApprovalClaim | None:
    if identity is None:
        return None
    command_id, fingerprint = identity
    existing = _existing_approval_decision(jobs, command_id)
    if existing is None:
        return None
    job, receipt = existing
    if receipt.get("fingerprint") != fingerprint:
        command = (
            JobCommand.APPROVE
            if receipt.get("decision") == "approved"
            else JobCommand.DENY
        )
        raise JobCommandCollisionError(command_id, command=command)
    return LegacyJobApprovalClaim(
        False,
        True,
        False,
        dict(job),
        str(receipt.get("id", "")) or None,
        "decision_replayed",
    )


def _validate_pending_approval(
    job: Mapping[str, object],
    payload: Mapping[str, object],
    identity: tuple[str, str] | None,
) -> tuple[dict, str]:
    pending_tool = job.get("pendingTool")
    if not isinstance(pending_tool, dict):
        raise JobCommandStaleSnapshotError("pending approval tool is missing")
    event_id = str(payload.get("eventId", "")).strip()
    if pending_tool.get("eventId") != event_id:
        raise JobCommandStaleSnapshotError("pending approval event is stale")
    actual_fingerprint = legacy_job_pending_tool_fingerprint(pending_tool)
    if identity is not None and (
        actual_fingerprint
        != str(payload.get("approvalFingerprint", "")).strip()
    ):
        raise JobApprovalFingerprintMismatchError(
            "pending Tool fingerprint no longer matches approval command"
        )
    return pending_tool, actual_fingerprint


def _append_approval_decision(
    job: MutableMapping[str, object],
    payload: Mapping[str, object],
    *,
    decided_at: str,
    actual_attempt_id: str,
    actual_fingerprint: str,
    identity: tuple[str, str] | None,
) -> LegacyJobApprovalClaim:
    command_id, fingerprint = identity or ("", "")
    decision = str(payload.get("decision", "")).strip()
    receipt_command_id = command_id or (
        f"legacy-approval-{_sha256(str(job.get('id', '')), actual_attempt_id, decided_at)[:24]}"
    )
    receipt_id = (
        f"job-approval-{_sha256(receipt_command_id, fingerprint, decision)[:24]}"
    )
    receipt = {
        "id": receipt_id,
        "commandId": receipt_command_id,
        "fingerprint": fingerprint or _sha256(
            str(job.get("id", "")), actual_fingerprint, decision, decided_at
        ),
        "decision": decision,
        "eventId": str(payload.get("eventId", "")).strip(),
        "approvalFingerprint": actual_fingerprint,
        "attemptId": actual_attempt_id,
        "expectedStatus": str(job.get("status", "")),
        "expectedUpdatedAt": str(job.get("updatedAt", "")),
        "decidedAt": decided_at,
    }
    decisions = job.setdefault("approvalDecisions", [])
    if not isinstance(decisions, list):
        decisions = []
        job["approvalDecisions"] = decisions
    decisions.append(receipt)
    job["activeApprovalDecisionId"] = receipt_id
    job["updatedAt"] = decided_at
    if decision == "denied":
        pending_tool = job.get("pendingTool")
        display_name = (
            str(pending_tool.get("displayName", "unknown"))
            if isinstance(pending_tool, dict)
            else "unknown"
        )
        job["status"] = "failed"
        job["result"] = ""
        job["error"] = f"tool {display_name} denied by user"
        job.pop("pendingTool", None)
    else:
        job["status"] = "running"
    return LegacyJobApprovalClaim(
        True, False, decision == "approved", dict(job), receipt_id
    )


def claim_legacy_job_approval(
    jobs: MutableMapping[str, dict],
    job_id: str,
    payload: Mapping[str, object],
    *,
    decided_at: str,
) -> LegacyJobApprovalClaim:
    decision = str(payload.get("decision", "")).strip()
    if decision not in {"approved", "denied"}:
        raise JobCommandContractError("decision must be approved or denied")
    if not str(payload.get("eventId", "")).strip():
        raise JobCommandContractError("eventId is required")
    identity = _decision_identity(job_id, payload)
    replay = _approval_replay(jobs, identity)
    if replay is not None:
        return replay
    job = jobs.get(job_id)
    if job is None:
        return LegacyJobApprovalClaim(False, False, False, None, reason="job_not_found")
    actual_attempt_id, _ = legacy_job_attempt_identity(job)
    if identity is not None and (
        job.get("status") != payload.get("expectedStatus")
        or job.get("updatedAt") != payload.get("expectedUpdatedAt")
        or actual_attempt_id != payload.get("attemptId")
    ):
        raise JobCommandStaleSnapshotError("job approval snapshot is stale")
    if job.get("status") != "waiting_approval":
        return LegacyJobApprovalClaim(
            False, False, False, dict(job), reason="job_not_waiting_approval"
        )
    _, actual_fingerprint = _validate_pending_approval(job, payload, identity)
    return _append_approval_decision(
        job,
        payload,
        decided_at=decided_at,
        actual_attempt_id=actual_attempt_id,
        actual_fingerprint=actual_fingerprint,
        identity=identity,
    )


def approval_decision_is_current(
    job: Mapping[str, object],
    receipt_id: str,
) -> bool:
    if job.get("activeApprovalDecisionId") != receipt_id:
        return False
    decisions = job.get("approvalDecisions")
    return isinstance(decisions, list) and any(
        isinstance(item, dict)
        and item.get("id") == receipt_id
        and item.get("decision") == "approved"
        for item in decisions
    )


def mark_approval_manual_uncertain(
    job: MutableMapping[str, object],
    *,
    decided_at: str,
    reason: str,
) -> None:
    job["status"] = "failed"
    job["result"] = ""
    job["error"] = reason
    job["failureKeyword"] = "job_approval_uncertain"
    job["approvalDisposition"] = "manual_uncertain"
    job.pop("pendingTool", None)
    job["updatedAt"] = decided_at


def restore_legacy_job_approval_metadata(
    raw: Mapping[str, object],
    job: MutableMapping[str, object],
) -> None:
    for field in ("activeApprovalDecisionId", "approvalDisposition"):
        value = str(raw.get(field, "")).strip()
        if value:
            job[field] = value
    decisions = raw.get("approvalDecisions")
    if isinstance(decisions, list):
        job["approvalDecisions"] = [
            dict(item) for item in decisions if isinstance(item, dict)
        ]
