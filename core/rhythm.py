"""Part 8.1 time-rhythm modeling.

This module keeps the first time layer deterministic and side-effect free:
it models likely active hours from observed activity timestamps, without LLMs
or proactive delivery.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.session import SESSIONS_DIR

HOURS_PER_DAY = 24
DAYS_PER_WEEK = 7
HOURS_PER_WEEK = HOURS_PER_DAY * DAYS_PER_WEEK
MIN_HISTORY_DAYS = 14
SMOOTHING = 1.0


@dataclass(frozen=True)
class RhythmProfile:
    status: str
    hourly_weights: list[float]
    observed_days: int
    event_count: int
    confidence: float


def build_hourly_rhythm(
    events: list[datetime],
    *,
    now: datetime | None = None,
    min_history_days: int = MIN_HISTORY_DAYS,
) -> RhythmProfile:
    stamps = sorted(_valid_datetimes(events))
    observed_days = _observed_days(stamps, now=now)
    if observed_days < int(min_history_days):
        return RhythmProfile(
            status="cold_start",
            hourly_weights=_uniform_weights(),
            observed_days=observed_days,
            event_count=len(stamps),
            confidence=0.0,
        )

    counts = [SMOOTHING] * HOURS_PER_WEEK
    for stamp in stamps:
        counts[hour_slot(stamp)] += 1.0
    total = sum(counts)
    weights = [value / total for value in counts]
    return RhythmProfile(
        status="modeled",
        hourly_weights=weights,
        observed_days=observed_days,
        event_count=len(stamps),
        confidence=_confidence(event_count=len(stamps), observed_days=observed_days),
    )


def build_session_rhythm(
    sessions_dir: Path = SESSIONS_DIR,
    *,
    now: datetime | None = None,
) -> RhythmProfile:
    return build_hourly_rhythm(load_session_activity_stamps(sessions_dir), now=now)


def load_session_activity_stamps(sessions_dir: Path = SESSIONS_DIR) -> list[datetime]:
    if not sessions_dir.exists():
        return []
    stamps: list[datetime] = []
    for path in sessions_dir.glob("*.json"):
        stamp = _stamp_from_session_filename(path)
        if stamp:
            stamps.append(stamp)
    return sorted(stamps)


def hour_slot(stamp: datetime) -> int:
    return stamp.weekday() * HOURS_PER_DAY + stamp.hour


def _uniform_weights() -> list[float]:
    return [1 / HOURS_PER_WEEK] * HOURS_PER_WEEK


def _valid_datetimes(events: list[datetime]) -> list[datetime]:
    return [event for event in events if isinstance(event, datetime)]


def _observed_days(stamps: list[datetime], *, now: datetime | None) -> int:
    if not stamps:
        return 0
    end = now or max(stamps)
    first = min(stamps)
    return max(0, (end.date() - first.date()).days)


def _confidence(*, event_count: int, observed_days: int) -> float:
    event_factor = min(1.0, event_count / 40)
    span_factor = min(1.0, observed_days / 28)
    return round(event_factor * span_factor, 3)


def _stamp_from_session_filename(path: Path) -> datetime | None:
    try:
        return datetime.strptime(path.stem, "%Y%m%d_%H%M%S")
    except ValueError:
        return None
