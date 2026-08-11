"""Command reachability and scoped migration mode for Background Jobs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from core.authority_migration import (
    AuthorityMigrationError,
    MigrationMode,
    resolve_migration_mode,
)
from core.job_execution_adapter import JobCommand

BACKGROUND_JOB_DOMAIN = "background_job"
VAULT_REFLECTION_REACHABLE_COMMANDS = frozenset({
    JobCommand.CREATE,
    JobCommand.START,
    JobCommand.RETRY,
    JobCommand.CANCEL,
})


@dataclass(frozen=True, slots=True)
class JobCommandReachability:
    job_kind: str
    command: JobCommand
    reachable: bool
    evidence: str

    def to_dict(self) -> dict[str, object]:
        return {
            "jobKind": self.job_kind,
            "command": self.command.value,
            "reachable": self.reachable,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class JobCommandEvidencePath:
    job_kind: str
    observable: bool
    evidence: str

    def to_dict(self) -> dict[str, object]:
        return {
            "jobKind": self.job_kind,
            "observable": self.observable,
            "evidence": self.evidence,
        }


def audit_job_command_reachability(
    job_kind: str,
    command: JobCommand,
) -> JobCommandReachability:
    normalized_kind = job_kind.strip().lower()
    if not normalized_kind:
        raise ValueError("Job kind must not be empty")
    if normalized_kind == "vault_reflection":
        reachable = command in VAULT_REFLECTION_REACHABLE_COMMANDS
        evidence = (
            "vault_reflection_worker_dispatches_command"
            if reachable
            else "vault_reflection_worker_has_no_pending_tool_approval_path"
        )
    else:
        reachable = True
        evidence = "generic_job_worker_uses_tool_capable_chat_path"
    return JobCommandReachability(
        job_kind=normalized_kind,
        command=command,
        reachable=reachable,
        evidence=evidence,
    )


def audit_job_command_evidence_path(job_kind: str) -> JobCommandEvidencePath:
    """Audit whether the current product path can emit bound shadow evidence.

    Command reachability is deliberately separate: the legacy worker may support
    a command even when no current Desktop flow creates that Job kind with a
    Runtime shadow Run binding.
    """
    normalized_kind = job_kind.strip().lower()
    if not normalized_kind:
        raise ValueError("Job kind must not be empty")
    if normalized_kind == "vault_reflection":
        return JobCommandEvidencePath(
            job_kind=normalized_kind,
            observable=True,
            evidence=(
                "desktop_explicit_vault_reflection_plan_uses_accepted_task_plan_"
                "runtime_shadow_binding"
            ),
        )
    return JobCommandEvidencePath(
        job_kind=normalized_kind,
        observable=True,
        evidence="desktop_task_plan_background_job_supports_runtime_shadow_binding",
    )


def resolve_job_command_migration_mode(
    config: Mapping[str, object],
    job_kind: str,
    command: JobCommand,
) -> MigrationMode:
    normalized_kind = job_kind.strip().lower()
    if not normalized_kind:
        raise AuthorityMigrationError("Job kind must not be empty")
    domain_mode = resolve_migration_mode(config, BACKGROUND_JOB_DOMAIN)
    if domain_mode is MigrationMode.SHADOW:
        return MigrationMode.SHADOW
    runtime = config.get("runtime")
    command_modes = (
        runtime.get("command_migration_modes")
        if isinstance(runtime, dict)
        else None
    )
    background_job = (
        command_modes.get(BACKGROUND_JOB_DOMAIN)
        if isinstance(command_modes, dict)
        else None
    )
    kind_modes = (
        background_job.get(normalized_kind)
        if isinstance(background_job, dict)
        else None
    )
    raw_mode = (
        kind_modes.get(command.value)
        if isinstance(kind_modes, dict)
        else None
    )
    if raw_mode is None:
        return MigrationMode.SHADOW
    try:
        return MigrationMode(str(raw_mode).strip())
    except ValueError as exc:
        raise AuthorityMigrationError(
            "unsupported command migration mode for "
            f"{normalized_kind}.{command.value}: {raw_mode}"
        ) from exc
