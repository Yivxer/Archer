"""Deterministic evidence audit for legacy Background Job authority."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from core.job_execution_adapter import (
    COMMAND_REQUIREMENTS,
    JOB_EXECUTION_ADAPTER_CONTRACT_VERSION,
    LEGACY_JOB_V0_ADAPTER_ID,
    LEGACY_JOB_V0_CAPABILITIES,
    JobAuthorityDecision,
    JobCommand,
    JobExecutionCapability,
    audit_legacy_job_v0,
)

JOB_CAPABILITY_AUDIT_CONTRACT_VERSION = 1


class EvidenceScope(StrEnum):
    GLOBAL = "global"
    JOB_KIND = "job_kind"


class EvidenceVerdict(StrEnum):
    PROVEN = "proven"
    PARTIAL = "partial"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class JobCapabilityEvidence:
    evidence_id: str
    capability: JobExecutionCapability
    commands: tuple[JobCommand, ...]
    scope: EvidenceScope
    job_kinds: tuple[str, ...]
    implementation_symbols: tuple[str, ...]
    receipt_versions: tuple[str, ...]
    regression_tests: tuple[str, ...]
    verdict: EvidenceVerdict
    reason: str

    def applies_to(self, job_kind: str) -> bool:
        return self.scope is EvidenceScope.GLOBAL or job_kind in self.job_kinds

    def to_dict(self) -> dict[str, object]:
        return {
            "evidenceId": self.evidence_id,
            "capability": self.capability.value,
            "commands": [command.value for command in self.commands],
            "scope": self.scope.value,
            "jobKinds": list(self.job_kinds),
            "implementationSymbols": list(self.implementation_symbols),
            "receiptVersions": list(self.receipt_versions),
            "regressionTests": list(self.regression_tests),
            "verdict": self.verdict.value,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class JobCapabilityAudit:
    adapter_id: str
    contract_version: int
    job_kind: str | None
    authority_enabled: bool
    evidence: tuple[JobCapabilityEvidence, ...]
    command_decisions: tuple[JobAuthorityDecision, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "adapterId": self.adapter_id,
            "contractVersion": self.contract_version,
            "jobKind": self.job_kind,
            "authorityEnabled": self.authority_enabled,
            "evidence": [item.to_dict() for item in self.evidence],
            "commands": [decision.to_dict() for decision in self.command_decisions],
        }


def _commands_for(
    capability: JobExecutionCapability,
) -> tuple[JobCommand, ...]:
    return tuple(
        command
        for command in JobCommand
        if capability in COMMAND_REQUIREMENTS[command]
    )


def _evidence(
    evidence_id: str,
    capability: JobExecutionCapability,
    *,
    scope: EvidenceScope = EvidenceScope.GLOBAL,
    job_kinds: tuple[str, ...] = ("*",),
    implementation_symbols: tuple[str, ...],
    receipt_versions: tuple[str, ...],
    regression_tests: tuple[str, ...],
    verdict: EvidenceVerdict,
    reason: str,
) -> JobCapabilityEvidence:
    return JobCapabilityEvidence(
        evidence_id=evidence_id,
        capability=capability,
        commands=_commands_for(capability),
        scope=scope,
        job_kinds=job_kinds,
        implementation_symbols=implementation_symbols,
        receipt_versions=receipt_versions,
        regression_tests=regression_tests,
        verdict=verdict,
        reason=reason,
    )


JOB_CAPABILITY_EVIDENCE: tuple[JobCapabilityEvidence, ...] = (
    _evidence(
        "legacy-job-capability-stable-command-id-v1",
        JobExecutionCapability.STABLE_COMMAND_ID,
        implementation_symbols=("core.job_execution_adapter.job_command_id",),
        receipt_versions=("job-command-envelope.v1",),
        regression_tests=("tests.test_job_execution_adapter.test_command_id_is_stable_per_run_step_command_and_attempt",),
        verdict=EvidenceVerdict.PROVEN,
        reason="command identity is deterministic, but v0 does not require the envelope",
    ),
    _evidence(
        "legacy-job-capability-create-idempotency-v1",
        JobExecutionCapability.CREATE_IDEMPOTENCY,
        implementation_symbols=("terminal.api.job_routes._create_job",),
        receipt_versions=("legacy-job-create-command.v1",),
        regression_tests=("tests.test_job_command_identity.test_create_command_replay_reuses_job_without_duplicate_start",),
        verdict=EvidenceVerdict.PROVEN,
        reason="stable create commands replay the original Job and reject collisions",
    ),
    _evidence(
        "legacy-job-capability-start-cas-v1",
        JobExecutionCapability.START_COMPARE_AND_SET,
        implementation_symbols=("core.job_execution_adapter.claim_legacy_job_start",),
        receipt_versions=("legacy-job-start-claim.v1",),
        regression_tests=("tests.test_job_start_claim.test_concurrent_start_claims_launch_only_one_worker",),
        verdict=EvidenceVerdict.PROVEN,
        reason="start claim validates and mutates the queued snapshot under one lock",
    ),
    _evidence(
        "legacy-job-capability-attempt-identity-v1",
        JobExecutionCapability.ATTEMPT_IDENTITY,
        implementation_symbols=("core.job_execution_adapter.legacy_job_attempt_identity",),
        receipt_versions=("legacy-job-attempt.v1",),
        regression_tests=("tests.test_job_retry_attempt.test_retry_claim_is_persistable_and_replay_is_idempotent",),
        verdict=EvidenceVerdict.PROVEN,
        reason="retry and terminal evidence bind to a stable attempt identity",
    ),
    _evidence(
        "legacy-job-capability-cooperative-cancellation-v1",
        JobExecutionCapability.COOPERATIVE_CANCELLATION,
        implementation_symbols=("core.job_cancellation.claim_legacy_job_cancellation",),
        receipt_versions=("legacy-job-cancellation-request.v1", "legacy-job-cancellation-ack.v1"),
        regression_tests=("tests.test_job_cancellation_identity.test_running_cancel_stays_pending_until_worker_acknowledges",),
        verdict=EvidenceVerdict.PARTIAL,
        reason="boundaries suppress late results, but arbitrary in-flight tools cannot all be stopped",
    ),
    _evidence(
        "legacy-job-capability-approval-fingerprint-v1",
        JobExecutionCapability.APPROVAL_FINGERPRINT,
        implementation_symbols=("core.job_approval.claim_legacy_job_approval",),
        receipt_versions=("legacy-job-approval-decision.v1",),
        regression_tests=("tests.test_job_approval_identity.test_concurrent_approval_requests_execute_tool_once",),
        verdict=EvidenceVerdict.PROVEN,
        reason="approval identity binds event, attempt, snapshot, and pending Tool fingerprint",
    ),
    _evidence(
        "legacy-job-capability-cancellation-safe-finalize-v1",
        JobExecutionCapability.CANCELLATION_SAFE_FINALIZE,
        implementation_symbols=("core.job_terminal_finalize.assert_legacy_job_finalize_snapshot",),
        receipt_versions=("legacy-job-terminal-finalization.v1",),
        regression_tests=("tests.test_job_terminal_finalize.test_late_worker_cannot_finalize_a_new_attempt",),
        verdict=EvidenceVerdict.PROVEN,
        reason="terminal writes recheck attempt, snapshot, cancellation, and verification evidence",
    ),
    _evidence(
        "legacy-job-capability-restart-reconciliation-v1",
        JobExecutionCapability.RESTART_RECONCILIATION,
        implementation_symbols=("core.job_execution_adapter.reconcile_legacy_job_restart",),
        receipt_versions=("legacy-job-restart-reconciliation.v1",),
        regression_tests=("tests.test_job_restart_reconciliation.test_restart_reconciliation_is_idempotent_across_reloads",),
        verdict=EvidenceVerdict.PROVEN,
        reason="restart reconciliation is persistent, deterministic, and fail closed",
    ),
    _evidence(
        "legacy-job-capability-result-verification-v1",
        JobExecutionCapability.RESULT_VERIFICATION,
        implementation_symbols=("core.job_result_evidence.verify_persisted_job_result",),
        receipt_versions=("legacy-job-result-artifact.v1", "legacy-job-result-verification.v1"),
        regression_tests=("tests.test_job_result_evidence.test_repeated_verification_reuses_stable_receipt",),
        verdict=EvidenceVerdict.PROVEN,
        reason="the verifier rereads persisted result evidence and checks its fingerprint",
    ),
    _evidence(
        "legacy-job-capability-outcome-vault-reflection-v1",
        JobExecutionCapability.OUTCOME_VERIFICATION,
        scope=EvidenceScope.JOB_KIND,
        job_kinds=("vault_reflection",),
        implementation_symbols=("core.job_outcome_verification.verify_legacy_job_outcome",),
        receipt_versions=("legacy_job.vault_reflection.record.v1",),
        regression_tests=("tests.test_job_outcome_verification.test_single_vault_reflection_matches_independent_record",),
        verdict=EvidenceVerdict.PROVEN,
        reason="reflection results are checked against independently persisted vault records",
    ),
    _evidence(
        "legacy-job-capability-outcome-analysis-v1",
        JobExecutionCapability.OUTCOME_VERIFICATION,
        scope=EvidenceScope.JOB_KIND,
        job_kinds=("analysis", "chat", "review"),
        implementation_symbols=("core.job_outcome_verification.verify_legacy_job_outcome",),
        receipt_versions=("legacy-job-outcome.v1",),
        regression_tests=("tests.test_job_outcome_verification.test_generic_job_defaults_to_uncertain_without_string_heuristics",),
        verdict=EvidenceVerdict.MISSING,
        reason="generated text has no independent business outcome verifier or user confirmation receipt",
    ),
)


def audit_legacy_job_capabilities(
    job_kind: str | None = None,
) -> JobCapabilityAudit:
    normalized_kind = str(job_kind or "").strip() or None
    evidence = tuple(
        item
        for item in JOB_CAPABILITY_EVIDENCE
        if normalized_kind is None or item.applies_to(normalized_kind)
    )
    return JobCapabilityAudit(
        adapter_id=LEGACY_JOB_V0_ADAPTER_ID,
        contract_version=JOB_CAPABILITY_AUDIT_CONTRACT_VERSION,
        job_kind=normalized_kind,
        authority_enabled=bool(LEGACY_JOB_V0_CAPABILITIES),
        evidence=evidence,
        command_decisions=audit_legacy_job_v0(),
    )


assert JOB_EXECUTION_ADAPTER_CONTRACT_VERSION == 1
