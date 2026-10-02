"""Part 8.7 validation report for shadow initiative observation.

The report only decides whether collected shadow data is ready for human review.
It never enables real delivery.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from core.feedback import POSITIVE_FEEDBACK, TOO_FREQUENT_FEEDBACK

DEFAULT_REQUIRED_DAYS = 7
DEFAULT_MAX_DAILY_AVERAGE = 3.0
DEFAULT_MIN_FEEDBACK = 3
DEFAULT_MIN_RECOGNITION_RATE = 0.7
DEFAULT_REQUIRED_DELIVERY_OBSERVATION_DAYS = 14


@dataclass(frozen=True)
class ShadowValidationReport:
    observed_days: int
    candidate_count: int
    daily_average: float
    feedback_count: int
    recognition_rate: float | None
    too_frequent_count: int
    ready_for_manual_review: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "observedDays": self.observed_days,
            "candidateCount": self.candidate_count,
            "dailyAverage": self.daily_average,
            "feedbackCount": self.feedback_count,
            "recognitionRate": self.recognition_rate,
            "tooFrequentCount": self.too_frequent_count,
            "readyForManualReview": self.ready_for_manual_review,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class LongTermFrequencyMetrics:
    daily_average: float
    max_daily_count: int


@dataclass(frozen=True)
class LongTermRelevanceMetrics:
    feedback_count: int
    recognition_rate: float | None
    too_frequent_rate: float | None


@dataclass(frozen=True)
class LongTermContinuityMetrics:
    thread_resume_count: int


@dataclass(frozen=True)
class LongTermValidationReport:
    observed_days: int
    candidate_count: int
    first_observed_at: datetime | None
    frequency: LongTermFrequencyMetrics
    relevance: LongTermRelevanceMetrics
    continuity: LongTermContinuityMetrics
    ready_for_delivery_review: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "observedDays": self.observed_days,
            "candidateCount": self.candidate_count,
            "firstObservedAt": _format_stamp(self.first_observed_at),
            "readyForDeliveryReview": self.ready_for_delivery_review,
            "reasons": list(self.reasons),
            "metrics": {
                "frequency": {
                    "dailyAverage": self.frequency.daily_average,
                    "maxDailyCount": self.frequency.max_daily_count,
                },
                "relevance": {
                    "feedbackCount": self.relevance.feedback_count,
                    "recognitionRate": self.relevance.recognition_rate,
                    "tooFrequentRate": self.relevance.too_frequent_rate,
                },
                "continuity": {
                    "threadResumeCount": self.continuity.thread_resume_count,
                },
            },
        }


@dataclass(frozen=True)
class DeliveryGateReport:
    can_enable_delivery: bool
    shadow_only: bool
    reasons: tuple[str, ...]
    required_observation_days: int
    explicit_opt_in_required: bool
    first_observed_at: datetime | None
    earliest_review_at: datetime | None
    remaining_observation_days: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "canEnableDelivery": self.can_enable_delivery,
            "shadowOnly": self.shadow_only,
            "reasons": list(self.reasons),
            "requirements": {
                "requiredObservationDays": self.required_observation_days,
                "explicitOptIn": self.explicit_opt_in_required,
                "manualReview": True,
            },
            "timeline": {
                "firstObservedAt": _format_stamp(self.first_observed_at),
                "earliestReviewAt": _format_stamp(self.earliest_review_at),
                "remainingObservationDays": self.remaining_observation_days,
            },
        }


def evaluate_shadow_validation(
    logs: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    required_days: int = DEFAULT_REQUIRED_DAYS,
    max_daily_average: float = DEFAULT_MAX_DAILY_AVERAGE,
    min_feedback: int = DEFAULT_MIN_FEEDBACK,
    min_recognition_rate: float = DEFAULT_MIN_RECOGNITION_RATE,
) -> ShadowValidationReport:
    """Measure real shadow candidates against a conservative review threshold."""
    candidates = [log for log in logs if _is_candidate(log)]
    stamps = sorted(stamp for log in candidates if (stamp := _parse_stamp(log.get("created_at"))))
    observed_days = _observed_days(stamps, now=now)
    candidate_count = len(candidates)
    daily_average = round(candidate_count / observed_days, 3) if observed_days else 0.0

    feedbacks = [str(log.get("feedback") or "").strip().lower() for log in candidates]
    known_feedback = [item for item in feedbacks if item in POSITIVE_FEEDBACK | {TOO_FREQUENT_FEEDBACK}]
    positive_count = sum(item in POSITIVE_FEEDBACK for item in known_feedback)
    recognition_rate = round(positive_count / len(known_feedback), 3) if known_feedback else None
    too_frequent_count = sum(item == TOO_FREQUENT_FEEDBACK for item in known_feedback)

    reasons: list[str] = []
    if observed_days < max(1, int(required_days)):
        reasons.append("insufficient_observation_days")
    if daily_average > max(0.0, float(max_daily_average)):
        reasons.append("daily_frequency_too_high")
    if len(known_feedback) < max(1, int(min_feedback)):
        reasons.append("insufficient_feedback")
    elif recognition_rate is not None and recognition_rate < max(0.0, float(min_recognition_rate)):
        reasons.append("recognition_rate_too_low")
    if too_frequent_count:
        reasons.append("too_frequent_feedback_present")

    return ShadowValidationReport(
        observed_days=observed_days,
        candidate_count=candidate_count,
        daily_average=daily_average,
        feedback_count=len(known_feedback),
        recognition_rate=recognition_rate,
        too_frequent_count=too_frequent_count,
        ready_for_manual_review=not reasons,
        reasons=tuple(reasons),
    )


def evaluate_delivery_gate(
    manual_report: Any,
    long_term_report: Any,
    *,
    explicit_opt_in: bool = False,
    required_observation_days: int = DEFAULT_REQUIRED_DELIVERY_OBSERVATION_DAYS,
) -> DeliveryGateReport:
    """Gate real initiative delivery behind review, observation, and opt-in."""
    required_days = max(1, int(required_observation_days))
    observed_days = int(getattr(long_term_report, "observed_days", 0) or 0)
    first_observed_at = getattr(long_term_report, "first_observed_at", None)
    first_observed_at = first_observed_at if isinstance(first_observed_at, datetime) else None
    earliest_review_at = first_observed_at + timedelta(days=required_days) if first_observed_at else None
    remaining_days = max(0, required_days - observed_days)
    reasons: list[str] = []
    if not bool(getattr(manual_report, "ready_for_manual_review", False)):
        reasons.append("manual_review_not_ready")
    if observed_days < required_days:
        reasons.append("insufficient_long_term_observation")
    if not explicit_opt_in:
        reasons.append("explicit_opt_in_required")
    can_enable = not reasons
    return DeliveryGateReport(
        can_enable_delivery=can_enable,
        shadow_only=not can_enable,
        reasons=tuple(reasons),
        required_observation_days=required_days,
        explicit_opt_in_required=True,
        first_observed_at=first_observed_at,
        earliest_review_at=earliest_review_at,
        remaining_observation_days=remaining_days,
    )


def evaluate_long_term_validation(
    logs: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> LongTermValidationReport:
    """Summarize shadow observation metrics without enabling delivery."""
    candidates = [log for log in logs if _is_candidate(log)]
    stamps = sorted(stamp for log in candidates if (stamp := _parse_stamp(log.get("created_at"))))
    observed_days = _observed_days(stamps, now=now or datetime.now())
    candidate_count = len(candidates)
    daily_average = round(candidate_count / observed_days, 3) if observed_days else 0.0

    counts_by_day: dict[str, int] = {}
    for stamp in stamps:
        day = stamp.date().isoformat()
        counts_by_day[day] = counts_by_day.get(day, 0) + 1

    feedbacks = [str(log.get("feedback") or "").strip().lower() for log in candidates]
    known_feedback = [item for item in feedbacks if item in POSITIVE_FEEDBACK | {TOO_FREQUENT_FEEDBACK}]
    positive_count = sum(item in POSITIVE_FEEDBACK for item in known_feedback)
    too_frequent_count = sum(item == TOO_FREQUENT_FEEDBACK for item in known_feedback)
    recognition_rate = round(positive_count / len(known_feedback), 3) if known_feedback else None
    too_frequent_rate = round(too_frequent_count / len(known_feedback), 3) if known_feedback else None

    return LongTermValidationReport(
        observed_days=observed_days,
        candidate_count=candidate_count,
        first_observed_at=stamps[0] if stamps else None,
        frequency=LongTermFrequencyMetrics(
            daily_average=daily_average,
            max_daily_count=max(counts_by_day.values(), default=0),
        ),
        relevance=LongTermRelevanceMetrics(
            feedback_count=len(known_feedback),
            recognition_rate=recognition_rate,
            too_frequent_rate=too_frequent_rate,
        ),
        continuity=LongTermContinuityMetrics(
            thread_resume_count=sum(1 for log in candidates if log.get("kind") == "thread_resume"),
        ),
        ready_for_delivery_review=False,
        reasons=("continue_shadow_observation",),
    )


def _is_candidate(log: dict[str, Any]) -> bool:
    return isinstance(log, dict) and log.get("event_type") != "initiative_feedback" and log.get("kind") != "global_throttle"


def _parse_stamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
        # Historical naive stamps were written in local time. Compare offset
        # stamps on that same clock, including observation-day boundaries.
        return stamp.astimezone().replace(tzinfo=None) if stamp.tzinfo else stamp
    except ValueError:
        return None


def _observed_days(stamps: list[datetime], *, now: datetime | None) -> int:
    if not stamps:
        return 0
    end = now.astimezone().replace(tzinfo=None) if now and now.tzinfo else now or max(stamps)
    return max(0, (end.date() - min(stamps).date()).days + 1)


def _format_stamp(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None
