from datetime import datetime


def test_opportunity_detects_return_to_engaged_state():
    from core.opportunity import detect_opportunities

    candidates = detect_opportunities(
        previous_presence_state="idle",
        current_presence_state="engaged",
        open_threads=[],
        now=datetime(2026, 6, 26, 20, 0, 0),
    )

    assert len(candidates) == 1
    assert candidates[0].kind == "presence_return"
    assert candidates[0].reason == "presence_became_engaged"
    assert candidates[0].score == 0.65


def test_opportunity_detects_oldest_stale_open_thread():
    from core.opportunity import detect_opportunities

    candidates = detect_opportunities(
        previous_presence_state="engaged",
        current_presence_state="engaged",
        open_threads=[
            {"id": 4, "topic": "近期话题", "status": "open", "last_seen_at": "2026-06-24T20:00:00"},
            {"id": 9, "topic": "长期计划", "status": "open", "last_seen_at": "2026-06-14T20:00:00"},
        ],
        now=datetime(2026, 6, 26, 20, 0, 0),
    )

    assert len(candidates) == 1
    assert candidates[0].kind == "stale_thread"
    assert candidates[0].reason == "thread_untouched_for_days"
    assert candidates[0].score == 0.8
    assert candidates[0].trace["threadId"] == 9
    assert candidates[0].trace["daysUntouched"] == 12


def test_opportunity_ignores_recent_or_closed_threads():
    from core.opportunity import detect_opportunities

    candidates = detect_opportunities(
        previous_presence_state="engaged",
        current_presence_state="engaged",
        open_threads=[
            {"id": 1, "topic": "刚讨论过", "status": "open", "last_seen_at": "2026-06-25T20:00:00"},
            {"id": 2, "topic": "已结束", "status": "closed", "last_seen_at": "2026-06-01T20:00:00"},
        ],
        now=datetime(2026, 6, 26, 20, 0, 0),
    )

    assert candidates == []
