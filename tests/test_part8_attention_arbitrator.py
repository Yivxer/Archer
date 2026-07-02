from datetime import datetime


def test_attention_focus_prioritizes_open_threads_and_soul_tensions():
    from core.attention import attention_boost, build_attention_focus

    focus = build_attention_focus(
        recent_messages=[{"content": "继续做 Archer 的 Part 8"}],
        active_threads=[{"topic": "主动触达 opt-in", "prompt": "补授权流程"}],
        soul_tensions=["克制主动和长期在场之间的张力"],
    )

    assert "主动触达" in focus.terms
    assert "active_threads" in focus.sources
    assert attention_boost("这条记忆和主动触达授权有关", focus) > 0


def test_arbitrator_keeps_shadow_recording_inside_presence_and_frequency_boundaries():
    from core.arbitrator import evaluate_shadow_recording

    allowed = evaluate_shadow_recording(
        requested_presence_state="idle",
        persisted_presence_state="idle",
        today_count=0,
        daily_limit=3,
        throttled=False,
        throttled_limit=1,
    )
    muted = evaluate_shadow_recording(
        requested_presence_state="idle",
        persisted_presence_state="muted",
        today_count=0,
        daily_limit=3,
        throttled=False,
        throttled_limit=1,
    )
    throttled = evaluate_shadow_recording(
        requested_presence_state="idle",
        persisted_presence_state="idle",
        today_count=1,
        daily_limit=3,
        throttled=True,
        throttled_limit=1,
    )

    assert allowed.allowed is True
    assert allowed.reason == "within_daily_limit"
    assert muted.reason == "presence_muted"
    assert throttled.reason == "global_throttle_active"


def test_delivery_opt_in_state_is_explicit_and_reversible(tmp_path):
    from core.delivery_opt_in import get_delivery_opt_in, set_delivery_opt_in

    db = tmp_path / "archer.db"
    assert get_delivery_opt_in(db).enabled is False

    enabled = set_delivery_opt_in(db, enabled=True, reason="manual_review", now=datetime(2026, 6, 27, 9, 0, 0))
    disabled = set_delivery_opt_in(db, enabled=False, reason="revoked", now=datetime(2026, 6, 27, 10, 0, 0))

    assert enabled.enabled is True
    assert enabled.updated_at == "2026-06-27T09:00:00"
    assert disabled.enabled is False
    assert disabled.reason == "revoked"
