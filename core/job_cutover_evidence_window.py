"""Read-only review gate for real Background Job shadow evidence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Mapping

from core.authority_migration import (
    AuthorityMigrationError,
    AuthorityVerdict,
    MigrationMode,
    resolve_migration_mode,
)
from core.job_command_authority import (
    audit_job_command_evidence_path,
    audit_job_command_reachability,
)
from core.job_cutover_observation import (
    JobCutoverObservation,
    list_job_cutover_observations,
)
from core.job_execution_adapter import JobCommand
from core.task_plan_job_shadow import list_task_plan_job_observations

EVIDENCE_WINDOW_CONTRACT_VERSION = 1
TARGET_JOB_KIND = "vault_reflection"
REVIEWED_COMMANDS = (
    JobCommand.CREATE,
    JobCommand.START,
    JobCommand.RETRY,
    JobCommand.APPROVE,
    JobCommand.DENY,
)
REQUIRED_COMMANDS = tuple(
    command for command in REVIEWED_COMMANDS
    if audit_job_command_reachability(TARGET_JOB_KIND, command).reachable
)
MINIMUM_CANDIDATES_PER_COMMAND = 3
MINIMUM_DISTINCT_RUNS_PER_COMMAND = 3


class EvidenceWindowStatus(StrEnum):
    NOT_STARTED = "not_started"
    COLLECTING = "collecting"
    BLOCKED = "blocked"
    REVIEWABLE = "reviewable"


class EvidenceWindowError(ValueError):
    """The requested evidence window boundary is invalid."""


@dataclass(frozen=True, slots=True)
class CommandEvidenceReview:
    command: JobCommand
    observable_in_current_workflow: bool
    candidate_count: int
    verified_candidate_count: int
    unverified_candidate_count: int
    forbidden_count: int
    conflict_count: int
    drift_count: int
    distinct_candidate_runs: int
    meets_threshold: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "command": self.command.value,
            "observableInCurrentWorkflow": self.observable_in_current_workflow,
            "candidateCount": self.candidate_count,
            "verifiedCandidateCount": self.verified_candidate_count,
            "unverifiedCandidateCount": self.unverified_candidate_count,
            "forbiddenCount": self.forbidden_count,
            "conflictCount": self.conflict_count,
            "driftCount": self.drift_count,
            "distinctCandidateRuns": self.distinct_candidate_runs,
            "meetsThreshold": self.meets_threshold,
        }


@dataclass(frozen=True, slots=True)
class JobCutoverEvidenceWindow:
    status: EvidenceWindowStatus
    migration_mode: str
    window_started_at: str | None
    route_receipt_count: int
    distinct_run_count: int
    command_reviews: tuple[CommandEvidenceReview, ...]
    blockers: tuple[str, ...]
    collection_path_ready: bool
    collection_path_evidence: str
    authority_enabled: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "contractVersion": EVIDENCE_WINDOW_CONTRACT_VERSION,
            "status": self.status.value,
            "migrationMode": self.migration_mode,
            "windowStartedAt": self.window_started_at,
            "routeReceiptCount": self.route_receipt_count,
            "distinctRunCount": self.distinct_run_count,
            "targetJobKind": TARGET_JOB_KIND,
            "reviewedCommands": [item.value for item in REVIEWED_COMMANDS],
            "requiredCommands": [item.value for item in REQUIRED_COMMANDS],
            "excludedUnobservableCommands": [
                item.value for item in REVIEWED_COMMANDS
                if item not in REQUIRED_COMMANDS
            ],
            "minimumCandidatesPerCommand": MINIMUM_CANDIDATES_PER_COMMAND,
            "minimumDistinctRunsPerCommand": MINIMUM_DISTINCT_RUNS_PER_COMMAND,
            "candidateRequiresVerifiedTerminalOutcome": True,
            "collectionPathReady": self.collection_path_ready,
            "collectionPathEvidence": self.collection_path_evidence,
            "commandReviews": [item.to_dict() for item in self.command_reviews],
            "blockers": list(self.blockers),
            "syntheticEvidenceAccepted": False,
            "authorityEnabled": self.authority_enabled,
        }


def _instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise EvidenceWindowError(f"invalid evidence window timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise EvidenceWindowError("evidence window timestamp must include timezone")
    return parsed.astimezone(UTC)


def _review_command(
    observations: list[JobCutoverObservation],
    command: JobCommand,
    verified_outcome_runs: set[str],
) -> CommandEvidenceReview:
    matching = [item for item in observations if item.command is command]
    candidates = [item for item in matching if item.status == "candidate"]
    verified_candidates = [
        item for item in candidates if item.run_id in verified_outcome_runs
    ]
    forbidden_count = sum(item.status == "forbidden" for item in matching)
    conflict_count = sum(item.status == "conflict" for item in matching)
    drift_count = sum(
        item.verdict is AuthorityVerdict.DRIFTED for item in matching
    )
    distinct_runs = len({item.run_id for item in verified_candidates})
    meets_threshold = (
        len(verified_candidates) >= MINIMUM_CANDIDATES_PER_COMMAND
        and distinct_runs >= MINIMUM_DISTINCT_RUNS_PER_COMMAND
        and forbidden_count == 0
        and conflict_count == 0
        and drift_count == 0
    )
    return CommandEvidenceReview(
        command=command,
        observable_in_current_workflow=audit_job_command_reachability(
            TARGET_JOB_KIND,
            command,
        ).reachable,
        candidate_count=len(candidates),
        verified_candidate_count=len(verified_candidates),
        unverified_candidate_count=len(candidates) - len(verified_candidates),
        forbidden_count=forbidden_count,
        conflict_count=conflict_count,
        drift_count=drift_count,
        distinct_candidate_runs=distinct_runs,
        meets_threshold=meets_threshold,
    )


def _outcome_run_statuses(
    db_path: str | Path,
    observations: list[JobCutoverObservation],
) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for run_id in {item.run_id for item in observations}:
        snapshots = list_task_plan_job_observations(db_path, run_id)
        latest = max(
            snapshots,
            key=lambda item: (
                item.job_updated_at,
                item.observed_at,
                item.id,
            ),
            default=None,
        )
        if latest is None or latest.legacy_status in {
            "queued",
            "running",
            "waiting_approval",
        }:
            statuses[run_id] = "pending"
            continue
        evidence = latest.evidence_summary
        if (
            latest.legacy_status == "complete"
            and evidence.get("verificationStatus") == "verified"
            and evidence.get("outcomeStatus") == "verified"
        ):
            statuses[run_id] = "verified"
        else:
            statuses[run_id] = "terminal_unverified"
    return statuses


def _guard_blockers(observations: list[JobCutoverObservation]) -> list[str]:
    blockers: list[str] = []
    for observation in observations:
        if observation.command is JobCommand.CANCEL and observation.status != "forbidden":
            blockers.append("cancel_not_fail_closed")
        if (
            observation.job_kind != TARGET_JOB_KIND
            and observation.status in {"candidate", "authoritative"}
        ):
            blockers.append(
                f"generic_candidate:{observation.job_kind}:{observation.command.value}"
            )
        if observation.status == "authoritative":
            blockers.append("authoritative_receipt_inside_shadow_window")
    return blockers


def review_job_cutover_evidence_window(
    db_path: str | Path,
    config: Mapping[str, object],
    *,
    started_at: str | None = None,
) -> JobCutoverEvidenceWindow:
    try:
        mode = resolve_migration_mode(config, "background_job")
        mode_value = mode.value
    except AuthorityMigrationError:
        mode = None
        mode_value = "invalid"

    boundary = _instant(started_at) if started_at else None
    observations: list[JobCutoverObservation] = []
    invalid_timestamps: list[str] = []
    for observation in list_job_cutover_observations(db_path):
        try:
            recorded_at = _instant(observation.recorded_at)
        except EvidenceWindowError:
            invalid_timestamps.append(observation.receipt_id)
            continue
        if boundary is None or recorded_at >= boundary:
            observations.append(observation)

    target = [
        item for item in observations if item.job_kind == TARGET_JOB_KIND
    ]
    configured_path = audit_job_command_evidence_path(TARGET_JOB_KIND)
    collection_path_ready = configured_path.observable or bool(target)
    collection_path_evidence = (
        "bound_vault_reflection_shadow_observation_present"
        if target
        else configured_path.evidence
    )
    outcome_statuses = _outcome_run_statuses(db_path, target)
    verified_outcome_runs = {
        run_id for run_id, status in outcome_statuses.items()
        if status == "verified"
    }
    reviews = tuple(
        _review_command(target, command, verified_outcome_runs)
        for command in REVIEWED_COMMANDS
    )
    blockers = _guard_blockers(observations)
    blockers.extend(
        f"invalid_observation_timestamp:{receipt_id}"
        for receipt_id in invalid_timestamps
    )
    if mode is not MigrationMode.SHADOW:
        blockers.append("background_job_migration_mode_not_shadow")
    if not collection_path_ready:
        blockers.append("vault_reflection_shadow_collection_path_unavailable")
    blockers.extend(
        f"candidate_run_terminal_unverified:{run_id}"
        for run_id, status in outcome_statuses.items()
        if status == "terminal_unverified"
    )
    for review in reviews:
        if review.forbidden_count:
            blockers.append(f"forbidden:{review.command.value}")
        if review.conflict_count:
            blockers.append(f"conflict:{review.command.value}")
        if review.drift_count:
            blockers.append(f"drift:{review.command.value}")

    if blockers:
        status = EvidenceWindowStatus.BLOCKED
    elif not observations:
        status = EvidenceWindowStatus.NOT_STARTED
    elif all(
        review.meets_threshold
        for review in reviews
        if review.observable_in_current_workflow
    ):
        status = EvidenceWindowStatus.REVIEWABLE
    else:
        status = EvidenceWindowStatus.COLLECTING

    effective_start = started_at
    if effective_start is None and observations:
        effective_start = min(item.recorded_at for item in observations)
    return JobCutoverEvidenceWindow(
        status=status,
        migration_mode=mode_value,
        window_started_at=effective_start,
        route_receipt_count=len(observations),
        distinct_run_count=len({item.run_id for item in observations}),
        command_reviews=reviews,
        blockers=tuple(sorted(set(blockers))),
        collection_path_ready=collection_path_ready,
        collection_path_evidence=collection_path_evidence,
    )
