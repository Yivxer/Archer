"""Step persistence for Archer Runtime Closure."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from core.run_contract import (
    RunEventRecord,
    RunEventType,
    StepRecord,
    StepState,
    require_step_transition,
)
from core.run_store_support import (
    RunLedgerCorrupted,
    connect,
    insert_event,
    json_dump,
    next_event_sequence,
    require_run_exists,
    validate_event_sequence,
)


class StepNotFound(LookupError):
    """Raised when a requested runtime step does not exist."""


class StepStateConflict(RuntimeError):
    """Raised when a caller writes against a stale step state."""


class StepAttemptLimitExceeded(RuntimeError):
    """Raised when a step would start beyond its retry budget."""


class InvalidInitialStep(ValueError):
    """Raised when a new step is not an initial pending snapshot."""


class StepVerificationRequired(RuntimeError):
    """Raised when a step completion has no verified outcome receipt."""


def _insert_step(conn: sqlite3.Connection, record: StepRecord) -> None:
    conn.execute(
        """
        INSERT INTO runtime_steps(
            id, run_id, ordinal, title, kind, state, depends_on_json,
            capability, requires_approval, success_json, attempt_count,
            max_attempts, started_at, finished_at, error_code, error_summary
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.id,
            record.run_id,
            record.ordinal,
            record.title,
            record.kind,
            record.state.value,
            json_dump(list(record.depends_on)),
            record.capability,
            int(record.requires_approval),
            json_dump(list(record.success_criteria)),
            record.attempt_count,
            record.max_attempts,
            record.started_at,
            record.finished_at,
            record.error_code,
            record.error_summary,
        ),
    )


def _row_to_step(row: sqlite3.Row) -> StepRecord:
    return StepRecord(
        id=row["id"],
        run_id=row["run_id"],
        ordinal=row["ordinal"],
        title=row["title"],
        kind=row["kind"],
        state=StepState(row["state"]),
        depends_on=tuple(json.loads(row["depends_on_json"])),
        capability=row["capability"],
        requires_approval=bool(row["requires_approval"]),
        success_criteria=tuple(json.loads(row["success_json"])),
        attempt_count=row["attempt_count"],
        max_attempts=row["max_attempts"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error_code=row["error_code"],
        error_summary=row["error_summary"],
    )


def create_step(
    db_path: str | Path,
    record: StepRecord,
    *,
    event_id: str,
    created_at: str,
) -> RunEventRecord:
    if record.state is not StepState.PENDING or record.attempt_count != 0:
        raise InvalidInitialStep("new step must start as pending with zero attempts")
    event = RunEventRecord(
        id=event_id,
        run_id=record.run_id,
        step_id=record.id,
        sequence=0,
        event_type=RunEventType.STEP_CREATED,
        created_at=created_at,
        payload={"step": record.to_dict()},
    )
    conn = connect(db_path)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            require_run_exists(conn, record.run_id)
            _insert_step(conn, record)
            event = replace(
                event,
                sequence=next_event_sequence(conn, record.run_id),
            )
            insert_event(conn, event)
    finally:
        conn.close()
    return event


def get_step(db_path: str | Path, step_id: str) -> StepRecord | None:
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM runtime_steps WHERE id = ?",
            (step_id,),
        ).fetchone()
    finally:
        conn.close()
    return _row_to_step(row) if row is not None else None


def list_steps_for_run(
    db_path: str | Path,
    run_id: str,
) -> list[StepRecord]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT * FROM runtime_steps
            WHERE run_id = ?
            ORDER BY ordinal ASC, id ASC
            """,
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_step(row) for row in rows]


def _require_current_step(conn: sqlite3.Connection, step_id: str) -> StepRecord:
    row = conn.execute(
        "SELECT * FROM runtime_steps WHERE id = ?",
        (step_id,),
    ).fetchone()
    if row is None:
        raise StepNotFound(step_id)
    return _row_to_step(row)


def _update_step_snapshot(
    conn: sqlite3.Connection,
    current: StepRecord,
    target: StepState,
    *,
    transitioned_at: str,
) -> StepRecord:
    if target is StepState.COMPLETED:
        latest_verification = conn.execute(
            """
            SELECT status FROM runtime_verifications
            WHERE run_id = ? AND step_id = ?
            ORDER BY checked_at DESC, id DESC
            LIMIT 1
            """,
            (current.run_id, current.id),
        ).fetchone()
        if (
            latest_verification is None
            or latest_verification["status"] != "verified"
        ):
            raise StepVerificationRequired(
                f"latest receipt must be verified before completion: {current.id}"
            )
    if (
        target is StepState.RUNNING
        and current.attempt_count >= current.max_attempts
    ):
        raise StepAttemptLimitExceeded(f"step attempt limit reached: {current.id}")
    started_at = (
        current.started_at or transitioned_at
        if target is StepState.RUNNING
        else current.started_at
    )
    finished_at = (
        transitioned_at
        if target
        in {
            StepState.COMPLETED,
            StepState.FAILED,
            StepState.SKIPPED,
            StepState.CANCELLED,
        }
        else None
    )
    attempt_count = current.attempt_count + (
        1 if target is StepState.RUNNING else 0
    )
    cursor = conn.execute(
        """
        UPDATE runtime_steps
        SET state = ?, attempt_count = ?, started_at = ?, finished_at = ?
        WHERE id = ? AND state = ?
        """,
        (
            target.value,
            attempt_count,
            started_at,
            finished_at,
            current.id,
            current.state.value,
        ),
    )
    if cursor.rowcount != 1:
        raise StepStateConflict(f"step state changed during update: {current.id}")
    return replace(
        current,
        state=target,
        attempt_count=attempt_count,
        started_at=started_at,
        finished_at=finished_at,
    )


def _transition_event(
    conn: sqlite3.Connection,
    current: StepRecord,
    updated: StepRecord,
    *,
    event_id: str,
    transitioned_at: str,
) -> RunEventRecord:
    return RunEventRecord(
        id=event_id,
        run_id=current.run_id,
        step_id=current.id,
        sequence=next_event_sequence(conn, current.run_id),
        event_type=RunEventType.STEP_STATE_CHANGED,
        created_at=transitioned_at,
        payload={
            "from": current.state.value,
            "to": updated.state.value,
            "attempt_count": updated.attempt_count,
            "started_at": updated.started_at,
            "finished_at": updated.finished_at,
        },
    )


def transition_step(
    db_path: str | Path,
    step_id: str,
    target: StepState,
    *,
    expected_state: StepState,
    event_id: str,
    transitioned_at: str,
) -> StepRecord:
    conn = connect(db_path)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            current = _require_current_step(conn, step_id)
            if current.state is not expected_state:
                raise StepStateConflict(
                    f"stale step state: expected {expected_state.value}, "
                    f"actual {current.state.value}"
                )
            require_step_transition(current.state, target)
            updated = _update_step_snapshot(
                conn,
                current,
                target,
                transitioned_at=transitioned_at,
            )
            insert_event(
                conn,
                _transition_event(
                    conn,
                    current,
                    updated,
                    event_id=event_id,
                    transitioned_at=transitioned_at,
                ),
            )
        return updated
    finally:
        conn.close()


def _payload_to_step(payload: dict[str, Any]) -> StepRecord:
    try:
        raw = payload["step"]
        return StepRecord(
            id=raw["id"],
            run_id=raw["run_id"],
            ordinal=raw["ordinal"],
            title=raw["title"],
            kind=raw["kind"],
            state=StepState(raw["state"]),
            depends_on=tuple(raw["depends_on"]),
            capability=raw["capability"],
            requires_approval=raw["requires_approval"],
            success_criteria=tuple(raw["success_criteria"]),
            attempt_count=raw["attempt_count"],
            max_attempts=raw["max_attempts"],
            started_at=raw["started_at"],
            finished_at=raw["finished_at"],
            error_code=raw["error_code"],
            error_summary=raw["error_summary"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RunLedgerCorrupted("invalid step.created payload") from exc


def rebuild_step_snapshot(
    events: Sequence[RunEventRecord],
    step_id: str,
) -> StepRecord:
    validate_event_sequence(events)
    step_events = [event for event in events if event.step_id == step_id]
    if not step_events or step_events[0].event_type is not RunEventType.STEP_CREATED:
        raise RunLedgerCorrupted(f"step ledger is missing step.created: {step_id}")
    current = _payload_to_step(step_events[0].payload)
    if current.id != step_id or current.run_id != step_events[0].run_id:
        raise RunLedgerCorrupted("step.created identity does not match event")
    for event in step_events[1:]:
        if event.event_type is not RunEventType.STEP_STATE_CHANGED:
            continue
        payload = event.payload
        if event.run_id != current.run_id:
            raise RunLedgerCorrupted("step event run id does not match snapshot")
        if payload.get("from") != current.state.value:
            raise RunLedgerCorrupted("step transition source does not match snapshot")
        try:
            target = StepState(payload["to"])
            require_step_transition(current.state, target)
        except (KeyError, ValueError) as exc:
            raise RunLedgerCorrupted("invalid step state transition event") from exc
        expected_attempts = current.attempt_count + (
            1 if target is StepState.RUNNING else 0
        )
        if payload.get("attempt_count") != expected_attempts:
            raise RunLedgerCorrupted("step attempt count is not contiguous")
        current = replace(
            current,
            state=target,
            attempt_count=expected_attempts,
            started_at=payload.get("started_at"),
            finished_at=payload.get("finished_at"),
        )
    return current
