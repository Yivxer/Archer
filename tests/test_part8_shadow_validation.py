from datetime import UTC, datetime, timedelta, timezone

import pytest


def _candidate(day: int, *, feedback: str = "") -> dict:
    return {
        "event_type": "initiative_due",
        "kind": "thread_resume",
        "created_at": (datetime(2026, 6, 1, 9, 0, 0) + timedelta(days=day)).isoformat(),
        "feedback": feedback,
    }


@pytest.mark.parametrize("report_name", ["evaluate_shadow_validation", "evaluate_long_term_validation"])
def test_shadow_reports_accept_mixed_timestamp_formats(report_name: str) -> None:
    from core import shadow_validation

    logs = [_candidate(0), _candidate(1), _candidate(2)]
    stamp = datetime.fromisoformat(logs[1]["created_at"])
    logs[1]["created_at"] = stamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
    report = getattr(shadow_validation, report_name)(logs, now=datetime(2026, 6, 3, 18))

    assert report.observed_days == 3
    assert report.candidate_count == 3
    feedback_count = report.feedback_count if report_name == "evaluate_shadow_validation" else report.relevance.feedback_count
    assert feedback_count == 0


@pytest.mark.parametrize("report_name", ["evaluate_shadow_validation", "evaluate_long_term_validation"])
def test_shadow_observation_days_use_local_dates_for_aware_clock(report_name: str) -> None:
    from core import shadow_validation

    local_now = datetime(2026, 6, 2, 0, 15)
    other_zone_now = local_now.astimezone(timezone(timedelta(hours=-12)))
    report = getattr(shadow_validation, report_name)([_candidate(0)], now=other_zone_now)

    assert report.observed_days == 2


def test_shadow_validation_is_ready_for_manual_review_after_stable_week():
    from core.shadow_validation import evaluate_shadow_validation

    report = evaluate_shadow_validation(
        [_candidate(day, feedback="acknowledged" if day < 3 else "") for day in range(7)],
        now=datetime(2026, 6, 7, 18, 0, 0),
    )

    assert report.observed_days == 7
    assert report.candidate_count == 7
    assert report.daily_average == 1.0
    assert report.feedback_count == 3
    assert report.recognition_rate == 1.0
    assert report.ready_for_manual_review is True
    assert report.reasons == ()


def test_shadow_validation_excludes_system_feedback_records_from_candidate_metrics():
    from core.shadow_validation import evaluate_shadow_validation

    report = evaluate_shadow_validation(
        [
            _candidate(0, feedback="acknowledged"),
            _candidate(1, feedback="acknowledged"),
            _candidate(2, feedback="acknowledged"),
            _candidate(3),
            _candidate(4),
            _candidate(5),
            _candidate(6),
            {
                "event_type": "initiative_feedback",
                "kind": "global_throttle",
                "created_at": datetime(2026, 6, 7, 10, 0, 0).isoformat(),
                "feedback": "too_frequent",
            },
        ],
        now=datetime(2026, 6, 7, 18, 0, 0),
    )

    assert report.candidate_count == 7
    assert report.feedback_count == 3
    assert report.too_frequent_count == 0
    assert report.ready_for_manual_review is True


def test_shadow_validation_holds_review_when_feedback_or_frequency_is_insufficient():
    from core.shadow_validation import evaluate_shadow_validation

    report = evaluate_shadow_validation(
        [_candidate(0), _candidate(0), _candidate(0), _candidate(1), _candidate(2)],
        now=datetime(2026, 6, 7, 18, 0, 0),
    )

    assert report.ready_for_manual_review is False
    assert report.daily_average == 0.714
    assert report.reasons == ("insufficient_feedback",)


def test_shadow_validation_requires_the_planned_seventy_percent_recognition_rate():
    from core.shadow_validation import evaluate_shadow_validation

    report = evaluate_shadow_validation(
        [
            _candidate(0, feedback="acknowledged"),
            _candidate(1, feedback="acknowledged"),
            _candidate(2, feedback="too_frequent"),
            _candidate(3),
            _candidate(4),
            _candidate(5),
            _candidate(6),
        ],
        now=datetime(2026, 6, 7, 18, 0, 0),
    )

    assert report.recognition_rate == 0.667
    assert "recognition_rate_too_low" in report.reasons


def test_long_term_validation_summarizes_frequency_relevance_and_observation_windows():
    from core.shadow_validation import evaluate_long_term_validation

    logs = [
        _candidate(0, feedback="acknowledged"),
        _candidate(1, feedback="acknowledged"),
        _candidate(2, feedback="too_frequent"),
        _candidate(3),
        _candidate(4, feedback="acknowledged"),
        _candidate(5),
        _candidate(6),
        _candidate(7, feedback="acknowledged"),
        {
            "event_type": "initiative_feedback",
            "kind": "global_throttle",
            "created_at": datetime(2026, 6, 8, 10, 0, 0).isoformat(),
            "feedback": "too_frequent",
        },
    ]

    report = evaluate_long_term_validation(
        logs,
        now=datetime(2026, 6, 14, 18, 0, 0),
    )

    assert report.observed_days == 14
    assert report.frequency.daily_average == 0.571
    assert report.frequency.max_daily_count == 1
    assert report.relevance.recognition_rate == 0.8
    assert report.relevance.too_frequent_rate == 0.2
    assert report.continuity.thread_resume_count == 8
    assert report.ready_for_delivery_review is False
    assert report.reasons == ("continue_shadow_observation",)
    assert report.to_dict()["metrics"]["relevance"]["recognitionRate"] == 0.8


def test_delivery_gate_requires_observation_window_manual_review_and_explicit_opt_in():
    from core.shadow_validation import evaluate_delivery_gate

    manual_report = type("ManualReport", (), {"ready_for_manual_review": True})()
    long_term_report = type("LongTermReport", (), {"observed_days": 10, "first_observed_at": datetime(2026, 6, 1, 9, 0, 0)})()

    blocked = evaluate_delivery_gate(manual_report, long_term_report, explicit_opt_in=False)

    assert blocked.can_enable_delivery is False
    assert blocked.shadow_only is True
    assert blocked.reasons == ("insufficient_long_term_observation", "explicit_opt_in_required")
    assert blocked.first_observed_at == datetime(2026, 6, 1, 9, 0, 0)
    assert blocked.earliest_review_at == datetime(2026, 6, 15, 9, 0, 0)
    assert blocked.remaining_observation_days == 4

    ready_report = type("LongTermReport", (), {"observed_days": 14, "first_observed_at": datetime(2026, 6, 1, 9, 0, 0)})()
    allowed = evaluate_delivery_gate(manual_report, ready_report, explicit_opt_in=True)

    assert allowed.can_enable_delivery is True
    assert allowed.shadow_only is False
    assert allowed.reasons == ()
    assert allowed.to_dict()["requirements"]["requiredObservationDays"] == 14
    assert allowed.to_dict()["timeline"]["earliestReviewAt"] == "2026-06-15T09:00:00"
