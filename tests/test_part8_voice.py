def test_voice_for_stale_thread_keeps_topic_without_pressuring_user():
    from core.opportunity import OpportunityCandidate
    from core.voice import compose_proactive_voice

    draft = compose_proactive_voice(
        OpportunityCandidate(
            kind="stale_thread",
            reason="thread_untouched_for_days",
            score=0.8,
            trace={"topic": "长期计划"},
        ),
        stance="witness",
    )

    assert draft.stance == "witness"
    assert "长期计划" in draft.message
    assert "不需要现在回答" in draft.message


def test_voice_is_independent_from_current_work_mode():
    from core.opportunity import OpportunityCandidate
    from core.voice import compose_proactive_voice

    candidate = OpportunityCandidate(
        kind="presence_return",
        reason="presence_became_engaged",
        score=0.65,
        trace={},
    )

    builder = compose_proactive_voice(candidate, stance="companion", current_mode="builder")
    writer = compose_proactive_voice(candidate, stance="companion", current_mode="writer")

    assert builder.message == writer.message
    assert builder.stance == "companion"
    assert builder.source_kind == "presence_return"


def test_voice_falls_back_to_companion_for_unknown_stance_or_candidate():
    from core.opportunity import OpportunityCandidate
    from core.voice import compose_proactive_voice

    draft = compose_proactive_voice(
        OpportunityCandidate(kind="unknown", reason="unknown", score=0.1, trace={}),
        stance="operator",
    )

    assert draft.stance == "companion"
    assert draft.message == "有一条线索值得先留在这里，不急着处理。"
