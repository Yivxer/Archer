from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from core.outcome_store import record_artifact, record_verification
from core.run_contract import (
    ArtifactRecord,
    InvalidRunTransition,
    InvalidStepTransition,
    RunBudget,
    RunEventRecord,
    RunEventType,
    RunRecord,
    RunState,
    StepRecord,
    StepState,
    StopReason,
    VerificationReceipt,
    VerificationStatus,
)
from core.run_store import (
    InvalidInitialRun,
    InvalidInitialStep,
    RunLedgerCorrupted,
    RunNotFound,
    RunSnapshotMismatch,
    RunVersionConflict,
    StepAttemptLimitExceeded,
    StepNotFound,
    StepStateConflict,
    append_event,
    create_run,
    create_step,
    get_run,
    get_step,
    list_events,
    rebuild_run_snapshot,
    rebuild_step_snapshot,
    scan_non_terminal_runs,
    transition_run,
    transition_step,
)
from memory.migrations import LATEST_SCHEMA_VERSION, MIGRATIONS, run_migrations


def _record() -> RunRecord:
    return RunRecord(
        id="run-1",
        objective="完成 Runtime Closure",
        source="chat",
        session_id="session-1",
        thread_id="thread-1",
        created_at="2026-07-23T10:00:00+08:00",
        updated_at="2026-07-23T10:00:00+08:00",
        budget=RunBudget(max_steps=5, token_budget=20_000),
    )


def _step() -> StepRecord:
    return StepRecord(
        id="step-1",
        run_id="run-1",
        ordinal=1,
        title="建立原子状态迁移",
        kind="implementation",
        depends_on=("step-0",),
        capability="runtime_store",
        requires_approval=False,
        success_criteria=("snapshot_updated", "event_appended"),
    )


@pytest.mark.integration
def test_runtime_migration_creates_run_store_tables(tmp_path) -> None:
    db_path = tmp_path / "archer.db"

    result = run_migrations(db_path)

    assert result.version == LATEST_SCHEMA_VERSION
    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        conn.close()
    assert {
        "runtime_runs",
        "runtime_steps",
        "runtime_events",
        "runtime_artifacts",
        "runtime_verifications",
        "runtime_checkpoints",
        "runtime_task_plan_observations",
        "runtime_task_plan_job_bindings",
        "runtime_task_plan_job_observations",
    } <= tables


@pytest.mark.integration
def test_existing_v4_database_upgrades_without_losing_data(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path, migrations=MIGRATIONS[:4])
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
    conn.execute("INSERT INTO sentinel VALUES ('keep-me')")
    conn.commit()
    conn.close()

    result = run_migrations(db_path)

    assert result.applied == list(range(5, LATEST_SCHEMA_VERSION + 1))
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT value FROM sentinel").fetchone()[0] == "keep-me"
    finally:
        conn.close()


@pytest.mark.integration
def test_existing_v5_runtime_upgrades_to_checkpoint_schema(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path, migrations=MIGRATIONS[:5])
    record = _record()
    create_run(db_path, record, event_id="event-v5-run")

    result = run_migrations(db_path)

    assert result.applied == list(range(6, LATEST_SCHEMA_VERSION + 1))
    assert get_run(db_path, record.id) == record
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute(
            "SELECT count(*) FROM sqlite_master "
            "WHERE type = 'table' AND name = 'runtime_checkpoints'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT count(*) FROM sqlite_master "
            "WHERE type = 'table' AND name = 'runtime_task_plan_observations'"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_create_and_get_run_round_trip_with_initial_event(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    record = _record()

    event = create_run(db_path, record, event_id="event-1")

    assert get_run(db_path, record.id) == record
    assert event.event_type is RunEventType.RUN_RECEIVED
    assert list_events(db_path, record.id) == [event]


def test_duplicate_run_rolls_back_its_initial_event(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    record = _record()
    create_run(db_path, record, event_id="event-1")

    with pytest.raises(sqlite3.IntegrityError):
        create_run(db_path, record, event_id="event-2")

    assert [event.id for event in list_events(db_path, record.id)] == ["event-1"]


def test_create_rejects_non_initial_snapshot(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    record = RunRecord(
        **{
            **_record().to_dict(),
            "state": RunState.EXECUTING,
            "budget": _record().budget,
        }
    )

    with pytest.raises(InvalidInitialRun, match="received at version 1"):
        create_run(db_path, record, event_id="event-1")

    assert get_run(db_path, record.id) is None


def test_event_ledger_is_ordered_and_append_only(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    record = _record()
    create_run(db_path, record, event_id="event-1")
    append_event(
        db_path,
        RunEventRecord(
            id="event-2",
            run_id=record.id,
            sequence=2,
            event_type=RunEventType.RUN_STATE_CHANGED,
            created_at="2026-07-23T10:01:00+08:00",
            payload={"from": "received", "to": "understanding"},
        ),
    )

    assert [event.sequence for event in list_events(db_path, record.id)] == [1, 2]
    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE runtime_events SET payload_json = '{}' WHERE id = 'event-2'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM runtime_events WHERE id = 'event-2'")
    finally:
        conn.close()


def test_transition_updates_snapshot_and_appends_event_atomically(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    create_run(db_path, _record(), event_id="event-1")

    updated = transition_run(
        db_path,
        "run-1",
        RunState.UNDERSTANDING,
        expected_version=1,
        event_id="event-2",
        updated_at="2026-07-23T10:01:00+08:00",
    )

    assert updated.state is RunState.UNDERSTANDING
    assert updated.version == 2
    events = list_events(db_path, "run-1")
    assert [event.sequence for event in events] == [1, 2]
    assert events[-1].payload == {
        "from": "received",
        "to": "understanding",
        "version": 2,
        "stop_reason": None,
        "completed_at": None,
    }


def test_stale_version_rejects_transition_without_event(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    create_run(db_path, _record(), event_id="event-1")

    with pytest.raises(RunVersionConflict, match="expected 0, actual 1"):
        transition_run(
            db_path,
            "run-1",
            RunState.UNDERSTANDING,
            expected_version=0,
            event_id="event-2",
            updated_at="2026-07-23T10:01:00+08:00",
        )

    assert get_run(db_path, "run-1") == _record()
    assert [event.id for event in list_events(db_path, "run-1")] == ["event-1"]


def test_illegal_transition_rejects_snapshot_and_event(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    create_run(db_path, _record(), event_id="event-1")

    with pytest.raises(InvalidRunTransition, match="received -> completed"):
        transition_run(
            db_path,
            "run-1",
            RunState.COMPLETED,
            expected_version=1,
            event_id="event-2",
            updated_at="2026-07-23T10:01:00+08:00",
        )

    assert get_run(db_path, "run-1") == _record()
    assert len(list_events(db_path, "run-1")) == 1


def test_duplicate_event_rolls_back_snapshot_transition(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    create_run(db_path, _record(), event_id="event-1")

    with pytest.raises(sqlite3.IntegrityError):
        transition_run(
            db_path,
            "run-1",
            RunState.UNDERSTANDING,
            expected_version=1,
            event_id="event-1",
            updated_at="2026-07-23T10:01:00+08:00",
        )

    assert get_run(db_path, "run-1") == _record()
    assert len(list_events(db_path, "run-1")) == 1


def test_missing_run_is_reported_without_creating_event(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)

    with pytest.raises(RunNotFound, match="missing"):
        transition_run(
            db_path,
            "missing",
            RunState.UNDERSTANDING,
            expected_version=1,
            event_id="event-1",
            updated_at="2026-07-23T10:01:00+08:00",
        )


def test_terminal_snapshot_cannot_transition_or_append_event(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    create_run(db_path, _record(), event_id="event-1")
    path = (
        RunState.UNDERSTANDING,
        RunState.PLANNING,
        RunState.EXECUTING,
        RunState.VERIFYING,
        RunState.COMPLETED,
    )
    updated = _record()
    for version, target in enumerate(path, start=1):
        updated = transition_run(
            db_path,
            "run-1",
            target,
            expected_version=version,
            event_id=f"event-{version + 1}",
            updated_at=f"2026-07-23T10:0{version}:00+08:00",
            stop_reason=(
                StopReason.GOAL_SATISFIED
                if target is RunState.COMPLETED
                else None
            ),
        )

    assert updated.state is RunState.COMPLETED
    assert updated.stop_reason is StopReason.GOAL_SATISFIED
    assert updated.completed_at == "2026-07-23T10:05:00+08:00"
    with pytest.raises(InvalidRunTransition, match="completed -> executing"):
        transition_run(
            db_path,
            "run-1",
            RunState.EXECUTING,
            expected_version=6,
            event_id="event-7",
            updated_at="2026-07-23T10:06:00+08:00",
        )
    assert len(list_events(db_path, "run-1")) == 6


def test_event_ledger_rebuilds_current_run_snapshot(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    create_run(db_path, _record(), event_id="event-1")
    updated = transition_run(
        db_path,
        "run-1",
        RunState.UNDERSTANDING,
        expected_version=1,
        event_id="event-2",
        updated_at="2026-07-23T10:01:00+08:00",
    )

    rebuilt = rebuild_run_snapshot(list_events(db_path, "run-1"))

    assert rebuilt == updated == get_run(db_path, "run-1")


def test_rebuild_rejects_event_sequence_gap(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    first = create_run(db_path, _record(), event_id="event-1")
    broken = RunEventRecord(
        id="event-3",
        run_id="run-1",
        sequence=3,
        event_type=RunEventType.RUN_STATE_CHANGED,
        created_at="2026-07-23T10:01:00+08:00",
        payload={
            "from": "received",
            "to": "understanding",
            "version": 2,
            "stop_reason": None,
            "completed_at": None,
        },
    )

    with pytest.raises(RunLedgerCorrupted, match="sequence is not contiguous"):
        rebuild_run_snapshot([first, broken])


def test_rebuild_rejects_transition_from_wrong_snapshot(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    first = create_run(db_path, _record(), event_id="event-1")
    broken = RunEventRecord(
        id="event-2",
        run_id="run-1",
        sequence=2,
        event_type=RunEventType.RUN_STATE_CHANGED,
        created_at="2026-07-23T10:01:00+08:00",
        payload={
            "from": "planning",
            "to": "executing",
            "version": 2,
            "stop_reason": None,
            "completed_at": None,
        },
    )

    with pytest.raises(RunLedgerCorrupted, match="source does not match"):
        rebuild_run_snapshot([first, broken])


def test_create_and_get_step_round_trip_with_event(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    create_run(db_path, _record(), event_id="event-1")

    event = create_step(
        db_path,
        _step(),
        event_id="event-2",
        created_at="2026-07-23T10:01:00+08:00",
    )

    assert get_step(db_path, "step-1") == _step()
    assert event.event_type is RunEventType.STEP_CREATED
    assert event.step_id == "step-1"
    assert [item.sequence for item in list_events(db_path, "run-1")] == [1, 2]


def test_create_step_requires_existing_run_and_initial_state(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)

    with pytest.raises(RunNotFound, match="run-1"):
        create_step(
            db_path,
            _step(),
            event_id="event-1",
            created_at="2026-07-23T10:01:00+08:00",
        )
    invalid = replace(_step(), state=StepState.READY)
    with pytest.raises(InvalidInitialStep, match="pending with zero attempts"):
        create_step(
            db_path,
            invalid,
            event_id="event-2",
            created_at="2026-07-23T10:01:00+08:00",
        )


def test_duplicate_step_event_rolls_back_step_insert(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    create_run(db_path, _record(), event_id="event-1")

    with pytest.raises(sqlite3.IntegrityError):
        create_step(
            db_path,
            _step(),
            event_id="event-1",
            created_at="2026-07-23T10:01:00+08:00",
        )

    assert get_step(db_path, "step-1") is None
    assert len(list_events(db_path, "run-1")) == 1


def test_transition_step_updates_snapshot_and_event_atomically(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    create_run(db_path, _record(), event_id="event-1")
    create_step(
        db_path,
        _step(),
        event_id="event-2",
        created_at="2026-07-23T10:01:00+08:00",
    )

    ready = transition_step(
        db_path,
        "step-1",
        StepState.READY,
        expected_state=StepState.PENDING,
        event_id="event-3",
        transitioned_at="2026-07-23T10:02:00+08:00",
    )
    running = transition_step(
        db_path,
        "step-1",
        StepState.RUNNING,
        expected_state=StepState.READY,
        event_id="event-4",
        transitioned_at="2026-07-23T10:03:00+08:00",
    )

    assert ready.state is StepState.READY
    assert running.state is StepState.RUNNING
    assert running.attempt_count == 1
    assert running.started_at == "2026-07-23T10:03:00+08:00"
    assert get_step(db_path, "step-1") == running


def test_stale_step_state_rejects_snapshot_and_event(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    create_run(db_path, _record(), event_id="event-1")
    create_step(
        db_path,
        _step(),
        event_id="event-2",
        created_at="2026-07-23T10:01:00+08:00",
    )
    transition_step(
        db_path,
        "step-1",
        StepState.READY,
        expected_state=StepState.PENDING,
        event_id="event-3",
        transitioned_at="2026-07-23T10:02:00+08:00",
    )

    with pytest.raises(StepStateConflict, match="expected pending, actual ready"):
        transition_step(
            db_path,
            "step-1",
            StepState.READY,
            expected_state=StepState.PENDING,
            event_id="event-4",
            transitioned_at="2026-07-23T10:03:00+08:00",
        )

    assert get_step(db_path, "step-1").state is StepState.READY
    assert len(list_events(db_path, "run-1")) == 3


def test_step_transition_failure_rolls_back_snapshot(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    create_run(db_path, _record(), event_id="event-1")
    create_step(
        db_path,
        _step(),
        event_id="event-2",
        created_at="2026-07-23T10:01:00+08:00",
    )

    with pytest.raises(InvalidStepTransition, match="pending -> running"):
        transition_step(
            db_path,
            "step-1",
            StepState.RUNNING,
            expected_state=StepState.PENDING,
            event_id="event-3",
            transitioned_at="2026-07-23T10:02:00+08:00",
        )
    with pytest.raises(StepNotFound, match="missing"):
        transition_step(
            db_path,
            "missing",
            StepState.READY,
            expected_state=StepState.PENDING,
            event_id="event-4",
            transitioned_at="2026-07-23T10:02:00+08:00",
        )

    assert get_step(db_path, "step-1") == _step()
    assert len(list_events(db_path, "run-1")) == 2


def test_terminal_step_cannot_transition_or_append_event(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    create_run(db_path, _record(), event_id="event-1")
    create_step(
        db_path,
        _step(),
        event_id="event-2",
        created_at="2026-07-23T10:01:00+08:00",
    )
    path = (
        StepState.READY,
        StepState.RUNNING,
        StepState.VERIFYING,
        StepState.COMPLETED,
    )
    updated = _step()
    for sequence, target in enumerate(path, start=3):
        if target is StepState.COMPLETED:
            record_artifact(
                db_path,
                ArtifactRecord(
                    id="artifact-1",
                    run_id="run-1",
                    step_id="step-1",
                    kind="test",
                    uri_or_path="/tmp/result",
                    fingerprint="sha256:abc",
                    media_type="text/plain",
                    created_by="test",
                ),
                event_id="artifact-event",
                created_at="2026-07-23T10:04:30+08:00",
            )
            record_verification(
                db_path,
                VerificationReceipt(
                    id="verification-1",
                    run_id="run-1",
                    step_id="step-1",
                    verifier="test",
                    status=VerificationStatus.VERIFIED,
                    criteria=_step().success_criteria,
                    evidence_refs=("artifact-1",),
                    checked_at="2026-07-23T10:04:45+08:00",
                ),
                event_id="verification-event",
            )
        updated = transition_step(
            db_path,
            "step-1",
            target,
            expected_state=updated.state,
            event_id=f"event-{sequence}",
            transitioned_at=f"2026-07-23T10:0{sequence - 1}:00+08:00",
        )

    assert updated.state is StepState.COMPLETED
    assert updated.finished_at == "2026-07-23T10:05:00+08:00"
    with pytest.raises(InvalidStepTransition, match="completed -> running"):
        transition_step(
            db_path,
            "step-1",
            StepState.RUNNING,
            expected_state=StepState.COMPLETED,
            event_id="event-7",
            transitioned_at="2026-07-23T10:06:00+08:00",
        )
    assert len(list_events(db_path, "run-1")) == 8


def test_step_attempt_limit_blocks_retry_without_event(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    create_run(db_path, _record(), event_id="event-1")
    step = replace(_step(), max_attempts=1)
    create_step(
        db_path,
        step,
        event_id="event-2",
        created_at="2026-07-23T10:01:00+08:00",
    )
    ready = transition_step(
        db_path,
        "step-1",
        StepState.READY,
        expected_state=StepState.PENDING,
        event_id="event-3",
        transitioned_at="2026-07-23T10:02:00+08:00",
    )
    running = transition_step(
        db_path,
        "step-1",
        StepState.RUNNING,
        expected_state=ready.state,
        event_id="event-4",
        transitioned_at="2026-07-23T10:03:00+08:00",
    )
    verifying = transition_step(
        db_path,
        "step-1",
        StepState.VERIFYING,
        expected_state=running.state,
        event_id="event-5",
        transitioned_at="2026-07-23T10:04:00+08:00",
    )

    with pytest.raises(StepAttemptLimitExceeded, match="step-1"):
        transition_step(
            db_path,
            "step-1",
            StepState.RUNNING,
            expected_state=verifying.state,
            event_id="event-6",
            transitioned_at="2026-07-23T10:05:00+08:00",
        )

    assert get_step(db_path, "step-1") == verifying
    assert len(list_events(db_path, "run-1")) == 5


def test_event_ledger_rebuilds_current_step_snapshot(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    create_run(db_path, _record(), event_id="event-1")
    create_step(
        db_path,
        _step(),
        event_id="event-2",
        created_at="2026-07-23T10:01:00+08:00",
    )
    ready = transition_step(
        db_path,
        "step-1",
        StepState.READY,
        expected_state=StepState.PENDING,
        event_id="event-3",
        transitioned_at="2026-07-23T10:02:00+08:00",
    )
    running = transition_step(
        db_path,
        "step-1",
        StepState.RUNNING,
        expected_state=ready.state,
        event_id="event-4",
        transitioned_at="2026-07-23T10:03:00+08:00",
    )

    rebuilt = rebuild_step_snapshot(
        list_events(db_path, "run-1"),
        "step-1",
    )

    assert rebuilt == running == get_step(db_path, "step-1")


def test_step_rebuild_rejects_non_contiguous_attempt_count(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    create_run(db_path, _record(), event_id="event-1")
    created = create_step(
        db_path,
        _step(),
        event_id="event-2",
        created_at="2026-07-23T10:01:00+08:00",
    )
    ready = RunEventRecord(
        id="event-3",
        run_id="run-1",
        step_id="step-1",
        sequence=3,
        event_type=RunEventType.STEP_STATE_CHANGED,
        created_at="2026-07-23T10:02:00+08:00",
        payload={
            "from": "pending",
            "to": "ready",
            "attempt_count": 0,
            "started_at": None,
            "finished_at": None,
        },
    )
    broken = replace(
        ready,
        id="event-4",
        sequence=4,
        payload={
            "from": "ready",
            "to": "running",
            "attempt_count": 3,
            "started_at": "2026-07-23T10:03:00+08:00",
            "finished_at": None,
        },
    )
    first = list_events(db_path, "run-1")[0]

    with pytest.raises(RunLedgerCorrupted, match="attempt count"):
        rebuild_step_snapshot([first, created, ready, broken], "step-1")


def test_scan_returns_only_consistent_non_terminal_runs(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    open_run = _record()
    closed_run = replace(_record(), id="run-2")
    create_run(db_path, open_run, event_id="open-event-1")
    create_step(
        db_path,
        _step(),
        event_id="open-event-2",
        created_at="2026-07-23T10:01:00+08:00",
    )
    create_run(db_path, closed_run, event_id="closed-event-1")
    current = closed_run
    for sequence, target in enumerate(
        (
            RunState.UNDERSTANDING,
            RunState.PLANNING,
            RunState.EXECUTING,
            RunState.VERIFYING,
            RunState.COMPLETED,
        ),
        start=2,
    ):
        current = transition_run(
            db_path,
            "run-2",
            target,
            expected_version=current.version,
            event_id=f"closed-event-{sequence}",
            updated_at=f"2026-07-23T11:0{sequence}:00+08:00",
            stop_reason=(
                StopReason.GOAL_SATISFIED
                if target is RunState.COMPLETED
                else None
            ),
        )

    assert scan_non_terminal_runs(db_path) == [open_run]


def test_scan_rejects_snapshot_that_disagrees_with_ledger(tmp_path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    create_run(db_path, _record(), event_id="event-1")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE runtime_runs SET objective = 'tampered' WHERE id = 'run-1'"
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(RunSnapshotMismatch, match="run-1"):
        scan_non_terminal_runs(db_path)
