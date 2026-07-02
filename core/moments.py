"""Part 8.1 moment sensing rules.

The moment layer classifies time windows for later initiative scoring. It only
returns signals; it never sends messages or changes runtime state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.rhythm import RhythmProfile, hour_slot

REST_HOURS = set(range(0, 8)) | {23}
WORK_HOURS = set(range(9, 18))
DEEP_CONVERSATION_HOURS = set(range(19, 23))


@dataclass(frozen=True)
class MomentSignal:
    kind: str
    reason: str
    score: float


def detect_moment(stamp: datetime, *, rhythm: RhythmProfile | None = None) -> MomentSignal:
    if stamp.hour in REST_HOURS:
        return MomentSignal(kind="rest", reason="quiet_hours", score=1.0)

    rhythm_score = _rhythm_peak_score(stamp, rhythm)
    if stamp.hour in DEEP_CONVERSATION_HOURS and rhythm_score > 0:
        return MomentSignal(kind="deep_conversation", reason="rhythm_peak", score=rhythm_score)

    if stamp.weekday() < 5 and stamp.hour in WORK_HOURS:
        return MomentSignal(kind="work", reason="weekday_daytime", score=0.8)

    return MomentSignal(kind="open", reason="unclassified", score=0.3)


def _rhythm_peak_score(stamp: datetime, rhythm: RhythmProfile | None) -> float:
    if not rhythm or rhythm.status != "modeled" or not rhythm.hourly_weights:
        return 0.0
    weights = rhythm.hourly_weights
    slot_weight = weights[hour_slot(stamp)]
    peak = max(weights)
    if peak <= 0 or slot_weight < peak:
        return 0.0
    return round(min(1.0, 0.5 + rhythm.confidence), 3)
