"""Part 8.3 explainable opportunity detection.

The opportunity layer produces candidates for later threshold evaluation. It
does not persist, inject, or deliver an initiative.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.initiative_shadow import normalize_presence_state

DEFAULT_STALE_THREAD_DAYS = 7


@dataclass(frozen=True)
class OpportunityCandidate:
    kind: str
    reason: str
    score: float
    trace: dict[str, Any]


def detect_opportunities(
    *,
    previous_presence_state: str,
    current_presence_state: str,
    open_threads: list[dict[str, Any]],
    now: datetime | None = None,
    stale_thread_days: int = DEFAULT_STALE_THREAD_DAYS,
) -> list[OpportunityCandidate]:
    """Return a compact, ranked set of current initiative opportunities."""
    now = now or datetime.now()
    candidates: list[OpportunityCandidate] = []
    previous = normalize_presence_state(previous_presence_state)
    current = normalize_presence_state(current_presence_state)
    if previous != "engaged" and current == "engaged":
        candidates.append(
            OpportunityCandidate(
                kind="presence_return",
                reason="presence_became_engaged",
                score=0.65,
                trace={"previousPresenceState": previous, "currentPresenceState": current},
            )
        )

    stale = _oldest_stale_thread(open_threads, now=now, min_days=stale_thread_days)
    if stale:
        candidates.append(stale)
    return sorted(candidates, key=lambda item: item.score, reverse=True)


def _oldest_stale_thread(
    threads: list[dict[str, Any]],
    *,
    now: datetime,
    min_days: int,
) -> OpportunityCandidate | None:
    selected: tuple[dict[str, Any], int] | None = None
    for thread in threads:
        if str(thread.get("status") or "open") != "open":
            continue
        stamp = _parse_stamp(thread.get("last_seen_at"))
        if not stamp:
            continue
        days_untouched = max(0, (now.date() - stamp.date()).days)
        if days_untouched < max(1, int(min_days)):
            continue
        if selected is None or days_untouched > selected[1]:
            selected = (thread, days_untouched)
    if not selected:
        return None

    thread, days_untouched = selected
    return OpportunityCandidate(
        kind="stale_thread",
        reason="thread_untouched_for_days",
        score=0.8,
        trace={
            "threadId": thread.get("id"),
            "topic": str(thread.get("topic") or ""),
            "lastSeenAt": str(thread.get("last_seen_at") or ""),
            "daysUntouched": days_untouched,
        },
    )


def _parse_stamp(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
