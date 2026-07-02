"""Part 8 initiative arbitration boundary.

This module owns cross-layer speaking rules. Current callers still run in
shadow mode; the boundary keeps delivery decisions explainable and testable.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArbitrationDecision:
    allowed: bool
    reason: str
    effective_daily_limit: int


def evaluate_shadow_recording(
    *,
    requested_presence_state: str,
    persisted_presence_state: str,
    today_count: int,
    daily_limit: int,
    throttled: bool,
    throttled_limit: int,
) -> ArbitrationDecision:
    """Decide whether a shadow initiative may be recorded now."""
    requested = _normalize_presence_state(requested_presence_state)
    persisted = _normalize_presence_state(persisted_presence_state)
    if requested == "muted" or persisted == "muted":
        return ArbitrationDecision(False, "presence_muted", 0)

    effective_limit = max(0, int(daily_limit))
    if throttled:
        effective_limit = min(effective_limit, max(0, int(throttled_limit)))
    if int(today_count) >= effective_limit:
        reason = "global_throttle_active" if throttled else "daily_limit_reached"
        return ArbitrationDecision(False, reason, effective_limit)
    return ArbitrationDecision(True, "within_daily_limit", effective_limit)


def _normalize_presence_state(value: str | None) -> str:
    state = str(value or "").strip().lower()
    return state if state in {"engaged", "idle", "muted"} else "idle"
