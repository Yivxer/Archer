"""Chat delivery and reply controls for memory-grounded companion messages."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from core.initiative_shadow import get_shadow_log, list_shadow_logs
from core.thread_clue_lifecycle import thread_clue_allows_delivery

MIN_CONFIDENCE = 0.75
ALLOWED_RESPONSES = {"displayed", "continue", "correct", "suppress"}


def init_companion_receipts(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS companion_chat_receipts (
            initiative_log_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def pending_companion_message(db_path: Path) -> dict[str, Any] | None:
    """Return one delivered, reliable, not-yet-shown thread resume."""
    init_companion_receipts(db_path)
    conn = sqlite3.connect(db_path)
    seen = {
        int(row[0])
        for row in conn.execute("SELECT initiative_log_id FROM companion_chat_receipts").fetchall()
    }
    conn.close()
    for log in list_shadow_logs(db_path, limit=100):
        trace = log.get("decision_trace") or {}
        confidence = float(trace.get("confidence") or 0.0)
        source = str(trace.get("source") or "")
        if (
            int(log["id"]) not in seen
            and log.get("kind") == "thread_resume"
            and bool(log.get("delivered"))
            and source == "episodic"
            and confidence >= MIN_CONFIDENCE
            and trace.get("threadId") is not None
            and thread_clue_allows_delivery(db_path, log)
        ):
            return {
                "id": int(log["id"]),
                "message": str(log.get("message") or ""),
                "threadId": str(trace["threadId"]),
                "sessionId": str(trace.get("sessionId") or ""),
                "source": source,
                "confidence": confidence,
            }
    return None


def respond_to_companion(
    db_path: Path,
    log_id: int,
    response: str,
    *,
    detail: str = "",
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Record a direct chat response without silently changing long-term memory."""
    if response not in ALLOWED_RESPONSES:
        raise ValueError("unsupported companion response")
    log = get_shadow_log(db_path, int(log_id))
    if log is None or log.get("kind") != "thread_resume" or not log.get("delivered"):
        return None
    init_companion_receipts(db_path)
    stamp = (now or datetime.now()).isoformat(timespec="seconds")
    status = {
        "displayed": "displayed",
        "continue": "continued",
        "correct": "corrected",
        "suppress": "suppressed",
    }[response]
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO companion_chat_receipts (initiative_log_id, status, detail, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(initiative_log_id) DO UPDATE SET
            status=excluded.status, detail=excluded.detail, updated_at=excluded.updated_at
        """,
        (int(log_id), status, detail.strip()[:500], stamp),
    )
    if response == "suppress":
        trace = log.get("decision_trace") or {}
        thread_id = trace.get("threadId")
        if thread_id is not None:
            conn.execute(
                "UPDATE part8_threads SET status='suppressed' WHERE id=?",
                (int(thread_id),),
            )
    conn.commit()
    conn.close()
    return {
        "id": int(log_id),
        "status": status,
        "memoryResult": "corrected" if response == "correct" else "skipped",
    }
