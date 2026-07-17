"""SQLite-backed durable outbox for approved external side effects."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4


OUTBOX_STATUSES = frozenset({
    "pending", "approved", "sending", "sent", "failed", "cancelled",
})


def init_outbox_table(db_path: str | Path) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS durable_outbox (
                id               TEXT PRIMARY KEY,
                kind             TEXT NOT NULL,
                idempotency_key  TEXT NOT NULL UNIQUE,
                payload_json     TEXT NOT NULL,
                status           TEXT NOT NULL CHECK (
                    status IN ('pending','approved','sending','sent','failed','cancelled')
                ),
                attempts         INTEGER NOT NULL DEFAULT 0,
                max_attempts     INTEGER NOT NULL DEFAULT 3,
                next_attempt_at  TEXT,
                last_error       TEXT NOT NULL DEFAULT '',
                result_json      TEXT,
                created_at       TEXT NOT NULL,
                updated_at       TEXT NOT NULL,
                approved_at      TEXT,
                sent_at          TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_durable_outbox_ready
                ON durable_outbox(status, next_attempt_at, created_at);
        """)
        conn.commit()
    finally:
        conn.close()


def enqueue(
    db_path: str | Path,
    *,
    kind: str,
    payload: dict[str, Any],
    idempotency_key: str,
    max_attempts: int = 3,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not kind.strip() or not idempotency_key.strip():
        raise ValueError("kind and idempotency_key are required")
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    init_outbox_table(db_path)
    timestamp = (now or datetime.now()).isoformat(timespec="seconds")
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    item_id = f"outbox-{uuid4().hex}"
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO durable_outbox "
            "(id, kind, idempotency_key, payload_json, status, attempts, max_attempts, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'pending', 0, ?, ?, ?)",
            (item_id, kind.strip(), idempotency_key.strip(), payload_json, max_attempts, timestamp, timestamp),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM durable_outbox WHERE idempotency_key = ?",
            (idempotency_key.strip(),),
        ).fetchone()
        item = _decode_row(row)
        if item["kind"] != kind.strip() or item["payload"] != payload:
            raise ValueError("idempotency_key already belongs to a different outbox payload")
        item["reused"] = cursor.rowcount == 0
        return item
    finally:
        conn.close()


def approve(db_path: str | Path, item_id: str, *, now: datetime | None = None) -> dict[str, Any] | None:
    return _transition(db_path, item_id, from_statuses={"pending"}, to_status="approved", now=now)


def cancel(db_path: str | Path, item_id: str, *, now: datetime | None = None) -> dict[str, Any] | None:
    return _transition(
        db_path, item_id,
        from_statuses={"pending", "approved", "failed"},
        to_status="cancelled", now=now,
    )


def claim_for_sending(
    db_path: str | Path,
    item_id: str,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> dict[str, Any] | None:
    timestamp = (now or datetime.now()).isoformat(timespec="seconds")
    conn = _connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM durable_outbox WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            conn.rollback()
            return None
        item = _decode_row(row)
        eligible = (
            item["status"] in {"approved", "failed"}
            and item["attempts"] < item["maxAttempts"]
            and (force or not item["nextAttemptAt"] or item["nextAttemptAt"] <= timestamp)
        )
        if not eligible:
            conn.rollback()
            return None
        conn.execute(
            "UPDATE durable_outbox SET status='sending', attempts=attempts+1, "
            "next_attempt_at=NULL, last_error='', updated_at=? WHERE id=?",
            (timestamp, item_id),
        )
        conn.commit()
        return get_item(db_path, item_id)
    finally:
        conn.close()


def mark_sent(
    db_path: str | Path,
    item_id: str,
    result: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    timestamp = (now or datetime.now()).isoformat(timespec="seconds")
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            "UPDATE durable_outbox SET status='sent', result_json=?, sent_at=?, updated_at=? "
            "WHERE id=? AND status='sending'",
            (json.dumps(result or {}, ensure_ascii=False, sort_keys=True), timestamp, timestamp, item_id),
        )
        conn.commit()
        return get_item(db_path, item_id) if cursor.rowcount else None
    finally:
        conn.close()


def mark_failed(
    db_path: str | Path,
    item_id: str,
    error: str,
    *,
    now: datetime | None = None,
    base_delay_seconds: int = 5,
) -> dict[str, Any] | None:
    current = get_item(db_path, item_id)
    if current is None or current["status"] != "sending":
        return None
    moment = now or datetime.now()
    next_attempt = None
    if current["attempts"] < current["maxAttempts"]:
        delay = max(0, base_delay_seconds) * (2 ** max(0, current["attempts"] - 1))
        next_attempt = (moment + timedelta(seconds=delay)).isoformat(timespec="seconds")
    timestamp = moment.isoformat(timespec="seconds")
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            "UPDATE durable_outbox SET status='failed', last_error=?, next_attempt_at=?, updated_at=? "
            "WHERE id=? AND status='sending'",
            (str(error)[:1000], next_attempt, timestamp, item_id),
        )
        conn.commit()
        return get_item(db_path, item_id) if cursor.rowcount else None
    finally:
        conn.close()


def recover_interrupted(db_path: str | Path, *, now: datetime | None = None) -> int:
    timestamp = (now or datetime.now()).isoformat(timespec="seconds")
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            "UPDATE durable_outbox SET status='failed', last_error='interrupted during sending', "
            "next_attempt_at=CASE WHEN attempts < max_attempts THEN ? ELSE NULL END, updated_at=? "
            "WHERE status='sending'",
            (timestamp, timestamp),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def get_item(db_path: str | Path, item_id: str) -> dict[str, Any] | None:
    conn = _connect(db_path)
    try:
        return _decode_row(conn.execute(
            "SELECT * FROM durable_outbox WHERE id = ?", (item_id,),
        ).fetchone())
    finally:
        conn.close()


def list_items(
    db_path: str | Path,
    *,
    statuses: set[str] | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    conn = _connect(db_path)
    try:
        params: list[Any] = []
        where = ""
        if statuses:
            invalid = statuses - OUTBOX_STATUSES
            if invalid:
                raise ValueError(f"invalid outbox statuses: {sorted(invalid)}")
            placeholders = ",".join("?" for _ in statuses)
            where = f" WHERE status IN ({placeholders})"
            params.extend(sorted(statuses))
        params.append(max(1, min(int(limit), 500)))
        rows = conn.execute(
            f"SELECT * FROM durable_outbox{where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [_decode_row(row) for row in rows]
    finally:
        conn.close()


def _transition(
    db_path: str | Path,
    item_id: str,
    *,
    from_statuses: set[str],
    to_status: str,
    now: datetime | None,
) -> dict[str, Any] | None:
    timestamp = (now or datetime.now()).isoformat(timespec="seconds")
    placeholders = ",".join("?" for _ in from_statuses)
    approved_at = timestamp if to_status == "approved" else None
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            f"UPDATE durable_outbox SET status=?, approved_at=COALESCE(?, approved_at), updated_at=? "
            f"WHERE id=? AND status IN ({placeholders})",
            (to_status, approved_at, timestamp, item_id, *sorted(from_statuses)),
        )
        conn.commit()
        return get_item(db_path, item_id) if cursor.rowcount else None
    finally:
        conn.close()


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _decode_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "kind": row["kind"],
        "idempotencyKey": row["idempotency_key"],
        "payload": json.loads(row["payload_json"]),
        "status": row["status"],
        "attempts": row["attempts"],
        "maxAttempts": row["max_attempts"],
        "nextAttemptAt": row["next_attempt_at"],
        "lastError": row["last_error"],
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "approvedAt": row["approved_at"],
        "sentAt": row["sent_at"],
    }
