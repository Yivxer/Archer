def test_rhythm_backfill_adds_modeled_peak_summary_without_losing_profile_data():
    from core.rhythm import HOURS_PER_WEEK, RhythmProfile, hour_slot
    from memory.soul_profile import SoulProfile, backfill_rhythm

    weights = [0.001] * HOURS_PER_WEEK
    weights[hour_slot(__import__("datetime").datetime(2026, 6, 22, 21, 0, 0))] = 0.9
    weights[hour_slot(__import__("datetime").datetime(2026, 6, 24, 9, 0, 0))] = 0.8
    profile = SoulProfile(core_values=["保持自主"], rhythm=["手工记录：早晨适合规划"])

    updated = backfill_rhythm(
        profile,
        RhythmProfile("modeled", weights, observed_days=24, event_count=30, confidence=0.65),
        max_peaks=2,
    )

    assert updated.core_values == ["保持自主"]
    assert updated.rhythm[0] == "手工记录：早晨适合规划"
    assert updated.rhythm[1] == "[模型] 置信度 0.65；活动高峰：周一 21:00、周三 09:00"
    assert profile.rhythm == ["手工记录：早晨适合规划"]


def test_rhythm_backfill_keeps_profile_unchanged_during_cold_start():
    from core.rhythm import HOURS_PER_WEEK, RhythmProfile
    from memory.soul_profile import SoulProfile, backfill_rhythm

    profile = SoulProfile(rhythm=["手工记录：夜晚安静"])
    updated = backfill_rhythm(
        profile,
        RhythmProfile("cold_start", [1 / HOURS_PER_WEEK] * HOURS_PER_WEEK, 3, 4, 0.0),
    )

    assert updated == profile


def test_narrative_backfill_uses_only_high_importance_narrative_memory_types():
    from memory.soul_profile import SoulProfile, backfill_narrative

    profile = SoulProfile(narrative=["手工记录：长期主义"])
    updated = backfill_narrative(
        profile,
        [
            {"content": "正在从工具使用者转向自建系统", "type": "self_narrative", "importance": 5},
            {"content": "从失去旧记忆到重建新系统", "type": "life_theme", "importance": 4},
            {"content": "普通任务结果", "type": "insight", "importance": 5},
            {"content": "低重要度叙事", "type": "self_narrative", "importance": 3},
        ],
    )

    assert updated.narrative == [
        "手工记录：长期主义",
        "[模型] 正在从工具使用者转向自建系统",
        "[模型] 从失去旧记忆到重建新系统",
    ]
    assert profile.narrative == ["手工记录：长期主义"]


def test_narrative_backfill_deduplicates_and_respects_limit():
    from memory.soul_profile import SoulProfile, backfill_narrative

    updated = backfill_narrative(
        SoulProfile(),
        [
            {"content": "主题 A", "type": "life_theme", "importance": 5},
            {"content": "主题 A", "type": "reflection_anchor", "importance": 5},
            {"content": "主题 B", "type": "project_mythology", "importance": 5},
        ],
        limit=1,
    )

    assert updated.narrative == ["[模型] 主题 A"]


def test_tensions_backfill_keeps_only_explicit_high_importance_deep_memory():
    from memory.soul_profile import SoulProfile, backfill_tensions

    profile = SoulProfile(tensions=["手工记录：效率与休息的拉扯"])
    updated = backfill_tensions(
        profile,
        [
            {"content": "想要主动性，但不能被打扰", "type": "life_theme", "importance": 4},
            {"content": "明明想休息，却总在规划", "type": "self_narrative", "importance": 5},
            {"content": "任务完成，但是还要发布", "type": "insight", "importance": 5},
            {"content": "想快一点，但还不够重要", "type": "life_theme", "importance": 3},
        ],
    )

    assert updated.tensions == [
        "手工记录：效率与休息的拉扯",
        "[模型] 想要主动性，但不能被打扰",
        "[模型] 明明想休息，却总在规划",
    ]
    assert profile.tensions == ["手工记录：效率与休息的拉扯"]


def test_patterns_backfill_uses_existing_evidence_gated_behavior_themes():
    from memory.soul_profile import SoulProfile, backfill_patterns

    profile = SoulProfile(patterns=["手工记录：先完成再优化"])
    updated = backfill_patterns(
        profile,
        [
            {"name": "结构优先", "description": "先搭结构，再小步验证", "category": "behavior"},
            {"name": "持续挑战", "description": "面对不确定时会反复规划", "category": "struggle"},
            {"name": "AI 工具", "description": "持续研究工具", "category": "interest"},
            {"name": "成长轨迹", "description": "", "category": "growth"},
        ],
    )

    assert updated.patterns == [
        "手工记录：先完成再优化",
        "[模型] 先搭结构，再小步验证",
        "[模型] 面对不确定时会反复规划",
        "[模型] 成长轨迹",
    ]
    assert profile.patterns == ["手工记录：先完成再优化"]


def test_patterns_backfill_deduplicates_and_respects_limit():
    from memory.soul_profile import SoulProfile, backfill_patterns

    updated = backfill_patterns(
        SoulProfile(),
        [
            {"name": "结构优先", "description": "先搭结构", "category": "behavior"},
            {"name": "重复", "description": "先搭结构", "category": "growth"},
        ],
        limit=1,
    )

    assert updated.patterns == ["[模型] 先搭结构"]
