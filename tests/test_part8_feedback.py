def test_feedback_recommends_slow_down_after_too_frequent_signal():
    from core.feedback import analyze_initiative_feedback

    summary = analyze_initiative_feedback(
        [
            {"feedback": "acknowledged"},
            {"feedback": "too_frequent"},
            {"feedback": ""},
        ]
    )

    assert summary.feedback_count == 2
    assert summary.recognition_rate == 0.5
    assert summary.too_frequent_count == 1
    assert summary.recommendation == "slow_down"
    assert summary.pacing_multiplier == 0.25


def test_feedback_keeps_steady_pacing_when_recognition_is_consistently_positive():
    from core.feedback import analyze_initiative_feedback

    summary = analyze_initiative_feedback(
        [
            {"feedback": "acknowledged"},
            {"feedback": "helpful"},
            {"feedback": "acknowledged"},
        ]
    )

    assert summary.recognition_rate == 1.0
    assert summary.recommendation == "steady"
    assert summary.pacing_multiplier == 1.0


def test_feedback_observes_when_no_user_feedback_exists():
    from core.feedback import analyze_initiative_feedback

    summary = analyze_initiative_feedback([{"feedback": ""}, {"feedback": "unknown"}])

    assert summary.feedback_count == 0
    assert summary.recognition_rate is None
    assert summary.recommendation == "observe"
