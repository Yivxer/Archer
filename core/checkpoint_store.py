"""Append-only checkpoint persistence for resumable Runtime Closure runs."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from core.run_contract import (
    TERMINAL_RUN_STATES,
    RunCheckpoint,
    RunEventRecord,
    RunEventType,
    RunState,
)
from core.run_store_support import connect, insert_event, json_dump, next_event_sequence

RESUMABLE_STATES = frozenset(
    {RunState.PLANNING, RunState.EXECUTING, RunState.VERIFYING}
)


class CheckpointConflict(RuntimeError):
    """Raised when checkpoint input disagrees with the current Run snapshot."""


class InvalidCheckpoint(ValueError):
    """Raised when a checkpoint cannot safely describe a resume point."""


def _validate_checkpoint(record: RunCheckpoint) -> None:
    if record.resume_state not in RESUMABLE_STATES:
        raise InvalidCheckpoint("checkpoint resume_state is not resumable")
    if record.cursor_version < 1:
        raise InvalidCheckpoint("checkpoint cursor_version must be positive")
    if not isinstance(record.cursor, dict):
        raise InvalidCheckpoint("checkpoint cursor must be an object")


def _require_matching_run(
    conn: sqlite3.Connection,
    record: RunCheckpoint,
    expected_run_version: int,
) -> None:
    row = conn.execute(
        "SELECT state, current_step_id, version FROM runtime_runs WHERE id = ?",
        (record.run_id,),
    ).fetchone()
    if row is None:
        raise CheckpointConflict(f"run does not exist: {record.run_id}")
    if int(row["version"]) != expected_run_version:
        raise CheckpointConflict("run version changed before checkpoint")
    if RunState(row["state"]) in TERMINAL_RUN_STATES:
        raise CheckpointConflict("terminal run cannot accept checkpoints")
    if record.step_id and record.step_id != row["current_step_id"]:
        raise CheckpointConflict("checkpoint step is not the current run step")


def _checkpoint_event(
    conn: sqlite3.Connection,
    record: RunCheckpoint,
    event_id: str,
    run_version: int,
) -> RunEventRecord:
    return RunEventRecord(
        id=event_id,
        run_id=record.run_id,
        step_id=record.step_id,
        sequence=next_event_sequence(conn, record.run_id),
        event_type=RunEventType.CHECKPOINT_RECORDED,
        created_at=record.created_at,
        payload={"checkpoint": record.to_dict(), "run_version": run_version},
    )


def record_checkpoint(
    db_path: str | Path,
    record: RunCheckpoint,
    *,
    expected_run_version: int,
    event_id: str,
) -> RunCheckpoint:
    _validate_checkpoint(record)
    conn = connect(db_path)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            _require_matching_run(conn, record, expected_run_version)
            conn.execute(
                """
                INSERT INTO runtime_checkpoints(
                    id, run_id, step_id, resume_state, cursor_version,
                    cursor_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.run_id,
                    record.step_id,
                    record.resume_state.value,
                    record.cursor_version,
                    json_dump(record.cursor),
                    record.created_at,
                ),
            )
            insert_event(
                conn,
                _checkpoint_event(conn, record, event_id, expected_run_version),
            )
        return record
    finally:
        conn.close()


def _row_to_checkpoint(row: sqlite3.Row) -> RunCheckpoint:
    return RunCheckpoint(
        id=row["id"],
        run_id=row["run_id"],
        step_id=row["step_id"],
        resume_state=RunState(row["resume_state"]),
        cursor_version=row["cursor_version"],
        cursor=json.loads(row["cursor_json"]),
        created_at=row["created_at"],
    )


def list_checkpoints(
    db_path: str | Path,
    run_id: str,
) -> list[RunCheckpoint]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT * FROM runtime_checkpoints
            WHERE run_id = ?
            ORDER BY rowid
            """,
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_checkpoint(row) for row in rows]


def latest_checkpoint(
    db_path: str | Path,
    run_id: str,
) -> RunCheckpoint | None:
    checkpoints = list_checkpoints(db_path, run_id)
    return checkpoints[-1] if checkpoints else None
