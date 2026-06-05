"""
A1 — 身份与人格系统测试
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _cfg():
    return {"persona": {"default_mode": "listener", "modes": {}}, "obsidian": {}}


def test_persona_module_exports_reusable_constants():
    from core.persona import SOUL_COMPANION_IDENTITY, CONVERSATION_RHYTHM_RULES, FIRST_RUN_PATH

    assert "长期陪伴型 AI 灵魂伴生体" in SOUL_COMPANION_IDENTITY
    assert "呼吸节奏" in CONVERSATION_RHYTHM_RULES
    assert "首问策略" in FIRST_RUN_PATH
    assert "首条记忆优先级" in FIRST_RUN_PATH
    assert "首次结束信号" in FIRST_RUN_PATH


def test_system_prompt_includes_rhythm_awareness():
    from core.context import build_system_prompt

    prompt = build_system_prompt(_cfg(), heavy=False, intent="chat")
    assert "对话节奏感知" in prompt
    assert "先判断用户呼吸节奏" in prompt


def test_first_run_prompt_is_only_injected_when_requested():
    from core.context import build_system_prompt

    normal = build_system_prompt(_cfg(), heavy=False, intent="chat")
    first = build_system_prompt(_cfg(), heavy=False, intent="chat", first_run=True)

    assert "[新用户 First-Run 路径]" not in normal
    assert "[新用户 First-Run 路径]" in first
    assert "首问策略" in first


def test_context_keeps_soul_companion_identity():
    from core.context import build_system_prompt

    prompt = build_system_prompt(_cfg(), heavy=False, intent="chat")
    assert "soul_companion" in prompt
    assert "长期陪伴型 AI 灵魂伴生体" in prompt
