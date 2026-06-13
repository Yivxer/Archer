"""
A4 — 记忆系统升级测试草案

目标：先用测试固定 A4 的最小安全边界，再决定实现方式。
本轮倾向不直接改 DB schema；depth / metadata 可先通过 JSON metadata 承载。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def test_a4_memory_types_are_registered():
    from memory.store import MEMORY_TYPES

    for memory_type in [
        "fact",
        "preference",
        "emotion_pattern",
        "value",
        "value_conflict",
        "life_theme",
        "self_narrative",
        "project_mythology",
        "relationship_pattern",
        "creative_identity",
        "growth_marker",
        "reflection_anchor",
    ]:
        assert memory_type in MEMORY_TYPES


def test_memory_record_accepts_depth_metadata_without_schema_change():
    from memory.a4 import normalize_memory_candidate

    candidate = normalize_memory_candidate({
        "content": "枫弋把 Archer 从工具重新定义为灵魂伴生体。",
        "type": "project_mythology",
        "importance": 5,
        "depth": 5,
        "tags": "Archer,SOUL",
    })

    assert candidate["type"] == "project_mythology"
    assert candidate["depth"] == 5
    assert candidate["metadata"]["depth"] == 5
    assert candidate["metadata"]["type_family"] == "soul"


def test_depth_is_clamped_to_1_5():
    from memory.a4 import normalize_memory_candidate

    low = normalize_memory_candidate({"content": "这是一个足够长的事实", "depth": -3})
    high = normalize_memory_candidate({"content": "这是一个足够长的精神母题", "depth": 9})

    assert low["depth"] == 1
    assert high["depth"] == 5


def test_weighty_sentence_becomes_reflection_anchor():
    from memory.a4 import should_create_reflection_anchor

    assert should_create_reflection_anchor("自己能做的事情尽量自己能做好就行")
    assert should_create_reflection_anchor("Archer 不是工具，是灵魂伴侣")
    assert not should_create_reflection_anchor("好的")
    assert not should_create_reflection_anchor("帮我改一下这个按钮")


def test_retrieval_policy_caps_at_seven_and_prioritizes_anchor():
    from memory.a4 import select_context_memories

    memories = [
        {"id": 1, "content": "普通事实", "type": "fact", "importance": 3, "depth": 1},
        {"id": 2, "content": "价值判断", "type": "value", "importance": 5, "depth": 4},
        {"id": 3, "content": "反思锚点", "type": "reflection_anchor", "importance": 5, "depth": 5},
        {"id": 4, "content": "人生主题", "type": "life_theme", "importance": 4, "depth": 5},
        {"id": 5, "content": "项目神话", "type": "project_mythology", "importance": 5, "depth": 5},
        {"id": 6, "content": "情绪模式", "type": "emotion_pattern", "importance": 4, "depth": 4},
        {"id": 7, "content": "关系模式", "type": "relationship_pattern", "importance": 3, "depth": 3},
        {"id": 8, "content": "创作身份", "type": "creative_identity", "importance": 4, "depth": 4},
    ]

    selected = select_context_memories(
        memories,
        intent="reflection",
        trigger="reflection_anchor",
        limit=7,
    )

    assert len(selected) == 7
    assert selected[0]["type"] == "reflection_anchor"
    assert {m["id"] for m in selected} <= {m["id"] for m in memories}


def test_extract_prompt_mentions_a4_memory_types_and_depth():
    import memory.extract as extract

    prompt = extract._PROMPT
    assert "emotion_pattern" in prompt
    assert "reflection_anchor" in prompt
    assert "project_mythology" in prompt
    assert "depth" in prompt
    assert "1=事实" in prompt
    assert "5=精神母题" in prompt


def test_build_extract_focus_block_scopes_by_candidate_types():
    from memory.extract import build_extract_focus_block

    block = build_extract_focus_block(
        ["writing_preference", "task_result"],
        sensitive=False,
    )
    assert "writing_preference" in block
    assert "preference" in block
    assert "task_result" in block
    assert "敏感内容" not in block


def test_build_extract_focus_block_allows_project_update_drafts():
    from memory.extract import build_extract_focus_block

    block = build_extract_focus_block(["project_update"], sensitive=False)

    assert "project_update" in block
    assert "项目进展" in block
    assert "项目记忆草稿" in block
    assert "待用户确认" in block


def test_build_extract_focus_block_marks_sensitive_emotional():
    from memory.extract import build_extract_focus_block

    block = build_extract_focus_block(["emotional_pattern"], sensitive=True)
    assert "emotional_pattern" in block
    assert "敏感内容" in block


def test_retrieve_uses_a4_policy_for_reflection_anchor(monkeypatch):
    import memory.retrieve as retrieve

    mems = [
        {"id": 1, "content": "普通事实", "type": "fact", "importance": 3, "depth": 1},
        {"id": 2, "content": "反思锚点", "type": "reflection_anchor", "importance": 5, "depth": 5},
        {"id": 3, "content": "价值判断", "type": "value", "importance": 5, "depth": 4},
    ]

    monkeypatch.setattr(retrieve, "high_importance", lambda min_importance=4, limit=2: [])
    monkeypatch.setattr(retrieve, "_hybrid_search", lambda query, limit: list(mems))
    touched = []
    monkeypatch.setattr(retrieve, "update_last_used", lambda mid: touched.append(mid))

    core, related = retrieve.for_context("Archer 不是工具，是灵魂伴侣", limit=7, intent="reflection")

    assert core == []
    assert related[0]["type"] == "reflection_anchor"
    assert len(core + related) <= 7
    assert touched[0] == 2


def test_retrieve_caps_combined_context_to_seven(monkeypatch):
    import memory.retrieve as retrieve

    core_mems = [
        {"id": 100, "content": "核心价值", "type": "value", "importance": 5, "depth": 5},
        {"id": 101, "content": "核心主题", "type": "life_theme", "importance": 5, "depth": 5},
    ]
    related_mems = [
        {"id": i, "content": f"候选{i}", "type": "fact", "importance": 3, "depth": 1}
        for i in range(1, 10)
    ]

    monkeypatch.setattr(retrieve, "high_importance", lambda min_importance=4, limit=2: list(core_mems))
    monkeypatch.setattr(retrieve, "_hybrid_search", lambda query, limit: list(related_mems))
    monkeypatch.setattr(retrieve, "update_last_used", lambda mid: None)

    core, related = retrieve.for_context("复盘 Archer 的变化", limit=7, intent="reflection")

    assert len(core + related) == 7
    assert len(core) == 2
    assert len(related) == 5


def test_retrieve_emotional_intent_prioritizes_emotion_pattern(monkeypatch):
    import memory.retrieve as retrieve

    mems = [
        {"id": 1, "content": "价值", "type": "value", "importance": 5, "depth": 4},
        {"id": 2, "content": "情绪模式", "type": "emotion_pattern", "importance": 4, "depth": 4},
        {"id": 3, "content": "事实", "type": "fact", "importance": 3, "depth": 1},
    ]

    monkeypatch.setattr(retrieve, "high_importance", lambda min_importance=4, limit=2: [])
    monkeypatch.setattr(retrieve, "_hybrid_search", lambda query, limit: list(mems))
    monkeypatch.setattr(retrieve, "update_last_used", lambda mid: None)

    core, related = retrieve.for_context("我最近很焦虑", limit=7, intent="emotional")

    assert related[0]["type"] == "emotion_pattern"
