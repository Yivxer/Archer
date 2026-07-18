"""Part 8.3 presence-state transitions.

The state machine is intentionally pure. Runtime callers may persist or emit
these transitions later, but ordinary activity can never bypass muted state.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.initiative_shadow import normalize_presence_state
from memory.store import DB_PATH


@dataclass(frozen=True)
class PresenceTransition:
    state: str
    reason: str
    changed: bool


def transition_presence(current_state: str, event: str) -> PresenceTransition:
    """Apply one normalized event to an engaged/idle/muted presence state."""
    current = normalize_presence_state(current_state)
    normalized_event = str(event or "").strip().lower()
    if normalized_event == "mute":
        return _result(current, "muted", "muted_by_user")
    if normalized_event == "unmute":
        next_state = "idle" if current == "muted" else current
        return _result(current, next_state, "unmuted_by_user" if current == "muted" else "already_unmuted")
    if current == "muted":
        return _result(current, current, "muted_requires_explicit_unmute")
    if normalized_event == "user_activity":
        return _result(current, "engaged", "activity_detected")
    if normalized_event == "idle_timeout":
        return _result(current, "idle", "idle_timeout")
    return _result(current, current, "ignored_event")


def init_table(db_path: Path = DB_PATH) -> None:
    from memory.part8_schema import init_presence_table

    init_presence_table(db_path)


def get_presence_state(db_path: Path = DB_PATH) -> str:
    init_table(db_path)
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT state FROM part8_presence_state WHERE id=1").fetchone()
    conn.close()
    return normalize_presence_state(row[0] if row else "idle")


def set_presence_state(
    db_path: Path = DB_PATH,
    state: str = "idle",
    *,
    now: datetime | None = None,
) -> PresenceTransition:
    current = get_presence_state(db_path)
    requested = normalize_presence_state(state)
    if requested == "muted":
        result = transition_presence(current, "mute")
    elif current == "muted":
        result = transition_presence(current, "unmute")
    else:
        result = _result(current, requested, "presence_set")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO part8_presence_state (id, state, updated_at) VALUES (1, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at",
        (result.state, (now or datetime.now()).isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()
    return result


def _result(current: str, next_state: str, reason: str) -> PresenceTransition:
    return PresenceTransition(state=next_state, reason=reason, changed=current != next_state)
