from __future__ import annotations

import pytest

from core.authority_migration import AuthorityMigrationError, MigrationMode
from core.job_command_authority import (
    audit_job_command_evidence_path,
    audit_job_command_reachability,
    resolve_job_command_migration_mode,
)
from core.job_execution_adapter import JobCommand


def _config(*, domain: str, command: str | None = None) -> dict[str, object]:
    runtime: dict[str, object] = {
        "migration_modes": {"background_job": domain},
    }
    if command is not None:
        runtime["command_migration_modes"] = {
            "background_job": {
                "vault_reflection": {"create": command},
            },
        }
    return {"runtime": runtime}


def test_vault_reflection_approval_commands_are_not_reachable() -> None:
    assert audit_job_command_reachability(
        "vault_reflection", JobCommand.CREATE
    ).reachable is True
    assert audit_job_command_reachability(
        "vault_reflection", JobCommand.CANCEL
    ).reachable is True
    for command in (JobCommand.APPROVE, JobCommand.DENY):
        audit = audit_job_command_reachability("vault_reflection", command)
        assert audit.reachable is False
        assert "no_pending_tool_approval_path" in audit.evidence


def test_vault_reflection_has_bound_product_evidence_path() -> None:
    audit = audit_job_command_evidence_path("vault_reflection")

    assert audit.observable is True
    assert "accepted_task_plan" in audit.evidence
    assert "runtime_shadow_binding" in audit.evidence


def test_task_plan_job_kind_has_bound_product_evidence_path() -> None:
    audit = audit_job_command_evidence_path("chat")

    assert audit.observable is True
    assert "task_plan" in audit.evidence


def test_domain_authoritative_does_not_bypass_explicit_command_scope() -> None:
    assert resolve_job_command_migration_mode(
        _config(domain="authoritative"),
        "vault_reflection",
        JobCommand.CREATE,
    ) is MigrationMode.SHADOW
    assert resolve_job_command_migration_mode(
        _config(domain="authoritative", command="authoritative"),
        "vault_reflection",
        JobCommand.CREATE,
    ) is MigrationMode.AUTHORITATIVE


def test_domain_shadow_dominates_command_authoritative() -> None:
    assert resolve_job_command_migration_mode(
        _config(domain="shadow", command="authoritative"),
        "vault_reflection",
        JobCommand.CREATE,
    ) is MigrationMode.SHADOW


def test_invalid_command_mode_fails_closed() -> None:
    with pytest.raises(AuthorityMigrationError):
        resolve_job_command_migration_mode(
            _config(domain="authoritative", command="live"),
            "vault_reflection",
            JobCommand.CREATE,
        )
