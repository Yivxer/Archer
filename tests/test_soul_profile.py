"""
A5 — Soul Profile 结构化骨架测试

覆盖：
- SoulProfile 的字段结构
- current_life_stage 优先注入
- 长期特质按意图/文本匹配注入
- 注入总量不超过 7 条
- 空档案不产生 prompt section
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.context import build_system_prompt
from memory.soul_profile import SoulProfile, format_soul_profile_for_prompt


def test_soul_profile_has_required_fields():
    profile = SoulProfile()
    for field in [
        "core_values",
        "recurring_fears",
        "creative_identity",
        "life_themes",
        "emotional_patterns",
        "relationship_patterns",
        "aesthetic_preferences",
        "project_mythology",
        "language_style",
        "important_questions",
        "current_life_stage",
    ]:
        assert hasattr(profile, field), f"SoulProfile 缺少字段：{field}"


def test_current_life_stage_is_injected_first():
    profile = SoulProfile(
        current_life_stage=["正在从工具使用者转向自建系统的人"],
        core_values=["自己能做的事情尽量自己做好"],
    )
    text = format_soul_profile_for_prompt(profile, intent="decision", user_input="我该怎么选")
    assert text.startswith("[Soul Profile 摘要]")
    assert text.index("当前阶段：正在从工具使用者转向自建系统的人") < text.index("核心价值：自己能做的事情尽量自己做好")


def test_emotional_intent_prioritizes_emotional_patterns():
    profile = SoulProfile(
        current_life_stage=["正在全面接手门店"],
        core_values=["重视自己动手"],
        emotional_patterns=["焦虑时会用规划填充行动前的不确定"],
    )
    text = format_soul_profile_for_prompt(profile, intent="emotional", user_input="我最近很焦虑")
    assert "情绪模式：焦虑时会用规划填充行动前的不确定" in text


def test_project_query_prioritizes_project_mythology():
    profile = SoulProfile(
        current_life_stage=["Archer 进入灵魂伴生体阶段"],
        project_mythology=["Archer 的终端是内核，客户端是壳"],
        life_themes=["从失去旧记忆到重建新系统"],
    )
    text = format_soul_profile_for_prompt(profile, intent="project", user_input="Archer 下一步怎么推进")
    assert "项目神话：Archer 的终端是内核，客户端是壳" in text


def test_prompt_is_capped_at_seven_items():
    profile = SoulProfile(
        current_life_stage=["阶段1", "阶段2"],
        core_values=["价值1", "价值2", "价值3"],
        recurring_fears=["恐惧1", "恐惧2"],
        creative_identity=["身份1", "身份2"],
        life_themes=["主题1", "主题2"],
        emotional_patterns=["模式1", "模式2"],
    )
    text = format_soul_profile_for_prompt(profile, intent="reflection", user_input="复盘一下")
    # 第一行是 section 标题，后面每行一条档案摘要
    assert len(text.splitlines()) - 1 <= 7


def test_empty_profile_returns_empty_string():
    assert format_soul_profile_for_prompt(SoulProfile(), intent="chat", user_input="你好") == ""


def test_build_system_prompt_injects_compact_soul_profile(tmp_path):
    profile_path = tmp_path / "soul_profile.json"
    profile_path.write_text(
        """
        {
          "current_life_stage": ["正在推进 Archer 灵魂伴生体阶段"],
          "core_values": ["自己能做的事情尽量自己做好"],
          "project_mythology": ["终端是内核，客户端是壳"]
        }
        """.strip(),
        encoding="utf-8",
    )
    cfg = {
        "persona": {
            "default_mode": "listener",
            "modes": {},
            "soul_profile_path": str(profile_path),
        },
        "obsidian": {},
    }
    prompt = build_system_prompt(cfg, heavy=False, intent="project", user_input="Archer 下一步怎么推进")
    assert "[Soul Profile 摘要]" in prompt
    assert "当前阶段：正在推进 Archer 灵魂伴生体阶段" in prompt
    assert "项目神话：终端是内核，客户端是壳" in prompt


def test_build_system_prompt_does_not_inject_missing_soul_profile():
    cfg = {"persona": {"default_mode": "listener", "modes": {}}, "obsidian": {}}
    prompt = build_system_prompt(cfg, heavy=False, intent="chat", user_input="你好")
    assert "[Soul Profile 摘要]" not in prompt
