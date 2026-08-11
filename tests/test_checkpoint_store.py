from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from core.checkpoint_store import (
    CheckpointConflict,
    InvalidCheckpoint,
    latest_checkpoint,
    list_checkpoints,
    record_checkpoint,
)
from core.run_contract import (
    RunCheckpoint,
    RunEventType,
    RunRecord,
    RunState,
)
from core.run_store import create_run, list_events, transition_run
from memory.migrations import run_migrations


def _create_planning_run(db_path: Path) -> RunRecord:
    run = RunRecord(
        id="run-checkpoint",
        objective="恢复 Runtime",
        source="test",
        created_at="2026-07-24T18:00:00+08:00",
        updated_at="2026-07-24T18:00:00+08:00",
    )
    create_run(db_path, run, event_id="event-run")
    run = transition_run(
        db_path,
        run.id,
        RunState.UNDERSTANDING,
        expected_version=run.version,
        event_id="event-understanding",
        updated_at="2026-07-24T18:00:01+08:00",
    )
    return transition_run(
        db_path,
        run.id,
        RunState.PLANNING,
        expected_version=run.version,
        event_id="event-planning",
        updated_at="2026-07-24T18:00:02+08:00",
    )


def _checkpoint(run: RunRecord, checkpoint_id: str = "checkpoint-1") -> RunCheckpoint:
    return RunCheckpoint(
        id=checkpoint_id,
        run_id=run.id,
        resume_state=RunState.PLANNING,
        cursor={"planIndex": 2, "sourceVersion": run.version},
        created_at="2026-07-24T18:00:03+08:00",
    )


def test_checkpoint_is_persisted_with_append_only_event(tmp_path: Path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    run = _create_planning_run(db_path)
    checkpoint = _checkpoint(run)

    recorded = record_checkpoint(
        db_path,
        checkpoint,
        expected_run_version=run.version,
        event_id="event-checkpoint",
    )

    assert recorded == checkpoint
    assert latest_checkpoint(db_path, run.id) == checkpoint
    assert list_events(db_path, run.id)[-1].event_type is RunEventType.CHECKPOINT_RECORDED
    assert list_events(db_path, run.id)[-1].payload["run_version"] == run.version


def test_latest_checkpoint_uses_append_order(tmp_path: Path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    run = _create_planning_run(db_path)
    first = _checkpoint(run)
    second = replace(
        first,
        id="checkpoint-2",
        cursor={"planIndex": 3},
        created_at="2026-07-24T18:00:04+08:00",
    )

    record_checkpoint(
        db_path,
        first,
        expected_run_version=run.version,
        event_id="event-checkpoint-1",
    )
    record_checkpoint(
        db_path,
        second,
        expected_run_version=run.version,
        event_id="event-checkpoint-2",
    )

    assert list_checkpoints(db_path, run.id) == [first, second]
    assert latest_checkpoint(db_path, run.id) == second


def test_checkpoint_rejects_stale_run_without_partial_write(tmp_path: Path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    run = _create_planning_run(db_path)

    with pytest.raises(CheckpointConflict, match="version changed"):
        record_checkpoint(
            db_path,
            _checkpoint(run),
            expected_run_version=run.version - 1,
            event_id="event-checkpoint",
        )

    assert list_checkpoints(db_path, run.id) == []
    assert len(list_events(db_path, run.id)) == 3


def test_checkpoint_rejects_non_resumable_target(tmp_path: Path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    run = _create_planning_run(db_path)

    with pytest.raises(InvalidCheckpoint, match="not resumable"):
        record_checkpoint(
            db_path,
            replace(_checkpoint(run), resume_state=RunState.COMPLETED),
            expected_run_version=run.version,
            event_id="event-checkpoint",
        )


def test_checkpoint_rows_are_append_only(tmp_path: Path) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    run = _create_planning_run(db_path)
    record_checkpoint(
        db_path,
        _checkpoint(run),
        expected_run_version=run.version,
        event_id="event-checkpoint",
    )

    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE runtime_checkpoints SET cursor_json = '{}' "
                "WHERE id = 'checkpoint-1'"
            )
    finally:
        conn.close()
