"""Pure time-rhythm value types."""
from __future__ import annotations

from dataclasses import dataclass


HOURS_PER_DAY = 24
DAYS_PER_WEEK = 7
HOURS_PER_WEEK = HOURS_PER_DAY * DAYS_PER_WEEK


@dataclass(frozen=True)
class RhythmProfile:
    status: str
    hourly_weights: list[float]
    observed_days: int
    event_count: int
    confidence: float
