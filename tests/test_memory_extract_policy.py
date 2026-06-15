"""
P5.16 — Type-specific extraction prompts tests.
Verifies that each policy type gets its dedicated system prompt,
and that the generic prompt is used as fallback.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from memory.extract import (
    _PROMPT,
    _TYPE_PROMPTS,
    _CANDIDATE_FOCUS,
    build_extract_focus_block,
    extract,
)


# ── Type-specific prompt selection ──────────────────────────────────────────

def test_type_prompts_exist_for_all_candidate_focus_keys():
    """Every key in _CANDIDATE_FOCUS should have a corresponding _TYPE_PROMPTS entry."""
    for key in _CANDIDATE_FOCUS:
        assert key in _TYPE_PROMPTS, f"Missing _TYPE_PROMPTS entry for: {key}"


def test_project_update_prompt_contains_key_terms():
    prompt = _TYPE_PROMPTS["project_update"]
    assert "项目" in prompt
    assert "decision" in prompt
    assert "project_mythology" in prompt
    assert "不多于" not in prompt.lower() or "最多返回 3 条" in prompt
    assert "拿不准就不要写入" in prompt


def test_writing_preference_prompt_contains_key_terms():
    prompt = _TYPE_PROMPTS["writing_preference"]
    assert "写作" in prompt
    assert "creative_identity" in prompt
    assert "preference" in prompt
    assert "拿不准就不要写入" in prompt


def test_emotional_pattern_prompt_contains_key_terms():
    prompt = _TYPE_PROMPTS["emotional_pattern"]
    assert "情绪" in prompt
    assert "emotion_pattern" in prompt
    assert "不诊断" in prompt
    assert "拿不准就不要写入" in prompt


def test_life_theme_prompt_contains_key_terms():
    prompt = _TYPE_PROMPTS["life_theme"]
    assert "人生" in prompt
    assert "life_theme" in prompt
    assert "value" in prompt
    assert "reflection_anchor" in prompt
    assert "拿不准就不要写入" in prompt


def test_reflection_anchor_prompt_contains_key_terms():
    prompt = _TYPE_PROMPTS["reflection_anchor"]
    assert "复盘" in prompt
    assert "reflection_anchor" in prompt
    assert "growth_marker" in prompt
    assert "拿不准就不要写入" in prompt


def test_task_result_prompt_contains_key_terms():
    prompt = _TYPE_PROMPTS["task_result"]
    assert "任务" in prompt
    assert "decision" in prompt
    assert "todo" in prompt
    assert "拿不准就不要写入" in prompt


def test_generic_prompt_is_fallback():
    """Generic _PROMPT is distinct from all type-specific prompts and is the fallback."""
    assert _PROMPT not in _TYPE_PROMPTS.values()
    for key, typed in _TYPE_PROMPTS.items():
        assert typed != _PROMPT, f"Type prompt for {key} should differ from generic _PROMPT"


# ── build_extract_focus_block regression tests ──────────────────────────────

def test_build_extract_focus_block_empty_candidate_types():
    result = build_extract_focus_block(None)
    assert result == ""

    result = build_extract_focus_block([])
    assert result == ""


def test_build_extract_focus_block_single_type():
    result = build_extract_focus_block(["project_update"])
    assert "project_update" in result
    assert "project" in result
    assert "decision" in result


def test_build_extract_focus_block_multiple_types():
    result = build_extract_focus_block(["project_update", "task_result"])
    assert "project_update" in result
    assert "task_result" in result


def test_build_extract_focus_block_sensitive():
    result = build_extract_focus_block(["emotional_pattern"], sensitive=True)
    assert "emotional_pattern" in result
    assert "敏感" in result or "诊断" in result


def test_build_extract_focus_block_unknown_type_no_hint():
    """Unknown candidate types should not produce a hint line."""
    result = build_extract_focus_block(["nonexistent_type"])
    # Should still have the header line
    assert "本轮提炼范围" in result
    # Unknown type has no matching hint, so only the header is present
    assert "- nonexistent_type" not in result


# ── extract() without candidate_types uses generic prompt ───────────────────

def test_extract_no_candidate_types_uses_generic(monkeypatch):
    """When candidate_types is None/empty, the generic _PROMPT is used."""
    captured_prompt: list[str] = []

    def fake_stream_chat(messages, track_usage=False):
        captured_prompt.append(messages[0]["content"])
        yield '{"memories": []}'

    monkeypatch.setattr("memory.extract.stream_chat", fake_stream_chat)

    history = [
        {"role": "user", "content": "我今天想了一下，觉得应该更有耐心"},
        {"role": "assistant", "content": "这是一个很好的觉察"},
    ]
    extract(history, candidate_types=None)
    assert captured_prompt
    # Generic prompt starts with "你是严格的长期记忆提炼助手"
    assert captured_prompt[0].startswith(_PROMPT.split("\n")[0])


# ── extract() with candidate_types uses type-specific prompt ────────────────

def test_extract_with_project_update_uses_typed_prompt(monkeypatch):
    captured_prompt: list[str] = []

    def fake_stream_chat(messages, track_usage=False):
        captured_prompt.append(messages[0]["content"])
        yield '{"memories": []}'

    monkeypatch.setattr("memory.extract.stream_chat", fake_stream_chat)

    history = [
        {"role": "user", "content": "我把 Part5 的代码写完了"},
        {"role": "assistant", "content": "需要记录什么吗？"},
    ]
    extract(history, candidate_types=["project_update"])
    assert captured_prompt
    # Should use the type-specific prompt, not generic
    assert _TYPE_PROMPTS["project_update"].split("\n")[0] in captured_prompt[0]


def test_extract_with_task_result_uses_typed_prompt(monkeypatch):
    captured_prompt: list[str] = []

    def fake_stream_chat(messages, track_usage=False):
        captured_prompt.append(messages[0]["content"])
        yield '{"memories": []}'

    monkeypatch.setattr("memory.extract.stream_chat", fake_stream_chat)

    history = [
        {"role": "user", "content": "任务完成了，数据库迁移脚本已经写好"},
        {"role": "assistant", "content": "好的"},
    ]
    extract(history, candidate_types=["task_result"])
    assert captured_prompt
    assert _TYPE_PROMPTS["task_result"].split("\n")[0] in captured_prompt[0]


def test_extract_with_multiple_candidate_types_uses_first_matching(monkeypatch):
    """When multiple candidate_types are given, the first one with a _TYPE_PROMPTS entry is used."""
    captured_prompt: list[str] = []

    def fake_stream_chat(messages, track_usage=False):
        captured_prompt.append(messages[0]["content"])
        yield '{"memories": []}'

    monkeypatch.setattr("memory.extract.stream_chat", fake_stream_chat)

    history = [
        {"role": "user", "content": "聊聊最近的项目进展和我对写作的看法"},
        {"role": "assistant", "content": "好啊"},
    ]
    extract(history, candidate_types=["project_update", "writing_preference"])
    assert captured_prompt
    # First matching type should be used
    assert _TYPE_PROMPTS["project_update"].split("\n")[0] in captured_prompt[0]


def test_extract_with_unknown_candidate_type_falls_back_to_generic(monkeypatch):
    """When candidate_types has only unknown types, fall back to generic prompt."""
    captured_prompt: list[str] = []

    def fake_stream_chat(messages, track_usage=False):
        captured_prompt.append(messages[0]["content"])
        yield '{"memories": []}'

    monkeypatch.setattr("memory.extract.stream_chat", fake_stream_chat)

    history = [
        {"role": "user", "content": "今天天气不错"},
        {"role": "assistant", "content": "是的"},
    ]
    extract(history, candidate_types=["unknown_type"])
    assert captured_prompt
    # Should fall back to generic prompt
    assert captured_prompt[0].startswith(_PROMPT.split("\n")[0])


def test_extract_empty_history():
    """extract() with empty history returns empty lists."""
    mems, obsidian = extract([])
    assert mems == []
    assert obsidian == []


def test_extract_focus_block_appended_to_typed_prompt(monkeypatch):
    """When candidate_types is set, focus block is appended to type-specific prompt."""
    captured_prompt: list[str] = []

    def fake_stream_chat(messages, track_usage=False):
        captured_prompt.append(messages[0]["content"])
        yield '{"memories": []}'

    monkeypatch.setattr("memory.extract.stream_chat", fake_stream_chat)

    history = [
        {"role": "user", "content": "项目做完了"},
        {"role": "assistant", "content": "好"},
    ]
    extract(history, candidate_types=["project_update"])
    assert captured_prompt
    full = captured_prompt[0]
    assert _TYPE_PROMPTS["project_update"].split("\n")[0] in full
    assert "本轮提炼范围" in full
