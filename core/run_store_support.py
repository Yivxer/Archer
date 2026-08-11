"""Shared SQLite primitives for Runtime Closure persistence."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from core.run_contract import RunEventRecord


class RunNotFound(LookupError):
    """Raised when a requested runtime run does not exist."""


class RunLedgerCorrupted(RuntimeError):
    """Raised when runtime events cannot rebuild a coherent snapshot."""


def connect(db_path: str | Path) -> sqlite3.Connection:
    resolved_db_path = Path(db_path).expanduser()
    conn = sqlite3.connect(resolved_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def insert_event(conn: sqlite3.Connection, event: RunEventRecord) -> None:
    conn.execute(
        """
        INSERT INTO runtime_events(
            id, run_id, step_id, sequence, event_type, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.id,
            event.run_id,
            event.step_id,
            event.sequence,
            event.event_type.value,
            json_dump(event.payload),
            event.created_at,
        ),
    )


def next_event_sequence(conn: sqlite3.Connection, run_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM runtime_events WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return int(row[0])


def require_run_exists(conn: sqlite3.Connection, run_id: str) -> None:
    row = conn.execute(
        "SELECT 1 FROM runtime_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        raise RunNotFound(run_id)


def validate_event_sequence(events: Sequence[RunEventRecord]) -> None:
    if not events:
        raise RunLedgerCorrupted("run ledger is empty")
    if [event.sequence for event in events] != list(range(1, len(events) + 1)):
        raise RunLedgerCorrupted("run ledger sequence is not contiguous")
