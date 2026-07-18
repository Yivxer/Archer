"""Part 8.0 persistent thread cues.

This is the smallest durable layer for unclosed conversation threads. It does
not inject context or send messages; it only creates shadow initiative records
when an old open thread is worth reviewing.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from core.event_bus import INITIATIVE_DUE, SESSION_END, ArcherEvent, ArcherEventBus
from core.initiative_shadow import (
    DEFAULT_DAILY_LIMIT,
    list_shadow_logs,
    record_shadow_initiative,
    should_record_shadow_initiative,
)
from memory.store import DB_PATH


def init_table(db_path: Path = DB_PATH) -> None:
    from memory.part8_schema import init_part8_threads_table

    init_part8_threads_table(db_path)


def record_unclosed_thread(
    *,
    db_path: Path = DB_PATH,
    session_id: str = "",
    topic: str,
    prompt: str = "",
    last_seen_at: datetime | None = None,
) -> int:
    init_table(db_path)
    topic = topic.strip()
    if not topic:
        raise ValueError("topic is required")
    stamp = (last_seen_at or datetime.now()).isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        """
        INSERT INTO part8_threads
            (session_id, topic, prompt, status, last_seen_at, created_at)
        VALUES (?, ?, ?, 'open', ?, ?)
        """,
        (session_id.strip(), topic[:160], prompt.strip()[:500], stamp, stamp),
    )
    thread_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return thread_id


def list_open_threads(db_path: Path = DB_PATH, *, limit: int = 20) -> list[dict[str, Any]]:
    init_table(db_path)
    limit = max(1, min(int(limit), 100))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM part8_threads WHERE status='open' "
        "ORDER BY last_seen_at ASC, id ASC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def scan_thread_resume_candidates(
    *,
    db_path: Path = DB_PATH,
    now: datetime | None = None,
    min_gap_days: int = 1,
    daily_limit: int = DEFAULT_DAILY_LIMIT,
    presence_state: str = "idle",
) -> list[dict[str, Any]]:
    init_table(db_path)
    now = now or datetime.now()
    cutoff = (now - timedelta(days=max(0, int(min_gap_days)))).isoformat(timespec="seconds")
    decision = should_record_shadow_initiative(
        db_path,
        now=now,
        presence_state=presence_state,
        daily_limit=daily_limit,
    )
    if not decision.allowed:
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM part8_threads WHERE status='open' "
        "AND resume_logged_at IS NULL AND last_seen_at <= ? "
        "ORDER BY last_seen_at ASC, id ASC LIMIT 1",
        (cutoff,),
    ).fetchall()
    conn.close()
    created: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        log_id = record_shadow_initiative(
            db_path=db_path,
            event_type=INITIATIVE_DUE,
            kind="thread_resume",
            title=f"拾起未闭合话题：{item['topic']}",
            message=_resume_message(item),
            now=now,
            decision_trace={
                "reason": "stale_open_thread",
                "source": "episodic",
                "confidence": 0.9,
                "threadId": item["id"],
                "sessionId": item.get("session_id") or "",
                "lastSeenAt": item["last_seen_at"],
            },
        )
        _mark_resume_logged(db_path, item["id"], now)
        log = next((entry for entry in list_shadow_logs(db_path) if entry["id"] == log_id), None)
        if log:
            created.append(log)
    return created


def register_part8_thread_handlers(
    bus: ArcherEventBus,
    *,
    db_path: Path = DB_PATH,
) -> None:
    def _on_session_end(event: ArcherEvent) -> None:
        payload = event.payload if isinstance(event.payload, dict) else {}
        scan_thread_resume_candidates(
            db_path=db_path,
            now=event.created_at,
            presence_state=str(payload.get("presenceState") or "idle"),
        )

    bus.subscribe(SESSION_END, _on_session_end)


def _mark_resume_logged(db_path: Path, thread_id: int, now: datetime) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE part8_threads SET resume_logged_at=? WHERE id=?",
        (now.isoformat(timespec="seconds"), thread_id),
    )
    conn.commit()
    conn.close()


def _resume_message(thread: dict[str, Any]) -> str:
    topic = str(thread.get("topic") or "").strip()
    prompt = str(thread.get("prompt") or "").strip()
    if prompt:
        return f"上次还留着一个话题：{topic}。当时的线索是：{prompt}"
    return f"上次还留着一个话题：{topic}。"
