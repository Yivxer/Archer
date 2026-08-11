from __future__ import annotations

import sqlite3

import pytest

from core.authority_migration import (
    AuthorityVerdict,
    list_authority_comparisons,
)
from core.run_contract import RunState, StopReason
from core.run_store import get_run, list_events
from core.task_plan_observation import (
    TaskPlanObservationConflict,
    TaskPlanObservationUnavailable,
    list_task_plan_observations,
    record_task_plan_observation,
)
from core.task_plan_shadow import project_task_plan_shadow
from memory.migrations import run_migrations

NOW = "2026-07-25T11:00:00+08:00"


def _shadow_run(db_path, trace_id: str = "trace-plan-1") -> str:
    projection = project_task_plan_shadow(
        db_path,
        trace_id=trace_id,
        plan_event={
            "id": "plan-1",
            "title": "观察旧计划状态",
            "status": "proposed",
            "steps": [
                {
                    "id": 1,
                    "action": "inspect_context",
                    "tool": "project_context",
                    "requiresApproval": False,
                }
            ],
        },
        now=NOW,
    )
    return projection.run_id


def test_accepted_observation_is_idempotent_and_never_claims_execution(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    run_id = _shadow_run(db_path)

    first, first_run = record_task_plan_observation(
        db_path,
        run_id=run_id,
        plan_id="plan-1",
        trace_id="trace-plan-1",
        legacy_status="accepted",
        observed_at="2026-07-25T11:01:00+08:00",
    )
    event_count = len(list_events(db_path, run_id))
    second, second_run = record_task_plan_observation(
        db_path,
        run_id=run_id,
        plan_id="plan-1",
        trace_id="trace-plan-1",
        legacy_status="accepted",
        observed_at="2026-07-25T11:02:00+08:00",
    )

    assert second == first
    assert first.handoff == "legacy_job_unmigrated"
    assert first.runtime_execution_claimed is False
    assert first_run.state is RunState.WAITING_USER
    assert second_run.state is RunState.WAITING_USER
    assert len(list_events(db_path, run_id)) == event_count
    assert len(list_task_plan_observations(db_path, run_id)) == 1
    comparisons = list_authority_comparisons(
        db_path,
        domain="task_plan",
        run_id=run_id,
    )
    assert [item.verdict for item in comparisons] == [
        AuthorityVerdict.ALIGNED,
        AuthorityVerdict.ALIGNED,
    ]


def test_observation_idempotency_collision_is_rejected(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    run_id = _shadow_run(db_path)
    record_task_plan_observation(
        db_path,
        run_id=run_id,
        plan_id="plan-1",
        trace_id="trace-plan-1",
        legacy_status="accepted",
        observed_at=NOW,
    )

    with pytest.raises(TaskPlanObservationConflict):
        record_task_plan_observation(
            db_path,
            run_id=run_id,
            plan_id="plan-1",
            trace_id="different-trace",
            legacy_status="accepted",
            observed_at=NOW,
        )


def test_conflicting_terminal_legacy_status_is_rejected(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    run_id = _shadow_run(db_path)
    record_task_plan_observation(
        db_path,
        run_id=run_id,
        plan_id="plan-1",
        trace_id="trace-plan-1",
        legacy_status="accepted",
        observed_at=NOW,
    )

    with pytest.raises(TaskPlanObservationConflict):
        record_task_plan_observation(
            db_path,
            run_id=run_id,
            plan_id="plan-1",
            trace_id="trace-plan-1",
            legacy_status="dismissed",
            observed_at=NOW,
        )


def test_dismissed_observation_closes_shadow_without_external_execution(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    run_id = _shadow_run(db_path)

    observation, run = record_task_plan_observation(
        db_path,
        run_id=run_id,
        plan_id="plan-1",
        trace_id="trace-plan-1",
        legacy_status="dismissed",
        observed_at="2026-07-25T11:01:00+08:00",
    )

    assert observation.handoff == "none"
    assert run.state is RunState.CANCELLED
    assert run.stop_reason is StopReason.USER_CANCELLED
    assert get_run(db_path, run_id) == run
    states = [
        event.payload.get("to")
        for event in list_events(db_path, run_id)
        if event.event_type.value == "run.state_changed"
    ]
    assert states[-2:] == ["cancelling", "cancelled"]
    comparisons = list_authority_comparisons(
        db_path,
        domain="task_plan",
        run_id=run_id,
    )
    assert comparisons[-1].verdict is AuthorityVerdict.ALIGNED


def test_observations_are_append_only_and_require_shadow_source(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    run_id = _shadow_run(db_path)
    record_task_plan_observation(
        db_path,
        run_id=run_id,
        plan_id="plan-1",
        trace_id="trace-plan-1",
        legacy_status="accepted",
        observed_at=NOW,
    )

    conn = sqlite3.connect(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE runtime_task_plan_observations SET handoff = 'none'"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM runtime_task_plan_observations")
    conn.close()

    with pytest.raises(TaskPlanObservationUnavailable):
        record_task_plan_observation(
            db_path,
            run_id="missing",
            plan_id="plan-1",
            trace_id="trace-plan-1",
            legacy_status="dismissed",
            observed_at=NOW,
        )
