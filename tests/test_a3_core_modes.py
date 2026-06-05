"""
A3 — 核心模式系统测试
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _cfg(modes_dir: Path):
    return {"persona": {"default_mode": "listener", "modes_dir": str(modes_dir), "modes": {}}, "obsidian": {}}


def test_core_mode_files_exist_and_describe_roles():
    modes = ROOT / "modes"
    assert "倾听者" in (modes / "listener.md").read_text(encoding="utf-8")
    assert "哲学家" in (modes / "philosopher.md").read_text(encoding="utf-8")
    assert "追问者" in (modes / "questioner.md").read_text(encoding="utf-8")


def test_default_mode_prompt_blends_listener_and_questioner():
    from core.context import build_system_prompt

    prompt = build_system_prompt(_cfg(ROOT / "modes"), heavy=False, intent="chat")
    assert "默认模式行为" in prompt
    assert "Listener" in prompt or "倾听者" in prompt
    assert "Questioner" in prompt or "追问者" in prompt
    assert "先承接" in prompt
    assert "轻轻追问" in prompt


def test_mode_switch_entry_is_documented_as_implemented():
    from core.persona import MODE_SWITCH_DESIGN

    assert "/mode" in MODE_SWITCH_DESIGN
    assert "桌面端" in MODE_SWITCH_DESIGN
    assert "已实现" in MODE_SWITCH_DESIGN
