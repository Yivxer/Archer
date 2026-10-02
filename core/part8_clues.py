"""Part 8.2 continuity clue extraction.

This layer turns obvious unfinished user threads into durable `part8_threads`
records. It is intentionally rule-based for the first slice: no LLM calls, no
prompt injection, and no proactive delivery.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from core.part8_threads import init_table, list_open_threads, record_unclosed_thread
from memory.store import DB_PATH

_CONTINUITY_MARKERS = ("继续", "后面", "之后", "再", "接着", "未完成", "做完", "测试")
_CLAUSE_SPLIT_MARKERS = ("，", "。", "；", ",", ";", "\n")


@dataclass(frozen=True)
class ThreadClue:
    topic: str
    prompt: str
    reason: str


def extract_unclosed_thread(messages: list[dict[str, Any]]) -> ThreadClue | None:
    user_texts = [
        _compact(str(message.get("content") or ""))
        for message in messages
        if isinstance(message, dict) and message.get("role") == "user"
    ]
    text = " ".join(item for item in user_texts if item)
    if not text or not any(marker in text for marker in _CONTINUITY_MARKERS):
        return None

    topic = _topic_from_text(text)
    if not topic:
        return None
    return ThreadClue(topic=topic, prompt=text[:500], reason="continuity_marker")


def record_thread_clues_from_messages(
    *,
    db_path: Path = DB_PATH,
    session_id: str = "",
    messages: list[dict[str, Any]],
    now: datetime | None = None,
) -> list[int]:
    clue = extract_unclosed_thread(messages)
    if not clue:
        return []
    init_table(db_path)
    if _recorded_clue_exists(db_path, clue.topic, clue.prompt):
        return []
    return [
        record_unclosed_thread(
            db_path=db_path,
            session_id=session_id,
            topic=clue.topic,
            prompt=clue.prompt,
            last_seen_at=now or datetime.now(),
        )
    ]


def _recorded_clue_exists(db_path: Path, topic: str, prompt: str) -> bool:
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT 1 FROM part8_threads WHERE topic=? AND prompt=? LIMIT 1",
        (topic, prompt),
    ).fetchone()
    conn.close()
    return row is not None


def _topic_from_text(text: str) -> str:
    first_clause = text
    for marker in _CLAUSE_SPLIT_MARKERS:
        if marker in first_clause:
            first_clause = first_clause.split(marker, 1)[0]
    first_clause = _compact(first_clause)
    if not first_clause:
        return ""
    if len(first_clause) <= 40:
        return first_clause
    return first_clause[:40].rstrip()


def _compact(value: str) -> str:
    return " ".join(str(value or "").split()).strip()
