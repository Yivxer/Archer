"""Transactional episodic state for conversation threads."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.paths import memory_db_path


def init_thread_context_schema(db_path: str | Path) -> None:
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversation_thread_state (
                thread_id       TEXT PRIMARY KEY,
                capsule_json    TEXT NOT NULL,
                summary_version INTEGER NOT NULL DEFAULT 1,
                message_count   INTEGER NOT NULL DEFAULT 0,
                compacted_count INTEGER NOT NULL DEFAULT 0,
                environment     TEXT NOT NULL DEFAULT 'user',
                updated_at      TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversation_thread_sessions (
                thread_id   TEXT NOT NULL,
                session_id  TEXT NOT NULL,
                position    INTEGER NOT NULL DEFAULT 0,
                environment TEXT NOT NULL DEFAULT 'user',
                created_at  TEXT NOT NULL,
                PRIMARY KEY (thread_id, session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_thread_state_updated
                ON conversation_thread_state(environment, updated_at DESC);
        """)
        conn.commit()
    finally:
        conn.close()


def build_context_capsule(messages: list[dict]) -> dict[str, Any]:
    users = [_content(item) for item in messages if item.get("role") == "user" and _content(item)]
    assistants = [
        _content(item) for item in messages
        if item.get("role") == "assistant" and _content(item)
    ]
    corrections = [text for text in users if _contains_any(text, ("不对", "不是这个", "改成", "纠正", "记错"))]
    pending = [text for text in users if _contains_any(text, ("接下来", "还要", "待", "继续", "下一步"))]
    return {
        "goal": _compact(users[0] if users else "", 240),
        "decisions": [_compact(text, 240) for text in assistants[-3:]],
        "pending": [_compact(text, 240) for text in pending[-3:]],
        "corrections": [_compact(text, 240) for text in corrections[-3:]],
        "lastStop": _compact(users[-1] if users else (assistants[-1] if assistants else ""), 320),
    }


def update_thread_context(
    thread_id: str,
    messages: list[dict],
    *,
    db_path: str | Path | None = None,
    environment: str = "user",
) -> dict[str, Any]:
    path = Path(db_path).expanduser() if db_path is not None else memory_db_path()
    init_thread_context_schema(path)
    capsule = build_context_capsule(messages)
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    conn = sqlite3.connect(path)
    try:
        previous = conn.execute(
            "SELECT summary_version, compacted_count FROM conversation_thread_state WHERE thread_id=?",
            (thread_id,),
        ).fetchone()
        previous_version = int(previous[0]) if previous else 0
        compacted_count = int(previous[1]) if previous else 0
        should_advance = not previous or len(messages) <= 36 or len(messages) - compacted_count >= 12
        version = previous_version + 1 if should_advance else previous_version
        next_compacted_count = len(messages) if should_advance else compacted_count
        conn.execute(
            """INSERT INTO conversation_thread_state(
                   thread_id, capsule_json, summary_version, message_count, compacted_count, environment, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(thread_id) DO UPDATE SET
                   capsule_json=excluded.capsule_json,
                   summary_version=excluded.summary_version,
                   message_count=excluded.message_count,
                   compacted_count=excluded.compacted_count,
                   environment=excluded.environment,
                   updated_at=excluded.updated_at""",
            (thread_id, json.dumps(capsule, ensure_ascii=False), version, len(messages), next_compacted_count, environment, now),
        )
        conn.commit()
    finally:
        conn.close()
    return {"contextState": capsule, "summaryVersion": version, "lastStop": capsule["lastStop"]}


def register_thread_session(
    thread_id: str,
    session_id: str,
    *,
    db_path: str | Path | None = None,
    environment: str = "user",
) -> None:
    if not session_id:
        return
    path = Path(db_path).expanduser() if db_path is not None else memory_db_path()
    init_thread_context_schema(path)
    conn = sqlite3.connect(path)
    try:
        position = int(conn.execute(
            "SELECT COUNT(*) FROM conversation_thread_sessions WHERE thread_id=?",
            (thread_id,),
        ).fetchone()[0])
        conn.execute(
            """INSERT OR IGNORE INTO conversation_thread_sessions(
                   thread_id, session_id, position, environment, created_at
               ) VALUES (?, ?, ?, ?, ?)""",
            (thread_id, session_id, position, environment, datetime.now(timezone.utc).isoformat(timespec="microseconds")),
        )
        conn.commit()
    finally:
        conn.close()


def unregister_thread_session(session_id: str, *, db_path: str | Path | None = None) -> None:
    path = Path(db_path).expanduser() if db_path is not None else memory_db_path()
    init_thread_context_schema(path)
    conn = sqlite3.connect(path)
    try:
        conn.execute("DELETE FROM conversation_thread_sessions WHERE session_id=?", (session_id,))
        conn.commit()
    finally:
        conn.close()


def get_thread_context(thread_id: str, *, db_path: str | Path | None = None) -> dict[str, Any] | None:
    path = Path(db_path).expanduser() if db_path is not None else memory_db_path()
    init_thread_context_schema(path)
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            """SELECT capsule_json, summary_version FROM conversation_thread_state
               WHERE thread_id=? AND environment='user'""",
            (thread_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    try:
        capsule = json.loads(str(row[0]))
    except json.JSONDecodeError:
        return None
    return {"contextState": capsule, "summaryVersion": int(row[1]), "lastStop": capsule.get("lastStop", "")}


def latest_thread_context(*, db_path: str | Path | None = None) -> dict[str, Any] | None:
    path = Path(db_path).expanduser() if db_path is not None else memory_db_path()
    init_thread_context_schema(path)
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            """SELECT thread_id, capsule_json, summary_version
               FROM conversation_thread_state WHERE environment='user'
               ORDER BY updated_at DESC LIMIT 1"""
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    capsule = json.loads(str(row[1]))
    return {
        "threadId": str(row[0]),
        "contextState": capsule,
        "summaryVersion": int(row[2]),
        "lastStop": capsule.get("lastStop", ""),
    }


def format_context_capsule(state: dict[str, Any]) -> str:
    capsule = state.get("contextState", state)
    version = int(state.get("summaryVersion") or 0)
    lines = [f"[线程情境胶囊] version={version}" if version else "[线程情境胶囊]"]
    labels = (("goal", "目标"), ("decisions", "已确认结论"), ("pending", "未完成"), ("corrections", "用户纠正"), ("lastStop", "最近停点"))
    for key, label in labels:
        value = capsule.get(key)
        if isinstance(value, list):
            value = "；".join(str(item) for item in value if item)
        if value:
            lines.append(f"{label}：{value}")
    return "\n".join(lines)


def _content(item: dict) -> str:
    return str(item.get("content", "") or "").strip()


def _contains_any(value: str, markers: tuple[str, ...]) -> bool:
    return any(marker in value for marker in markers)


def _compact(value: str, limit: int) -> str:
    return " ".join(value.split())[:limit]
