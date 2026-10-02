"""Lifecycle of Part 8 cues, separate from saved conversation threads."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

TERMINAL_STATES = frozenset({"resolved", "closed", "dismissed", "expired"})


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def get_thread_clue(db_path: Path, clue_id: int) -> dict[str, Any] | None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if not _has_table(conn, "part8_threads"):
            return None
        row = conn.execute("SELECT * FROM part8_threads WHERE id=?", (clue_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def thread_clue_allows_delivery(db_path: Path, log: dict[str, Any]) -> bool:
    value = (log.get("decision_trace") or {}).get("threadId")
    # Legacy nonnumeric trace identifiers are not Part 8 cue IDs.
    if isinstance(value, bool) or not str(value or "").isdigit():
        return True
    clue = get_thread_clue(db_path, int(value))
    return clue is not None and clue["status"] == "open"


def _archive_candidates(conn: sqlite3.Connection, clue_id: int, status: str, stamp: str) -> list[int]:
    if not _has_table(conn, "initiative_sent_log"):
        return []
    ids = []
    for log_id, raw in conn.execute("SELECT id, decision_trace_json FROM initiative_sent_log WHERE kind='thread_resume'"):
        try:
            trace = json.loads(raw or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(trace, dict) or str(trace.get("threadId")) != str(clue_id):
            continue
        trace["threadLifecycle"] = {"previousStatus": "open", "status": status, "at": stamp}
        conn.execute(
            "UPDATE initiative_sent_log SET archived_at=COALESCE(archived_at, ?), decision_trace_json=? WHERE id=?",
            (stamp, json.dumps(trace, ensure_ascii=False), log_id),
        )
        ids.append(int(log_id))
    return ids


def _pending_outbox_ids(conn: sqlite3.Connection, log_ids: list[int]) -> list[str]:
    if not log_ids or not _has_table(conn, "durable_outbox"):
        return []
    ids = []
    for item_id, raw in conn.execute(
        "SELECT id, payload_json FROM durable_outbox WHERE kind='initiative.thread_resume' "
        "AND status IN ('pending','approved','failed')"
    ):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("initiativeLogId") in log_ids:
            ids.append(str(item_id))
    return ids


def transition_thread_clue(
    db_path: Path, clue_id: int, status: str, *, now: datetime | None = None,
) -> dict[str, Any] | None:
    if status not in TERMINAL_STATES:
        raise ValueError("unsupported thread clue status")
    stamp = (now or datetime.now()).isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        if not _has_table(conn, "part8_threads"):
            return None
        row = conn.execute("SELECT status, closed_at FROM part8_threads WHERE id=?", (clue_id,)).fetchone()
        if row is None:
            return None
        if row["status"] not in {"open", status}:
            raise ValueError("thread clue already has a different terminal status")
        if row["status"] == status:
            return {"id": clue_id, "status": status, "closedAt": row["closed_at"], "changed": False}
        conn.execute(
            "UPDATE part8_threads SET status=?, closed_at=?, archived_at=? WHERE id=? AND status='open'",
            (status, stamp, stamp, clue_id),
        )
        log_ids = _archive_candidates(conn, clue_id, status, stamp)
        outbox_ids = _pending_outbox_ids(conn, log_ids)
        conn.commit()
    finally:
        conn.close()
    from infrastructure.outbox import cancel

    for item_id in outbox_ids:
        cancel(db_path, item_id, now=now)
    return {"id": clue_id, "status": status, "closedAt": stamp, "changed": True}


def expire_stale_thread_clues(
    db_path: Path, *, max_idle_days: int = 30, now: datetime | None = None,
) -> list[int]:
    """Explicit maintenance only; never runs against user cues on startup."""
    if isinstance(max_idle_days, bool) or not isinstance(max_idle_days, int) or not 1 <= max_idle_days <= 365:
        raise ValueError("max_idle_days must be between 1 and 365")
    current = now or datetime.now()
    current = current.astimezone().replace(tzinfo=None) if current.tzinfo else current
    cutoff = current - timedelta(days=max_idle_days)
    conn = sqlite3.connect(db_path)
    try:
        if not _has_table(conn, "part8_threads"):
            return []
        rows = conn.execute("SELECT id, last_seen_at FROM part8_threads WHERE status='open'").fetchall()
    finally:
        conn.close()
    expired = []
    for clue_id, raw in rows:
        try:
            seen = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            continue
        seen = seen.astimezone().replace(tzinfo=None) if seen.tzinfo else seen
        if seen <= cutoff:
            result = transition_thread_clue(db_path, int(clue_id), "expired", now=current)
            if result and result["changed"]:
                expired.append(int(clue_id))
    return expired
