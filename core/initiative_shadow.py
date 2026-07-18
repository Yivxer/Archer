"""Part 8.0 shadow initiative log and minimal arbiter."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from core.arbitrator import evaluate_shadow_recording
from memory.store import DB_PATH

DEFAULT_DAILY_LIMIT = 3
THROTTLED_DAILY_LIMIT = 1
THROTTLE_HOURS = 48
VALID_PRESENCE_STATES = {"engaged", "idle", "muted"}


@dataclass(frozen=True)
class InitiativeDecision:
    allowed: bool
    reason: str


def init_table(db_path: Path = DB_PATH) -> None:
    from memory.part8_schema import init_initiative_shadow_table

    init_initiative_shadow_table(db_path)


def should_record_shadow_initiative(
    db_path: Path = DB_PATH,
    *,
    now: datetime | None = None,
    presence_state: str = "idle",
    daily_limit: int = DEFAULT_DAILY_LIMIT,
) -> InitiativeDecision:
    throttled = is_global_throttle_active(db_path, now=now)
    decision = evaluate_shadow_recording(
        requested_presence_state=presence_state,
        persisted_presence_state=_persisted_presence_state(db_path),
        today_count=count_today(db_path, now=now),
        daily_limit=daily_limit,
        throttled=throttled,
        throttled_limit=THROTTLED_DAILY_LIMIT,
    )
    return InitiativeDecision(decision.allowed, decision.reason)


def normalize_presence_state(value: str | None) -> str:
    state = str(value or "").strip().lower()
    return state if state in VALID_PRESENCE_STATES else "idle"


def _persisted_presence_state(db_path: Path) -> str:
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT state FROM part8_presence_state WHERE id=1").fetchone()
        conn.close()
    except sqlite3.Error:
        return "idle"
    return normalize_presence_state(row[0] if row else "idle")


def record_shadow_initiative(
    *,
    db_path: Path = DB_PATH,
    event_type: str,
    kind: str,
    title: str,
    message: str,
    now: datetime | None = None,
    decision_trace: dict[str, Any] | None = None,
    delivered: bool = False,
) -> int:
    init_table(db_path)
    stamp = (now or datetime.now()).isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        """
        INSERT INTO initiative_sent_log
            (event_type, kind, title, message, delivered, decision_trace_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_type,
            kind,
            title,
            message,
            1 if delivered else 0,
            json.dumps(decision_trace or {}, ensure_ascii=False, sort_keys=True),
            stamp,
        ),
    )
    assert cur.lastrowid is not None, "INSERT 未返回 lastrowid"
    log_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return log_id


def record_shadow_feedback(
    *,
    db_path: Path = DB_PATH,
    log_id: int,
    feedback: str,
    now: datetime | None = None,
) -> bool:
    init_table(db_path)
    stamp = (now or datetime.now()).isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "UPDATE initiative_sent_log SET feedback=? WHERE id=?",
        (feedback.strip(), log_id),
    )
    if feedback.strip() == "too_frequent":
        conn.execute(
            """
            INSERT INTO initiative_sent_log
                (event_type, kind, title, message, delivered, decision_trace_json, created_at, feedback)
            VALUES ('initiative_feedback', 'global_throttle', '全局降频', '用户反馈主动消息太频繁', 0, ?, ?, ?)
            """,
            (
                json.dumps({"reason": "too_frequent", "sourceLogId": log_id}, ensure_ascii=False, sort_keys=True),
                stamp,
                "too_frequent",
            ),
        )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def is_global_throttle_active(db_path: Path = DB_PATH, *, now: datetime | None = None) -> bool:
    init_table(db_path)
    now = now or datetime.now()
    cutoff = (now - timedelta(hours=THROTTLE_HOURS)).isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT 1 FROM initiative_sent_log WHERE feedback='too_frequent' AND created_at >= ? LIMIT 1",
        (cutoff,),
    ).fetchone()
    conn.close()
    return row is not None


def count_today(db_path: Path = DB_PATH, *, now: datetime | None = None) -> int:
    init_table(db_path)
    date_prefix = (now or datetime.now()).date().isoformat()
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT COUNT(*) FROM initiative_sent_log WHERE created_at >= ? AND created_at < ?",
        (f"{date_prefix}T00:00:00", f"{date_prefix}T23:59:59"),
    ).fetchone()
    conn.close()
    return int(row[0] if row else 0)


def list_shadow_logs(db_path: Path = DB_PATH, *, limit: int = 20) -> list[dict[str, Any]]:
    init_table(db_path)
    limit = max(1, min(int(limit), 100))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM initiative_sent_log ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [_format_log(dict(row)) for row in rows]


def get_shadow_log(db_path: Path, log_id: int) -> dict[str, Any] | None:
    init_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM initiative_sent_log WHERE id=?", (int(log_id),)).fetchone()
    conn.close()
    return _format_log(dict(row)) if row else None


def mark_initiative_delivered(
    db_path: Path,
    log_id: int,
    *,
    delivery_trace: dict[str, Any],
) -> dict[str, Any] | None:
    """Idempotently expose one initiative in Archer's in-app review surfaces."""
    current = get_shadow_log(db_path, log_id)
    if current is None:
        return None
    trace = dict(current.get("decision_trace") or {})
    trace["delivery"] = dict(delivery_trace)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE initiative_sent_log SET delivered=1, decision_trace_json=? WHERE id=?",
        (json.dumps(trace, ensure_ascii=False, sort_keys=True), int(log_id)),
    )
    conn.commit()
    conn.close()
    return get_shadow_log(db_path, log_id)


def count_delivered_today(
    db_path: Path,
    *,
    kind: str,
    now: datetime | None = None,
) -> int:
    init_table(db_path)
    date_prefix = (now or datetime.now()).date().isoformat()
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT COUNT(*) FROM initiative_sent_log "
        "WHERE delivered=1 AND kind=? AND created_at >= ? AND created_at < ?",
        (kind, f"{date_prefix}T00:00:00", f"{date_prefix}T23:59:59"),
    ).fetchone()
    conn.close()
    return int(row[0] if row else 0)


def _format_log(row: dict[str, Any]) -> dict[str, Any]:
    try:
        trace = json.loads(row.get("decision_trace_json") or "{}")
    except Exception:
        trace = {}
    return {
        "id": row["id"],
        "event_type": row["event_type"],
        "kind": row["kind"],
        "title": row.get("title") or "",
        "message": row["message"],
        "delivered": bool(row.get("delivered", 0)),
        "decision_trace": trace,
        "created_at": row["created_at"],
        "feedback": row.get("feedback") or "",
        "archived_at": row.get("archived_at"),
    }
