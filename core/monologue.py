"""Part 8.2 internal monologue shadow layer.

The monologue layer records compact internal thoughts as raw material for later
initiative and creative layers. It never delivers messages to the user.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from memory.store import DB_PATH

DEFAULT_DAILY_LLM_LIMIT = 3


@dataclass(frozen=True)
class MonologueEntry:
    id: int
    source: str
    thought: str
    trigger: str
    delivered: bool
    trace: dict[str, Any]
    created_at: str


def init_table(db_path: Path = DB_PATH) -> None:
    from memory.part8_schema import init_monologue_table

    init_monologue_table(db_path)


def record_monologue(
    *,
    db_path: Path = DB_PATH,
    source: str,
    thought: str,
    trigger: str = "",
    now: datetime | None = None,
    trace: dict[str, Any] | None = None,
    delivered: bool = False,
) -> int:
    init_table(db_path)
    clean_thought = _compact_text(thought)
    if not clean_thought:
        raise ValueError("thought is required")
    stamp = (now or datetime.now()).isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        """
        INSERT INTO part8_monologues
            (source, thought, trigger, delivered, trace_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            source.strip() or "rules",
            clean_thought,
            trigger.strip(),
            1 if delivered else 0,
            json.dumps(trace or {}, ensure_ascii=False, sort_keys=True),
            stamp,
        ),
    )
    monologue_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return monologue_id


def generate_monologue(
    *,
    db_path: Path = DB_PATH,
    messages: list[dict[str, Any]],
    now: datetime | None = None,
    daily_llm_limit: int = DEFAULT_DAILY_LLM_LIMIT,
    llm_generator: Callable[[list[dict[str, Any]]], str] | None = None,
    trigger: str = "session_end",
) -> MonologueEntry:
    now = now or datetime.now()
    if llm_generator and _llm_calls_today(db_path, now=now) < max(0, int(daily_llm_limit)):
        thought = _compact_text(llm_generator(messages))
        if thought:
            monologue_id = record_monologue(
                db_path=db_path,
                source="llm",
                thought=thought,
                trigger=trigger,
                now=now,
                trace={"reason": "llm_budget_available"},
            )
            return _get_monologue(db_path, monologue_id)

    reason = "daily_llm_budget_exhausted" if llm_generator else "rules_only"
    thought = _rule_monologue(messages)
    monologue_id = record_monologue(
        db_path=db_path,
        source="rules",
        thought=thought,
        trigger=trigger,
        now=now,
        trace={"reason": reason},
    )
    return _get_monologue(db_path, monologue_id)


def list_monologues(db_path: Path = DB_PATH, *, limit: int = 20) -> list[dict[str, Any]]:
    init_table(db_path)
    limit = max(1, min(int(limit), 100))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM part8_monologues ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [_format_monologue(dict(row)) for row in rows]


def _get_monologue(db_path: Path, monologue_id: int) -> MonologueEntry:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM part8_monologues WHERE id=?", (monologue_id,)).fetchone()
    conn.close()
    if row is None:
        raise LookupError(f"monologue not found: {monologue_id}")
    data = _format_monologue(dict(row))
    return MonologueEntry(**data)


def _llm_calls_today(db_path: Path, *, now: datetime) -> int:
    init_table(db_path)
    date_prefix = now.date().isoformat()
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT COUNT(*) FROM part8_monologues "
        "WHERE source='llm' AND created_at >= ? AND created_at < ?",
        (f"{date_prefix}T00:00:00", f"{date_prefix}T23:59:59"),
    ).fetchone()
    conn.close()
    return int(row[0] if row else 0)


def _format_monologue(row: dict[str, Any]) -> dict[str, Any]:
    try:
        trace = json.loads(row.get("trace_json") or "{}")
    except Exception:
        trace = {}
    return {
        "id": int(row["id"]),
        "source": row.get("source") or "rules",
        "thought": row.get("thought") or "",
        "trigger": row.get("trigger") or "",
        "delivered": bool(row.get("delivered", 0)),
        "trace": trace,
        "created_at": row.get("created_at") or "",
    }


def _rule_monologue(messages: list[dict[str, Any]]) -> str:
    user_texts = [
        _compact_text(str(message.get("content") or ""))
        for message in messages
        if isinstance(message, dict) and message.get("role") == "user"
    ]
    text = " ".join(item for item in user_texts if item)
    if not text:
        return "这次会话没有明显用户线索，保持静默观察。"
    return f"用户留下的主要线索：{text[:180]}"


def _compact_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip()
