"""
A7 — 技能降权与模型适配策略测试
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _cfg():
    return {"persona": {"default_mode": "listener", "modes": {}}, "obsidian": {}}


def test_persona_exports_skill_and_model_strategy():
    from core.persona import SKILL_SYSTEM_DOWNRANKING, MODEL_ADAPTATION_NOTES

    assert "技能使用原则" in SKILL_SYSTEM_DOWNRANKING
    assert "自然地使用它们完成用户的请求" in SKILL_SYSTEM_DOWNRANKING
    assert "当用户只是想被理解时" in SKILL_SYSTEM_DOWNRANKING
    assert "DeepSeek" in MODEL_ADAPTATION_NOTES
    assert "Soul Profile" in MODEL_ADAPTATION_NOTES
    assert "temperature" in MODEL_ADAPTATION_NOTES


def test_system_prompt_includes_a7_strategy_layers():
    from core.context import build_system_prompt

    prompt = build_system_prompt(_cfg(), heavy=False, intent="chat")
    assert "技能使用原则" in prompt
    assert "自然地使用它们完成用户的请求" in prompt
    assert "模型适配注意事项" in prompt
    assert "Soul Profile 注入量上限" in prompt
