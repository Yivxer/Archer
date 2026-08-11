"""Read-only shadow projection from legacy TaskPlan events into Runtime records.

The legacy Desktop plan event remains authoritative. This adapter only mirrors
the initial ``proposed`` snapshot so Runtime consistency can be measured before
any read or execution path is migrated.
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from core.authority_migration import (
    AuthorityVerdict,
    MigrationMode,
    authority_comparison_schema_available,
    build_authority_comparison,
    record_authority_comparison,
)
from core.run_contract import RunRecord, RunState, StepRecord
from core.run_store import create_run, get_run, transition_run
from core.step_store import create_step, get_step, list_steps_for_run

TASK_PLAN_SHADOW_SOURCE = "shadow.task_plan"
TASK_PLAN_SHADOW_KIND = "legacy_task_plan"


@dataclass(frozen=True, slots=True)
class TaskPlanShadowDifference:
    field: str
    expected: object
    actual: object

    def to_dict(self) -> dict[str, object]:
        return {
            "field": self.field,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass(frozen=True, slots=True)
class TaskPlanShadowProjection:
    plan_id: str
    trace_id: str
    run_id: str
    legacy_status: str
    shadow_state: str
    status: Literal["aligned", "drifted", "unsupported"]
    created: bool
    differences: tuple[TaskPlanShadowDifference, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "adapter": TASK_PLAN_SHADOW_SOURCE,
            "planId": self.plan_id,
            "traceId": self.trace_id,
            "runId": self.run_id,
            "legacyStatus": self.legacy_status,
            "shadowState": self.shadow_state,
            "status": self.status,
            "created": self.created,
            "differences": [item.to_dict() for item in self.differences],
        }


def _legacy_plan_snapshot(plan_event: dict[str, Any]) -> dict[str, object]:
    return {
        "id": str(plan_event.get("id", "")),
        "status": str(plan_event.get("status", "")),
        "title": str(plan_event.get("title", "")),
        "execution": plan_event.get("execution"),
        "steps": [
            {
                "id": item.get("id"),
                "action": item.get("action"),
                "tool": item.get("tool"),
                "requiresApproval": item.get("requiresApproval"),
            }
            for item in plan_event.get("steps", ())
            if isinstance(item, dict)
        ],
    }


def _runtime_plan_snapshot(
    run: RunRecord,
    steps: list[StepRecord],
) -> dict[str, object]:
    return {
        "id": run.id,
        "objective": run.objective,
        "source": run.source,
        "state": run.state.value,
        "steps": [
            {
                "id": step.id,
                "ordinal": step.ordinal,
                "title": step.title,
                "kind": step.kind,
                "state": step.state.value,
                "dependsOn": list(step.depends_on),
                "capability": step.capability,
                "requiresApproval": step.requires_approval,
            }
            for step in steps
        ],
    }


def task_plan_shadow_run_id(trace_id: str) -> str:
    digest = hashlib.sha256(trace_id.encode("utf-8")).hexdigest()[:24]
    return f"run-task-plan-{digest}"


def _step_id(run_id: str, ordinal: int) -> str:
    return f"{run_id}-step-{ordinal}"


def _expected_steps(run_id: str, plan_event: dict[str, Any]) -> list[StepRecord]:
    records: list[StepRecord] = []
    prior_step_id: str | None = None
    for ordinal, raw in enumerate(plan_event.get("steps", ()), start=1):
        legacy_step_id = int(raw.get("id", ordinal))
        step_id = _step_id(run_id, legacy_step_id)
        records.append(
            StepRecord(
                id=step_id,
                run_id=run_id,
                ordinal=ordinal,
                title=str(raw.get("action", "")).strip(),
                kind=TASK_PLAN_SHADOW_KIND,
                depends_on=(prior_step_id,) if prior_step_id else (),
                capability=str(raw.get("tool", "")).strip() or None,
                requires_approval=bool(raw.get("requiresApproval")),
            )
        )
        prior_step_id = step_id
    return records


def _difference(
    differences: list[TaskPlanShadowDifference],
    field: str,
    expected: object,
    actual: object,
) -> None:
    if expected != actual:
        differences.append(TaskPlanShadowDifference(field, expected, actual))


def _compare(
    expected_run: RunRecord,
    actual_run: RunRecord,
    expected_steps: list[StepRecord],
    actual_steps: list[StepRecord],
) -> tuple[TaskPlanShadowDifference, ...]:
    differences: list[TaskPlanShadowDifference] = []
    _difference(differences, "run.objective", expected_run.objective, actual_run.objective)
    _difference(differences, "run.source", expected_run.source, actual_run.source)
    _difference(
        differences,
        "run.state",
        RunState.WAITING_USER.value,
        actual_run.state.value,
    )
    _difference(differences, "steps.count", len(expected_steps), len(actual_steps))
    actual_by_ordinal = {step.ordinal: step for step in actual_steps}
    for expected in expected_steps:
        actual = actual_by_ordinal.get(expected.ordinal)
        prefix = f"steps[{expected.ordinal}]"
        if actual is None:
            differences.append(
                TaskPlanShadowDifference(prefix, expected.to_dict(), None)
            )
            continue
        for name in (
            "id",
            "title",
            "kind",
            "depends_on",
            "capability",
            "requires_approval",
            "state",
        ):
            expected_value = getattr(expected, name)
            actual_value = getattr(actual, name)
            if hasattr(expected_value, "value"):
                expected_value = expected_value.value
            if hasattr(actual_value, "value"):
                actual_value = actual_value.value
            _difference(
                differences,
                f"{prefix}.{name}",
                expected_value,
                actual_value,
            )
    return tuple(differences)


def _create_run_if_missing(
    db_path: str | Path,
    expected: RunRecord,
    *,
    event_id: str,
) -> tuple[RunRecord, bool]:
    current = get_run(db_path, expected.id)
    if current is not None:
        return current, False
    try:
        create_run(db_path, expected, event_id=event_id)
        return expected, True
    except sqlite3.IntegrityError:
        current = get_run(db_path, expected.id)
        if current is None:
            raise
        return current, False


def _create_steps_if_missing(
    db_path: str | Path,
    expected_steps: list[StepRecord],
    *,
    created_at: str,
) -> None:
    for expected in expected_steps:
        if get_step(db_path, expected.id) is not None:
            continue
        try:
            create_step(
                db_path,
                expected,
                event_id=f"event-{expected.id}-created",
                created_at=created_at,
            )
        except sqlite3.IntegrityError:
            if get_step(db_path, expected.id) is None:
                raise


def _advance_to_waiting_user(
    db_path: str | Path,
    run: RunRecord,
    *,
    updated_at: str,
) -> RunRecord:
    path = {
        RunState.RECEIVED: RunState.UNDERSTANDING,
        RunState.UNDERSTANDING: RunState.PLANNING,
        RunState.PLANNING: RunState.WAITING_USER,
    }
    current = run
    while current.state in path:
        target = path[current.state]
        current = transition_run(
            db_path,
            current.id,
            target,
            expected_version=current.version,
            event_id=f"event-{current.id}-{target.value}",
            updated_at=updated_at,
        )
    return current


def project_task_plan_shadow(
    db_path: str | Path,
    *,
    trace_id: str,
    plan_event: dict[str, Any],
    now: str,
    migration_mode: MigrationMode = MigrationMode.SHADOW,
) -> TaskPlanShadowProjection:
    """Persist and compare the initial legacy plan without executing it."""
    plan_id = str(plan_event.get("id", "")).strip()
    legacy_status = str(plan_event.get("status", "")).strip()
    run_id = task_plan_shadow_run_id(trace_id)
    if legacy_status != "proposed":
        current = get_run(db_path, run_id)
        return TaskPlanShadowProjection(
            plan_id=plan_id,
            trace_id=trace_id,
            run_id=run_id,
            legacy_status=legacy_status,
            shadow_state=current.state.value if current else "absent",
            status="unsupported",
            created=False,
            differences=(
                TaskPlanShadowDifference(
                    "legacy.status",
                    "proposed",
                    legacy_status,
                ),
            ),
        )

    expected_run = RunRecord(
        id=run_id,
        objective=str(plan_event.get("title", "")).strip(),
        source=TASK_PLAN_SHADOW_SOURCE,
        created_at=now,
        updated_at=now,
    )
    expected_steps = _expected_steps(run_id, plan_event)
    actual_run, created = _create_run_if_missing(
        db_path,
        expected_run,
        event_id=f"event-{run_id}-received",
    )
    base_matches = (
        actual_run.objective == expected_run.objective
        and actual_run.source == expected_run.source
    )
    if base_matches:
        _create_steps_if_missing(db_path, expected_steps, created_at=now)
        actual_steps = list_steps_for_run(db_path, run_id)
        step_differences = _compare(
            expected_run,
            actual_run,
            expected_steps,
            actual_steps,
        )
        non_state_differences = tuple(
            item for item in step_differences if item.field != "run.state"
        )
        if not non_state_differences:
            actual_run = _advance_to_waiting_user(
                db_path,
                actual_run,
                updated_at=now,
            )

    actual_run = get_run(db_path, run_id) or actual_run
    actual_steps = list_steps_for_run(db_path, run_id)
    differences = _compare(
        expected_run,
        actual_run,
        expected_steps,
        actual_steps,
    )
    projection = TaskPlanShadowProjection(
        plan_id=plan_id,
        trace_id=trace_id,
        run_id=run_id,
        legacy_status=legacy_status,
        shadow_state=actual_run.state.value,
        status="aligned" if not differences else "drifted",
        created=created,
        differences=differences,
    )
    receipt = build_authority_comparison(
        run_id=run_id,
        domain="task_plan",
        legacy_id=plan_id,
        mode=migration_mode,
        legacy_snapshot=_legacy_plan_snapshot(plan_event),
        runtime_snapshot=_runtime_plan_snapshot(actual_run, actual_steps),
        verdict=(
            AuthorityVerdict.ALIGNED
            if projection.status == "aligned"
            else AuthorityVerdict.DRIFTED
        ),
        reason=f"task_plan_proposed_{projection.status}",
        recorded_at=now,
    )
    if authority_comparison_schema_available(db_path):
        record_authority_comparison(db_path, receipt)
    return projection
