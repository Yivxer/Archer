from __future__ import annotations

from core.authority_migration import (
    AuthorityVerdict,
    list_authority_comparisons,
)
from core.run_contract import RunState, StepState
from core.run_store import get_run, list_events
from core.step_store import list_steps_for_run
from core.task_plan_shadow import (
    project_task_plan_shadow,
    task_plan_shadow_run_id,
)
from memory.migrations import run_migrations

NOW = "2026-07-25T10:00:00+08:00"


def _plan(
    *,
    title: str = "整理材料并写入 Obsidian",
    status: str = "proposed",
) -> dict:
    return {
        "id": "plan-legacy-1",
        "title": title,
        "status": status,
        "detail": "旧计划仍是权威来源",
        "steps": [
            {
                "id": 1,
                "action": "read_source",
                "tool": "input_context",
                "requiresApproval": False,
            },
            {
                "id": 2,
                "action": "write_obsidian",
                "tool": "obsidian_write",
                "requiresApproval": True,
            },
        ],
    }


def test_proposed_plan_projects_to_waiting_user_run_and_ordered_steps(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)

    projection = project_task_plan_shadow(
        db_path,
        trace_id="trace-plan-1",
        plan_event=_plan(),
        now=NOW,
    )

    run = get_run(db_path, projection.run_id)
    steps = list_steps_for_run(db_path, projection.run_id)
    assert projection.status == "aligned"
    assert projection.created is True
    assert projection.differences == ()
    assert run is not None
    assert run.state is RunState.WAITING_USER
    assert run.source == "shadow.task_plan"
    assert [step.ordinal for step in steps] == [1, 2]
    assert [step.state for step in steps] == [StepState.PENDING, StepState.PENDING]
    assert steps[1].depends_on == (steps[0].id,)
    assert steps[1].requires_approval is True
    comparisons = list_authority_comparisons(
        db_path,
        domain="task_plan",
        run_id=projection.run_id,
    )
    assert len(comparisons) == 1
    assert comparisons[0].verdict is AuthorityVerdict.ALIGNED


def test_projection_is_idempotent_for_same_trace_and_plan(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)

    first = project_task_plan_shadow(
        db_path,
        trace_id="trace-plan-1",
        plan_event=_plan(),
        now=NOW,
    )
    event_count = len(list_events(db_path, first.run_id))
    second = project_task_plan_shadow(
        db_path,
        trace_id="trace-plan-1",
        plan_event=_plan(),
        now="2026-07-25T10:01:00+08:00",
    )

    assert second.run_id == first.run_id
    assert second.created is False
    assert second.status == "aligned"
    assert len(list_events(db_path, first.run_id)) == event_count
    assert len(list_steps_for_run(db_path, first.run_id)) == 2
    assert len(list_authority_comparisons(
        db_path,
        domain="task_plan",
        run_id=first.run_id,
    )) == 1


def test_existing_shadow_drift_is_reported_without_overwrite(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    run_id = task_plan_shadow_run_id("trace-plan-1")
    project_task_plan_shadow(
        db_path,
        trace_id="trace-plan-1",
        plan_event=_plan(),
        now=NOW,
    )

    projection = project_task_plan_shadow(
        db_path,
        trace_id="trace-plan-1",
        plan_event=_plan(title="被修改的旧计划"),
        now="2026-07-25T10:01:00+08:00",
    )

    run = get_run(db_path, run_id)
    assert projection.status == "drifted"
    assert [item.field for item in projection.differences] == ["run.objective"]
    assert run is not None
    assert run.objective == "整理材料并写入 Obsidian"
    comparisons = list_authority_comparisons(
        db_path,
        domain="task_plan",
        run_id=run_id,
    )
    assert comparisons[-1].verdict is AuthorityVerdict.DRIFTED


def test_non_proposed_status_is_observed_but_never_executed(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)

    projection = project_task_plan_shadow(
        db_path,
        trace_id="trace-plan-accepted",
        plan_event=_plan(status="accepted"),
        now=NOW,
    )

    assert projection.status == "unsupported"
    assert projection.shadow_state == "absent"
    assert get_run(db_path, projection.run_id) is None
