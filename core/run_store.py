"""Run persistence boundary and stable Runtime Closure store facade."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from core.run_contract import (
    RunBudget,
    RunEventRecord,
    RunEventType,
    RunRecord,
    RunState,
    StopReason,
    require_run_transition,
)
from core.run_store_support import (
    RunLedgerCorrupted,
    RunNotFound,
    connect,
    insert_event,
    json_dump,
    next_event_sequence,
    validate_event_sequence,
)
from core.step_store import (
    InvalidInitialStep,
    StepAttemptLimitExceeded,
    StepNotFound,
    StepStateConflict,
    StepVerificationRequired,
    create_step,
    get_step,
    rebuild_step_snapshot,
    transition_step,
)

__all__ = [
    "InvalidInitialRun",
    "InvalidInitialStep",
    "RunLedgerCorrupted",
    "RunNotFound",
    "RunSnapshotMismatch",
    "RunVersionConflict",
    "StepAttemptLimitExceeded",
    "StepNotFound",
    "StepStateConflict",
    "StepVerificationRequired",
    "append_event",
    "create_run",
    "create_step",
    "get_run",
    "get_verified_run",
    "get_step",
    "list_events",
    "list_non_terminal_runs",
    "rebuild_run_snapshot",
    "rebuild_step_snapshot",
    "scan_non_terminal_runs",
    "transition_run",
    "transition_step",
]


class RunVersionConflict(RuntimeError):
    """Raised when a caller writes against a stale run snapshot."""


class InvalidInitialRun(ValueError):
    """Raised when a new run is not an initial received snapshot."""


class RunSnapshotMismatch(RunLedgerCorrupted):
    """Raised when the run table disagrees with its event ledger."""


def _insert_run(conn: sqlite3.Connection, record: RunRecord) -> None:
    conn.execute(
        """
        INSERT INTO runtime_runs(
            id, contract_version, objective, source, state, stop_reason,
            current_step_id, session_id, thread_id, parent_run_id,
            context_receipt_id, budget_json, created_at, updated_at,
            completed_at, version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.id,
            record.contract_version,
            record.objective,
            record.source,
            record.state.value,
            record.stop_reason.value if record.stop_reason else None,
            record.current_step_id,
            record.session_id,
            record.thread_id,
            record.parent_run_id,
            record.context_receipt_id,
            json_dump(record.to_dict()["budget"]),
            record.created_at,
            record.updated_at,
            record.completed_at,
            record.version,
        ),
    )


def create_run(
    db_path: str | Path,
    record: RunRecord,
    *,
    event_id: str,
) -> RunEventRecord:
    if record.state is not RunState.RECEIVED or record.version != 1:
        raise InvalidInitialRun("new run must start as received at version 1")
    event = RunEventRecord(
        id=event_id,
        run_id=record.id,
        sequence=1,
        event_type=RunEventType.RUN_RECEIVED,
        created_at=record.created_at,
        payload={"run": record.to_dict()},
    )
    conn = connect(db_path)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            _insert_run(conn, record)
            insert_event(conn, event)
    finally:
        conn.close()
    return event


def _row_to_run(row: sqlite3.Row) -> RunRecord:
    return RunRecord(
        id=row["id"],
        objective=row["objective"],
        source=row["source"],
        state=RunState(row["state"]),
        stop_reason=StopReason(row["stop_reason"]) if row["stop_reason"] else None,
        current_step_id=row["current_step_id"],
        session_id=row["session_id"],
        thread_id=row["thread_id"],
        parent_run_id=row["parent_run_id"],
        context_receipt_id=row["context_receipt_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
        version=row["version"],
        contract_version=row["contract_version"],
        budget=RunBudget(**json.loads(row["budget_json"])),
    )


def get_run(db_path: str | Path, run_id: str) -> RunRecord | None:
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM runtime_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    return _row_to_run(row) if row is not None else None


def _require_current_run(conn: sqlite3.Connection, run_id: str) -> RunRecord:
    row = conn.execute(
        "SELECT * FROM runtime_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        raise RunNotFound(run_id)
    return _row_to_run(row)


def _update_run_snapshot(
    conn: sqlite3.Connection,
    current: RunRecord,
    target: RunState,
    *,
    updated_at: str,
    stop_reason: StopReason | None,
) -> RunRecord:
    next_version = current.version + 1
    completed_at = updated_at if target in {
        RunState.COMPLETED,
        RunState.FAILED,
        RunState.CANCELLED,
    } else None
    cursor = conn.execute(
        """
        UPDATE runtime_runs
        SET state = ?, stop_reason = ?, updated_at = ?, completed_at = ?,
            version = ?
        WHERE id = ? AND version = ?
        """,
        (
            target.value,
            stop_reason.value if stop_reason else None,
            updated_at,
            completed_at,
            next_version,
            current.id,
            current.version,
        ),
    )
    if cursor.rowcount != 1:
        raise RunVersionConflict(f"run version changed during update: {current.id}")
    return replace(
        current,
        state=target,
        stop_reason=stop_reason,
        updated_at=updated_at,
        completed_at=completed_at,
        version=next_version,
    )


def _transition_event(
    conn: sqlite3.Connection,
    current: RunRecord,
    updated: RunRecord,
    *,
    event_id: str,
) -> RunEventRecord:
    return RunEventRecord(
        id=event_id,
        run_id=current.id,
        sequence=next_event_sequence(conn, current.id),
        event_type=RunEventType.RUN_STATE_CHANGED,
        created_at=updated.updated_at,
        payload={
            "from": current.state.value,
            "to": updated.state.value,
            "version": updated.version,
            "stop_reason": (
                updated.stop_reason.value if updated.stop_reason is not None else None
            ),
            "completed_at": updated.completed_at,
        },
    )


def transition_run(
    db_path: str | Path,
    run_id: str,
    target: RunState,
    *,
    expected_version: int,
    event_id: str,
    updated_at: str,
    stop_reason: StopReason | None = None,
) -> RunRecord:
    conn = connect(db_path)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            current = _require_current_run(conn, run_id)
            if current.version != expected_version:
                raise RunVersionConflict(
                    f"stale run version: expected {expected_version}, "
                    f"actual {current.version}"
                )
            require_run_transition(current.state, target)
            updated = _update_run_snapshot(
                conn,
                current,
                target,
                updated_at=updated_at,
                stop_reason=stop_reason,
            )
            insert_event(
                conn,
                _transition_event(conn, current, updated, event_id=event_id),
            )
        return updated
    finally:
        conn.close()


def append_event(db_path: str | Path, event: RunEventRecord) -> None:
    conn = connect(db_path)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            insert_event(conn, event)
    finally:
        conn.close()


def list_events(db_path: str | Path, run_id: str) -> list[RunEventRecord]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM runtime_events WHERE run_id = ? ORDER BY sequence",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        RunEventRecord(
            id=row["id"],
            run_id=row["run_id"],
            step_id=row["step_id"],
            sequence=row["sequence"],
            event_type=RunEventType(row["event_type"]),
            payload=json.loads(row["payload_json"]),
            created_at=row["created_at"],
        )
        for row in rows
    ]


def _payload_to_run(payload: dict[str, Any]) -> RunRecord:
    try:
        raw = payload["run"]
        return RunRecord(
            id=raw["id"],
            objective=raw["objective"],
            source=raw["source"],
            state=RunState(raw["state"]),
            stop_reason=(
                StopReason(raw["stop_reason"]) if raw["stop_reason"] else None
            ),
            current_step_id=raw["current_step_id"],
            session_id=raw["session_id"],
            thread_id=raw["thread_id"],
            parent_run_id=raw["parent_run_id"],
            context_receipt_id=raw["context_receipt_id"],
            created_at=raw["created_at"],
            updated_at=raw["updated_at"],
            completed_at=raw["completed_at"],
            version=raw["version"],
            contract_version=raw["contract_version"],
            budget=RunBudget(**raw["budget"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RunLedgerCorrupted("invalid run.received payload") from exc


def rebuild_run_snapshot(events: Sequence[RunEventRecord]) -> RunRecord:
    validate_event_sequence(events)
    first = events[0]
    if first.event_type is not RunEventType.RUN_RECEIVED:
        raise RunLedgerCorrupted("run ledger must start with run.received")
    current = _payload_to_run(first.payload)
    if current.id != first.run_id:
        raise RunLedgerCorrupted("run.received id does not match event")
    for event in events[1:]:
        if event.run_id != current.id:
            raise RunLedgerCorrupted("event run id does not match snapshot")
        if event.event_type is not RunEventType.RUN_STATE_CHANGED:
            continue
        payload = event.payload
        if payload.get("from") != current.state.value:
            raise RunLedgerCorrupted("state transition source does not match snapshot")
        if payload.get("version") != current.version + 1:
            raise RunLedgerCorrupted("state transition version is not contiguous")
        try:
            target = RunState(payload["to"])
            stop_reason = (
                StopReason(payload["stop_reason"])
                if payload.get("stop_reason") is not None
                else None
            )
            require_run_transition(current.state, target)
        except (KeyError, ValueError) as exc:
            raise RunLedgerCorrupted("invalid run state transition event") from exc
        current = replace(
            current,
            state=target,
            stop_reason=stop_reason,
            updated_at=event.created_at,
            completed_at=payload.get("completed_at"),
            version=payload["version"],
        )
    return current


def get_verified_run(db_path: str | Path, run_id: str) -> RunRecord | None:
    snapshot = get_run(db_path, run_id)
    if snapshot is None:
        return None
    rebuilt = rebuild_run_snapshot(list_events(db_path, run_id))
    if rebuilt != snapshot:
        raise RunSnapshotMismatch(f"run snapshot disagrees with ledger: {run_id}")
    return snapshot


def list_non_terminal_runs(db_path: str | Path) -> list[RunRecord]:
    terminal_states = (
        RunState.COMPLETED.value,
        RunState.FAILED.value,
        RunState.CANCELLED.value,
    )
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT * FROM runtime_runs
            WHERE state NOT IN (?, ?, ?)
            ORDER BY updated_at, id
            """,
            terminal_states,
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_run(row) for row in rows]


def scan_non_terminal_runs(db_path: str | Path) -> list[RunRecord]:
    snapshots = list_non_terminal_runs(db_path)
    for snapshot in snapshots:
        get_verified_run(db_path, snapshot.id)
    return snapshots
