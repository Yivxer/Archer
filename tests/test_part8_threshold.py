from datetime import datetime


def test_threshold_blocks_when_presence_is_muted():
    from core.threshold import InitiativeThresholdInput, evaluate_threshold

    decision = evaluate_threshold(
        InitiativeThresholdInput(
            now=datetime(2026, 6, 26, 9, 0, 0),
            presence_state="muted",
            moment_kind="open",
            opportunity_score=0.9,
            relationship_score=0.9,
            creative_score=0.9,
        )
    )

    assert decision.allowed is False
    assert decision.reason == "presence_muted"
    assert decision.score == 0.0


def test_threshold_blocks_rest_window_even_with_high_opportunity():
    from core.threshold import InitiativeThresholdInput, evaluate_threshold

    decision = evaluate_threshold(
        InitiativeThresholdInput(
            now=datetime(2026, 6, 26, 1, 0, 0),
            presence_state="idle",
            moment_kind="rest",
            opportunity_score=1.0,
            relationship_score=1.0,
            creative_score=1.0,
        )
    )

    assert decision.allowed is False
    assert decision.reason == "quiet_window"


def test_threshold_allows_high_signal_open_window():
    from core.threshold import InitiativeThresholdInput, evaluate_threshold

    decision = evaluate_threshold(
        InitiativeThresholdInput(
            now=datetime(2026, 6, 26, 21, 0, 0),
            presence_state="idle",
            moment_kind="deep_conversation",
            opportunity_score=0.8,
            relationship_score=0.7,
            creative_score=0.6,
        )
    )

    assert decision.allowed is True
    assert decision.reason == "threshold_met"
    assert decision.score >= 0.7
    assert decision.trace["momentKind"] == "deep_conversation"


def test_threshold_requires_enough_combined_signal():
    from core.threshold import InitiativeThresholdInput, evaluate_threshold

    decision = evaluate_threshold(
        InitiativeThresholdInput(
            now=datetime(2026, 6, 26, 15, 0, 0),
            presence_state="idle",
            moment_kind="work",
            opportunity_score=0.2,
            relationship_score=0.2,
            creative_score=0.1,
        )
    )

    assert decision.allowed is False
    assert decision.reason == "below_threshold"
