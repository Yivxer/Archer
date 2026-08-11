from __future__ import annotations

from importlib import import_module
from pathlib import Path

from core.job_capability_audit import (
    JOB_CAPABILITY_EVIDENCE,
    EvidenceScope,
    EvidenceVerdict,
    audit_legacy_job_capabilities,
)
from core.job_execution_adapter import JobCommand, JobExecutionCapability

ROOT = Path(__file__).resolve().parents[1]


def test_capability_matrix_is_deterministic_and_complete() -> None:
    first = audit_legacy_job_capabilities().to_dict()
    replay = audit_legacy_job_capabilities().to_dict()

    assert replay == first
    assert {
        item.capability for item in JOB_CAPABILITY_EVIDENCE
    } == set(JobExecutionCapability)
    assert all(item.commands for item in JOB_CAPABILITY_EVIDENCE)
    assert all(item.implementation_symbols for item in JOB_CAPABILITY_EVIDENCE)
    assert all(item.receipt_versions for item in JOB_CAPABILITY_EVIDENCE)
    assert all(item.regression_tests for item in JOB_CAPABILITY_EVIDENCE)


def test_audit_does_not_grant_legacy_job_v0_authority() -> None:
    audit = audit_legacy_job_capabilities("vault_reflection")

    assert audit.authority_enabled is False
    assert {decision.command for decision in audit.command_decisions} == set(JobCommand)
    assert all(decision.permitted is False for decision in audit.command_decisions)


def test_outcome_evidence_is_scoped_by_job_kind() -> None:
    vault = audit_legacy_job_capabilities("vault_reflection")
    analysis = audit_legacy_job_capabilities("analysis")
    vault_outcome = [
        item for item in vault.evidence
        if item.capability is JobExecutionCapability.OUTCOME_VERIFICATION
    ]
    analysis_outcome = [
        item for item in analysis.evidence
        if item.capability is JobExecutionCapability.OUTCOME_VERIFICATION
    ]

    assert len(vault_outcome) == len(analysis_outcome) == 1
    assert vault_outcome[0].scope is EvidenceScope.JOB_KIND
    assert vault_outcome[0].verdict is EvidenceVerdict.PROVEN
    assert analysis_outcome[0].verdict is EvidenceVerdict.MISSING


def test_partial_global_evidence_remains_visible_for_every_kind() -> None:
    audit = audit_legacy_job_capabilities("vault_reflection")
    cancellation = next(
        item for item in audit.evidence
        if item.capability is JobExecutionCapability.COOPERATIVE_CANCELLATION
    )

    assert cancellation.scope is EvidenceScope.GLOBAL
    assert cancellation.verdict is EvidenceVerdict.PARTIAL


def test_unknown_job_kind_has_no_outcome_evidence() -> None:
    audit = audit_legacy_job_capabilities("custom")

    assert all(
        item.capability is not JobExecutionCapability.OUTCOME_VERIFICATION
        for item in audit.evidence
    )


def test_matrix_references_real_implementation_and_regression_symbols() -> None:
    for item in JOB_CAPABILITY_EVIDENCE:
        for symbol in item.implementation_symbols:
            module_name, attribute = symbol.rsplit(".", 1)
            assert hasattr(import_module(module_name), attribute), symbol
        for test_symbol in item.regression_tests:
            module_name, function_name = test_symbol.rsplit(".", 1)
            test_path = ROOT / f"{module_name.replace('.', '/')}.py"
            assert test_path.is_file(), test_symbol
            assert f"def {function_name}(" in test_path.read_text(encoding="utf-8")
