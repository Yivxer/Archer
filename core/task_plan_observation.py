"""Append-only lifecycle observations for the legacy TaskPlan authority."""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from core.authority_migration import (
    AuthorityVerdict,
    MigrationMode,
    authority_comparison_schema_available,
    build_authority_comparison,
    record_authority_comparison,
)
from core.run_contract import RunRecord, RunState, StopReason
from core.run_store import get_run, transition_run
from core.run_store_support import connect
from core.task_plan_shadow import TASK_PLAN_SHADOW_SOURCE

LegacyPlanLifecycleStatus = Literal["accepted", "dismissed"]


class TaskPlanObservationUnavailable(RuntimeError):
    """Raised when a lifecycle event does not target a valid shadow Run."""


class TaskPlanObservationConflict(RuntimeError):
    """Raised when an idempotency key is reused with different observation data."""


@dataclass(frozen=True, slots=True)
class TaskPlanLifecycleObservation:
    id: str
    run_id: str
    plan_id: str
    trace_id: str
    legacy_status: LegacyPlanLifecycleStatus
    handoff: str
    runtime_execution_claimed: bool
    observed_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            "trace_id": self.trace_id,
            "legacy_status": self.legacy_status,
            "handoff": self.handoff,
            "runtime_execution_claimed": self.runtime_execution_claimed,
            "observed_at": self.observed_at,
        }


def task_plan_observation_id(
    run_id: str,
    plan_id: str,
    legacy_status: LegacyPlanLifecycleStatus,
) -> str:
    material = f"{run_id}\0{plan_id}\0{legacy_status}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"task-plan-observation-{digest}"


def _row_to_observation(row: sqlite3.Row) -> TaskPlanLifecycleObservation:
    return TaskPlanLifecycleObservation(
        id=row["id"],
        run_id=row["run_id"],
        plan_id=row["plan_id"],
        trace_id=row["trace_id"],
        legacy_status=row["legacy_status"],
        handoff=row["handoff"],
        runtime_execution_claimed=bool(row["runtime_execution_claimed"]),
        observed_at=row["observed_at"],
    )


def list_task_plan_observations(
    db_path: str | Path,
    run_id: str,
) -> list[TaskPlanLifecycleObservation]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT * FROM runtime_task_plan_observations
            WHERE run_id = ?
            ORDER BY observed_at ASC, id ASC
            """,
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_observation(row) for row in rows]


def _require_shadow_run(db_path: str | Path, run_id: str) -> RunRecord:
    run = get_run(db_path, run_id)
    if run is None:
        raise TaskPlanObservationUnavailable(f"shadow run does not exist: {run_id}")
    if run.source != TASK_PLAN_SHADOW_SOURCE:
        raise TaskPlanObservationUnavailable(
            f"run is not a TaskPlan shadow: {run_id}"
        )
    return run


def _observation_handoff(status: LegacyPlanLifecycleStatus) -> str:
    if status == "accepted":
        return "legacy_job_unmigrated"
    return "none"


def _validate_lifecycle_sequence(
    db_path: str | Path,
    run: RunRecord,
    status: LegacyPlanLifecycleStatus,
) -> None:
    observations = list_task_plan_observations(db_path, run.id)
    conflicting = next(
        (item for item in observations if item.legacy_status != status),
        None,
    )
    if conflicting is not None:
        raise TaskPlanObservationConflict(
            f"legacy plan already observed as {conflicting.legacy_status}"
        )
    if status == "accepted" and run.state is not RunState.WAITING_USER:
        raise TaskPlanObservationUnavailable(
            f"accepted shadow must remain waiting_user, got {run.state.value}"
        )
    if status == "dismissed" and run.state not in {
        RunState.WAITING_USER,
        RunState.CANCELLING,
        RunState.CANCELLED,
    }:
        raise TaskPlanObservationUnavailable(
            f"dismissed shadow cannot close from {run.state.value}"
        )


def _observation_identity(
    observation: TaskPlanLifecycleObservation,
) -> tuple[object, ...]:
    return (
        observation.id,
        observation.run_id,
        observation.plan_id,
        observation.trace_id,
        observation.legacy_status,
        observation.handoff,
        observation.runtime_execution_claimed,
    )


def _existing_observation_or_conflict(
    db_path: str | Path,
    requested: TaskPlanLifecycleObservation,
) -> TaskPlanLifecycleObservation:
    existing = next(
        (
            item
            for item in list_task_plan_observations(db_path, requested.run_id)
            if item.legacy_status == requested.legacy_status
        ),
        None,
    )
    if existing is None:
        raise TaskPlanObservationConflict(
            f"observation insert failed for {requested.run_id}"
        )
    if _observation_identity(existing) != _observation_identity(requested):
        raise TaskPlanObservationConflict(
            f"observation collision for {requested.run_id}"
        )
    return existing


def _insert_observation(
    db_path: str | Path,
    observation: TaskPlanLifecycleObservation,
) -> TaskPlanLifecycleObservation:
    conn = connect(db_path)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO runtime_task_plan_observations(
                    id, run_id, plan_id, trace_id, legacy_status, handoff,
                    runtime_execution_claimed, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation.id,
                    observation.run_id,
                    observation.plan_id,
                    observation.trace_id,
                    observation.legacy_status,
                    observation.handoff,
                    int(observation.runtime_execution_claimed),
                    observation.observed_at,
                ),
            )
        return observation
    except sqlite3.IntegrityError:
        return _existing_observation_or_conflict(db_path, observation)
    finally:
        conn.close()


def _close_dismissed_shadow(
    db_path: str | Path,
    run: RunRecord,
    *,
    observed_at: str,
) -> RunRecord:
    current = run
    if current.state is RunState.WAITING_USER:
        current = transition_run(
            db_path,
            current.id,
            RunState.CANCELLING,
            expected_version=current.version,
            event_id=f"event-{current.id}-legacy-dismissed-cancelling",
            updated_at=observed_at,
        )
    if current.state is RunState.CANCELLING:
        current = transition_run(
            db_path,
            current.id,
            RunState.CANCELLED,
            expected_version=current.version,
            event_id=f"event-{current.id}-legacy-dismissed-cancelled",
            updated_at=observed_at,
            stop_reason=StopReason.USER_CANCELLED,
        )
    if current.state is not RunState.CANCELLED:
        raise TaskPlanObservationUnavailable(
            f"dismissed shadow cannot close from {current.state.value}"
        )
    return current


def record_task_plan_observation(
    db_path: str | Path,
    *,
    run_id: str,
    plan_id: str,
    trace_id: str,
    legacy_status: LegacyPlanLifecycleStatus,
    observed_at: str,
    migration_mode: MigrationMode = MigrationMode.SHADOW,
) -> tuple[TaskPlanLifecycleObservation, RunRecord]:
    if legacy_status not in {"accepted", "dismissed"}:
        raise TaskPlanObservationUnavailable(
            f"unsupported legacy plan status: {legacy_status}"
        )
    if not all((plan_id.strip(), trace_id.strip(), observed_at.strip())):
        raise TaskPlanObservationUnavailable("observation fields must not be empty")
    run = _require_shadow_run(db_path, run_id)
    _validate_lifecycle_sequence(db_path, run, legacy_status)
    observation = TaskPlanLifecycleObservation(
        id=task_plan_observation_id(run_id, plan_id, legacy_status),
        run_id=run_id,
        plan_id=plan_id,
        trace_id=trace_id,
        legacy_status=legacy_status,
        handoff=_observation_handoff(legacy_status),
        runtime_execution_claimed=False,
        observed_at=observed_at,
    )
    persisted = _insert_observation(db_path, observation)
    if legacy_status == "dismissed":
        run = _close_dismissed_shadow(
            db_path,
            _require_shadow_run(db_path, run_id),
            observed_at=observed_at,
        )
    expected_state = (
        RunState.WAITING_USER
        if legacy_status == "accepted"
        else RunState.CANCELLED
    )
    verdict = (
        AuthorityVerdict.ALIGNED
        if run.state is expected_state and not persisted.runtime_execution_claimed
        else AuthorityVerdict.DRIFTED
    )
    receipt = build_authority_comparison(
        run_id=run_id,
        domain="task_plan",
        legacy_id=plan_id,
        mode=migration_mode,
        legacy_snapshot={
            "planId": plan_id,
            "traceId": trace_id,
            "status": legacy_status,
        },
        runtime_snapshot={
            "runId": run.id,
            "state": run.state.value,
            "observationId": persisted.id,
            "observedStatus": persisted.legacy_status,
            "handoff": persisted.handoff,
            "runtimeExecutionClaimed": persisted.runtime_execution_claimed,
        },
        verdict=verdict,
        reason=(
            "task_plan_lifecycle_aligned"
            if verdict is AuthorityVerdict.ALIGNED
            else "task_plan_lifecycle_drifted"
        ),
        recorded_at=observed_at,
    )
    if authority_comparison_schema_available(db_path):
        record_authority_comparison(db_path, receipt)
    return persisted, run
