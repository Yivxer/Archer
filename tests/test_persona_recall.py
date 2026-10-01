from __future__ import annotations

from pathlib import Path

import pytest

from core.context import build_desktop_core_prompt, build_system_prompt


@pytest.fixture
def recall_config(tmp_path: Path) -> dict:
    memory = tmp_path / "MEMORY.md"
    memory.write_text(
        "# 个人档案\n## 学习习惯\n"
        "我学习植物学时，先读观察笔记，然后去园子里辨认植物。\n\n"
        "## 制作习惯\n我制作木器时，先画草图，再测量木料。\n",
        encoding="utf-8",
    )
    soul = tmp_path / "SOUL.md"
    soul.write_text(
        "# 灵魂档案\n## 当前判断\n### 恢复方式\n"
        "我通常通过散步和睡眠恢复精力，不把忙碌当作成长。\n\n"
        "## 历史档案\n### 恢复方式\n过去依靠熬夜工作恢复精力。\n",
        encoding="utf-8",
    )
    return {"persona": {"memory_path": str(memory), "soul_path": str(soul)}}


def test_simple_prompt_recalls_configured_source(recall_config: dict) -> None:
    prompt = build_desktop_core_prompt(recall_config, query="我学习植物学的习惯是什么？")
    assert "先读观察笔记" in prompt
    assert "先画草图" not in prompt
    assert "context:memory_md" in prompt


def test_full_prompt_recalls_source_outside_broad_scope(recall_config: dict) -> None:
    prompt = build_system_prompt(
        recall_config, heavy=False, intent="chat", memory_scope=["knowledge"],
        user_input="我学习植物学的习惯是什么？",
    )
    assert "先读观察笔记" in prompt


@pytest.mark.parametrize("query", [
    "植物学是什么？", "我喜欢的陶艺釉色是什么？", "替我编一个植物学学习习惯。", "你好",
])
def test_recall_does_not_inject_for_unrelated_or_invented_requests(
    recall_config: dict, query: str,
) -> None:
    prompt = build_desktop_core_prompt(recall_config, query=query)
    assert "先读观察笔记" not in prompt
    assert "context:memory_md" not in prompt


def test_recall_keeps_current_judgment_separate_from_history(recall_config: dict) -> None:
    prompt = build_desktop_core_prompt(recall_config, query="我通常如何恢复精力？")
    assert "散步和睡眠" in prompt
    assert "过去依靠熬夜" not in prompt


def test_memory_off_does_not_add_source_recall(recall_config: dict) -> None:
    prompt = build_system_prompt(
        recall_config, heavy=False, intent="chat", memory_scope=[],
        user_input="我学习植物学的习惯是什么？", allow_persona_recall=False,
    )
    assert "先读观察笔记" not in prompt


def test_source_change_invalidates_cached_sections(recall_config: dict) -> None:
    from core.persona_recall import recall_persona_sections

    query = "我学习植物学的习惯是什么？"
    before = recall_persona_sections(query, recall_config)
    path = Path(recall_config["persona"]["memory_path"])
    path.write_text("## 学习习惯\n我学习植物学时，改为先观察叶片，再读笔记。\n", encoding="utf-8")
    after = recall_persona_sections(query, recall_config)
    assert "先读观察笔记" in before[0].text
    assert "先观察叶片" in after[0].text


def test_recall_rejects_unreadable_or_oversized_sources(recall_config: dict) -> None:
    from core.persona_recall import recall_persona_sections

    path = Path(recall_config["persona"]["memory_path"])
    path.write_bytes(b"\xff\xfe")
    assert recall_persona_sections("我学习植物学的习惯是什么？", recall_config) == []
    path.write_bytes(b"x" * 1_000_001)
    assert recall_persona_sections("我学习植物学的习惯是什么？", recall_config) == []


def test_recall_bounds_source_excerpt(recall_config: dict) -> None:
    from core.persona_recall import persona_recall_blocks

    Path(recall_config["persona"]["memory_path"]).write_text(
        "## 学习习惯\n我学习植物学时先看叶片。" + "叶片记录。" * 1000,
        encoding="utf-8",
    )
    blocks = persona_recall_blocks("我学习植物学的习惯是什么？", recall_config)
    assert len(blocks) == 1
    assert len(blocks[0]) < 2100


def test_explicit_unknown_thread_does_not_borrow_latest(monkeypatch: pytest.MonkeyPatch) -> None:
    from terminal.api.turn_context import _inject_stored_thread_context

    monkeypatch.setattr("memory.thread_context.get_thread_context", lambda thread_id: None)
    monkeypatch.setattr("memory.thread_context.latest_thread_context", lambda: {
        "contextState": {"goal": "别的线程中的目标"}, "lastStop": "其他线程停点",
    })
    messages = [{"role": "user", "content": "我们上次聊到哪里？"}]
    assert _inject_stored_thread_context(messages, "explicit-missing-thread") == messages


def test_assistant_suggestion_is_not_labelled_user_confirmed() -> None:
    from memory.thread_context import build_context_capsule, format_context_capsule

    capsule = build_context_capsule([
        {"role": "user", "content": "我还在比较两条路线"},
        {"role": "assistant", "content": "我建议先去海边"},
    ])
    prompt = format_context_capsule(capsule)
    assert "我建议先去海边" in prompt
    assert "已确认结论" not in prompt
    assert "须核对用户确认" in prompt
