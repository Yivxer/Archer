"""
v1.2 Phase 1 — 灵魂三层注入测试

覆盖：
- classify_query_intent 意图分类
- is_heavy_query 向后兼容
- COVENANT/PRESENCE 注入顺序
- SOUL 按需注入（decision/emotional/reflection 才注入）
- 普通 chat 不注入 SOUL
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.context import classify_query_intent, is_heavy_query, build_system_prompt


# ── classify_query_intent ──────────────────────────────────────────────────────

def test_greeting_is_chat():
    r = classify_query_intent("你好")
    assert r["intent"] == "chat"
    assert not r["needs_soul"]

def test_decision_keyword_triggers():
    for kw in ["建议", "该不该", "怎么办", "要不要", "应该"]:
        r = classify_query_intent(kw)
        assert r["intent"] == "decision", f"{kw!r} 应分类为 decision"
        assert r["needs_soul"]
        assert r["needs_memory"]

def test_emotional_keyword_triggers():
    for kw in ["焦虑", "迷茫", "难受", "害怕"]:
        r = classify_query_intent(kw)
        assert r["intent"] == "emotional", f"{kw!r} 应分类为 emotional"
        assert r["needs_soul"]

def test_reflection_keyword_triggers():
    for kw in ["复盘", "反思"]:
        r = classify_query_intent(kw)
        assert r["intent"] == "reflection", f"{kw!r} 应分类为 reflection"
        assert r["needs_soul"]
        assert r["needs_memory"]

def test_project_keyword_triggers():
    for kw in ["项目", "进度", "规划", "目标"]:
        r = classify_query_intent(kw)
        assert r["intent"] == "project", f"{kw!r} 应分类为 project"
        assert not r["needs_soul"]  # project 不注入 soul

def test_long_text_is_task_or_decision():
    r = classify_query_intent("帮我整理一下这周的工作进展，看看有什么需要优先处理的")
    assert r["needs_memory"]

def test_emotional_priority_over_decision():
    """emotional 优先级高于 decision。"""
    r = classify_query_intent("我很焦虑，不知道该怎么办")
    assert r["intent"] == "emotional"


# ── is_heavy_query 向后兼容 ────────────────────────────────────────────────────

def test_decision_kw_is_heavy():
    for kw in ["建议", "该不该", "怎么办", "规划", "复盘", "分析"]:
        assert is_heavy_query(kw), f"关键词 {kw!r} 应触发 heavy"

def test_short_neutral_is_not_heavy():
    assert not is_heavy_query("今天天气不错")
    assert not is_heavy_query("最近在读什么书")

def test_long_text_is_heavy():
    long_text = "这是一段超过四十个字符的文本，用于测试长文本是否被判断为 heavy 查询。"
    assert is_heavy_query(long_text)


# ── build_system_prompt 注入顺序 ────────────────────────────────────────────────

def _make_cfg(tmp_dir: str, **extra_paths) -> dict:
    """构造最小化 cfg 用于测试。"""
    return {
        "persona": {
            "name": "TestArcher",
            "soul_path": extra_paths.get("soul_path", ""),
            "memory_path": extra_paths.get("memory_path", ""),
            "covenant_path": extra_paths.get("covenant_path", ""),
            "presence_path": extra_paths.get("presence_path", ""),
            "default_mode": "coach",
            "modes": {},
        },
        "obsidian": {},
    }


def test_covenant_before_soul():
    with tempfile.TemporaryDirectory() as tmp:
        covenant = Path(tmp) / "COVENANT.md"
        covenant.write_text("# 根契约\n\n## 我不会做的事\n不替你做决定。\n\n## 我会做的事\n承认不确定。")
        soul = Path(tmp) / "SOUL.md"
        soul.write_text("# SOUL\n枫弋是个自由灵魂。")
        cfg = _make_cfg(tmp, covenant_path=str(covenant), soul_path=str(soul))
        prompt = build_system_prompt(cfg, heavy=False, intent="decision")
        # 用 section 标签而非关键词，避免 Runtime Safety 文本里的 SOUL.md 干扰
        covenant_pos = prompt.find("[根契约摘要]")
        soul_pos = prompt.find("[灵魂档案（SOUL.md）]")
        assert covenant_pos != -1, "COVENANT 摘要应出现在 prompt 中"
        assert soul_pos != -1, "SOUL 档案应出现在 prompt 中（decision 意图）"
        assert covenant_pos < soul_pos, "COVENANT 应在 SOUL 之前注入"

def test_presence_before_soul():
    with tempfile.TemporaryDirectory() as tmp:
        presence = Path(tmp) / "PRESENCE.md"
        presence.write_text("# PRESENCE\n\n## 默认基调\n偏向 coach。\n\n## 回应节奏\n简短开头。")
        soul = Path(tmp) / "SOUL.md"
        soul.write_text("# SOUL\n枫弋的灵魂。")
        cfg = _make_cfg(tmp, presence_path=str(presence), soul_path=str(soul))
        prompt = build_system_prompt(cfg, heavy=False, intent="decision")
        presence_pos = prompt.find("[在场方式]")
        soul_pos = prompt.find("[灵魂档案（SOUL.md）]")
        assert presence_pos != -1, "PRESENCE 摘要应出现在 prompt 中"
        assert soul_pos != -1, "SOUL 档案应出现在 prompt 中（decision 意图）"
        assert presence_pos < soul_pos, "PRESENCE 应在 SOUL 之前注入"

def test_soul_not_injected_in_chat():
    with tempfile.TemporaryDirectory() as tmp:
        soul = Path(tmp) / "SOUL.md"
        soul.write_text("枫弋的独特灵魂标识字符串：xUniqueMarker123。")
        cfg = _make_cfg(tmp, soul_path=str(soul))
        prompt = build_system_prompt(cfg, heavy=False, intent="chat")
        assert "xUniqueMarker123" not in prompt, "普通 chat 不应注入 SOUL 内容"
        assert "[灵魂档案（SOUL.md）]" not in prompt, "chat 不应有灵魂档案 section"

def test_soul_injected_in_decision():
    with tempfile.TemporaryDirectory() as tmp:
        soul = Path(tmp) / "SOUL.md"
        soul.write_text("枫弋的决策灵魂标识：yDecisionMarker456。")
        cfg = _make_cfg(tmp, soul_path=str(soul))
        prompt = build_system_prompt(cfg, heavy=True, intent="decision")
        assert "yDecisionMarker456" in prompt, "decision 意图应注入 SOUL 内容"

def test_soul_injected_in_emotional():
    with tempfile.TemporaryDirectory() as tmp:
        soul = Path(tmp) / "SOUL.md"
        soul.write_text("枫弋的情绪灵魂标识：zEmotionalMarker789。")
        cfg = _make_cfg(tmp, soul_path=str(soul))
        prompt = build_system_prompt(cfg, heavy=False, intent="emotional")
        assert "zEmotionalMarker789" in prompt, "emotional 意图应注入 SOUL 内容"

def test_runtime_safety_always_first():
    cfg = _make_cfg("/tmp")
    prompt = build_system_prompt(cfg, heavy=False, intent="chat")
    assert prompt.startswith("[安全边界]"), "Runtime Safety 应在最前"

def test_soul_not_injected_in_task():
    with tempfile.TemporaryDirectory() as tmp:
        soul = Path(tmp) / "SOUL.md"
        soul.write_text("枫弋的任务灵魂标识：wTaskMarker000。")
        cfg = _make_cfg(tmp, soul_path=str(soul))
        prompt = build_system_prompt(cfg, heavy=False, intent="task")
        assert "wTaskMarker000" not in prompt, "task 意图不应注入 SOUL 内容"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
