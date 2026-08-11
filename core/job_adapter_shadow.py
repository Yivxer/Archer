"""Non-executing Job Adapter v1 shadow authority audit."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from core.authority_migration import (
    AuthorityComparisonReceipt,
    AuthorityVerdict,
    MigrationMode,
    build_authority_comparison,
    record_authority_comparison,
)
from core.job_capability_audit import (
    EvidenceVerdict,
    audit_legacy_job_capabilities,
)
from core.job_execution_adapter import (
    JobAuthorityDecision,
    JobCommand,
    JobExecutionCapability,
    evaluate_job_authority,
    project_authoritative_job_state,
)

LEGACY_JOB_V1_SHADOW_ADAPTER_ID = "legacy.background_job.v1.shadow"
GENERIC_USER_CONFIRMED_JOB_KINDS = frozenset({"analysis", "chat", "review"})


@dataclass(frozen=True, slots=True)
class JobAdapterShadowAudit:
    adapter_id: str
    job_kind: str
    authority_enabled: bool
    candidate_capabilities: tuple[JobExecutionCapability, ...]
    command_decisions: tuple[JobAuthorityDecision, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "adapterId": self.adapter_id,
            "jobKind": self.job_kind,
            "authorityEnabled": self.authority_enabled,
            "candidateCapabilities": [
                item.value for item in self.candidate_capabilities
            ],
            "commands": [item.to_dict() for item in self.command_decisions],
        }


def candidate_capabilities_for(
    job_kind: str,
) -> tuple[JobExecutionCapability, ...]:
    audit = audit_legacy_job_capabilities(job_kind)
    capabilities = {
        item.capability
        for item in audit.evidence
        if item.verdict is EvidenceVerdict.PROVEN
    }
    return tuple(sorted(capabilities, key=lambda item: item.value))


def audit_job_adapter_v1_shadow(
    job_kind: str,
    *,
    runtime_artifact_ready: bool = False,
) -> JobAdapterShadowAudit:
    normalized_kind = str(job_kind).strip()
    if not normalized_kind:
        raise ValueError("Job kind must not be empty")
    capabilities = candidate_capabilities_for(normalized_kind)
    if (
        runtime_artifact_ready
        and normalized_kind in GENERIC_USER_CONFIRMED_JOB_KINDS
    ):
        capabilities = tuple(sorted(
            {*capabilities, JobExecutionCapability.OUTCOME_VERIFICATION},
            key=lambda item: item.value,
        ))
    decisions = tuple(
        evaluate_job_authority(
            LEGACY_JOB_V1_SHADOW_ADAPTER_ID,
            command,
            capabilities,
        )
        for command in JobCommand
    )
    return JobAdapterShadowAudit(
        adapter_id=LEGACY_JOB_V1_SHADOW_ADAPTER_ID,
        job_kind=normalized_kind,
        authority_enabled=False,
        candidate_capabilities=capabilities,
        command_decisions=decisions,
    )


def _verification_status(
    evidence: Mapping[str, object],
    field: str,
) -> bool | None:
    status = str(evidence.get(field, "")).strip()
    if status == "verified":
        return True
    if status == "failed":
        return False
    return None


def _runtime_projection(
    legacy_status: str,
    evidence: Mapping[str, object],
    *,
    awaiting_user_confirmation: bool = False,
) -> dict[str, object]:
    if awaiting_user_confirmation:
        return {
            "runState": "verifying",
            "stepState": "verifying",
            "terminal": False,
            "verificationRequired": True,
            "waitingFor": "user_confirmation",
        }
    projection = project_authoritative_job_state(
        legacy_status,
        result_verified=_verification_status(evidence, "verificationStatus"),
        outcome_verified=_verification_status(evidence, "outcomeStatus"),
    )
    return {
        "runState": projection.run_state.value,
        "stepState": projection.step_state.value,
        "terminal": projection.terminal,
        "verificationRequired": projection.verification_required,
    }


def record_job_adapter_shadow_audit(
    db_path: str | Path,
    *,
    run_id: str,
    legacy_job_id: str,
    job_kind: str,
    legacy_status: str,
    job_updated_at: str,
    evidence_summary: Mapping[str, object],
    recorded_at: str,
    runtime_artifact_ready: bool = False,
) -> tuple[JobAdapterShadowAudit, AuthorityComparisonReceipt]:
    audit = audit_job_adapter_v1_shadow(
        job_kind,
        runtime_artifact_ready=runtime_artifact_ready,
    )
    runtime_projection = _runtime_projection(
        legacy_status,
        evidence_summary,
        awaiting_user_confirmation=(
            runtime_artifact_ready
            and job_kind in GENERIC_USER_CONFIRMED_JOB_KINDS
        ),
    )
    receipt = build_authority_comparison(
        run_id=run_id,
        domain="background_job",
        legacy_id=legacy_job_id,
        mode=MigrationMode.SHADOW,
        legacy_snapshot={
            "jobId": legacy_job_id,
            "jobKind": job_kind,
            "status": legacy_status,
            "updatedAt": job_updated_at,
            "attemptId": evidence_summary.get("attemptId"),
            "verificationId": evidence_summary.get("verificationId"),
            "outcomeVerificationId": evidence_summary.get(
                "outcomeVerificationId"
            ),
        },
        runtime_snapshot={
            **runtime_projection,
            "adapterId": audit.adapter_id,
            "authorityEnabled": audit.authority_enabled,
            "candidateCapabilities": [
                item.value for item in audit.candidate_capabilities
            ],
            "commands": [item.to_dict() for item in audit.command_decisions],
        },
        verdict=AuthorityVerdict.ALIGNED,
        reason="legacy_job_shadow_projection_aligned",
        recorded_at=recorded_at,
    )
    return audit, record_authority_comparison(db_path, receipt)
