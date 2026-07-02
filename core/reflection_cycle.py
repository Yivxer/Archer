"""Part 8.1 periodic reflection cycle signals."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from memory.store import DB_PATH

DEFAULT_CYCLE_DAYS = 7


@dataclass(frozen=True)
class ReflectionCycleSignal:
    due: bool
    cycle: str
    reason: str
    days_since_last: int | None


def evaluate_reflection_cycle(
    reflection_stamps: list[datetime],
    *,
    now: datetime | None = None,
    cycle_days: int = DEFAULT_CYCLE_DAYS,
) -> ReflectionCycleSignal:
    now = now or datetime.now()
    stamps = sorted(stamp for stamp in reflection_stamps if isinstance(stamp, datetime))
    if not stamps:
        return ReflectionCycleSignal(
            due=True,
            cycle="weekly",
            reason="no_previous_reflection",
            days_since_last=None,
        )

    days_since_last = max(0, (now.date() - stamps[-1].date()).days)
    if days_since_last >= max(1, int(cycle_days)):
        return ReflectionCycleSignal(
            due=True,
            cycle="weekly",
            reason="cycle_due",
            days_since_last=days_since_last,
        )
    return ReflectionCycleSignal(
        due=False,
        cycle="weekly",
        reason="within_cycle",
        days_since_last=days_since_last,
    )


def load_reflection_stamps(db_path: Path = DB_PATH) -> list[datetime]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT created_at FROM memories
            WHERE type IN ('reflection', 'reflection_anchor')
            ORDER BY created_at ASC
            """
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    stamps: list[datetime] = []
    for (created_at,) in rows:
        stamp = _parse_stamp(created_at)
        if stamp:
            stamps.append(stamp)
    return stamps


def current_reflection_cycle(
    *,
    db_path: Path = DB_PATH,
    now: datetime | None = None,
) -> ReflectionCycleSignal:
    return evaluate_reflection_cycle(load_reflection_stamps(db_path), now=now)


def _parse_stamp(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
