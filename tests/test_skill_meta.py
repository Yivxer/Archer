"""
P5.3 — Skill metadata and auto-match tests
"""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _mock_module(name: str, *, meta: dict | None = None, skill: dict | None = None):
    mod = types.ModuleType(name)
    mod.SKILL = skill or {"name": name, "description": f"{name} skill"}
    if meta is not None:
        mod.__meta__ = meta
    mod.schema = lambda: {"type": "function", "function": {"name": name}}
    mod.run = lambda args: "ok"
    return mod


def test_parse_skill_meta_merges_skill_and_meta():
    from skills.meta import parse_skill_meta

    mod = _mock_module(
        "web_search",
        skill={"name": "web_search", "description": "from skill", "risk": "low"},
        meta={"keywords": ["搜索", "查一下"], "model_preference": "fast"},
    )
    meta = parse_skill_meta(mod)
    assert meta is not None
    assert meta.name == "web_search"
    assert meta.description == "from skill"
    assert "搜索" in meta.keywords
    assert meta.model_preference == "fast"


def test_loader_get_skill_meta_from_real_skill():
    from skills.loader import load_skills, get_skill_meta

    skills = load_skills()
    assert "web_search" in skills
    meta = get_skill_meta(skills["web_search"])
    assert meta.name == "web_search"
    assert meta.keywords


def test_auto_match_skills_uses_meta_keywords():
    from core.skill_router import auto_match_skills

    skills = {
        "web_search": _mock_module(
            "web_search",
            meta={"keywords": ["官方文档", "报错"], "auto_trigger": True},
        ),
        "weather": _mock_module("weather", meta={"keywords": ["天气"], "auto_trigger": True}),
    }
    matched = auto_match_skills("这个报错怎么解决", intent="task", all_skills=skills)
    assert "web_search" in matched
    assert "weather" not in matched


def test_auto_match_respects_auto_trigger_false():
    from core.skill_router import auto_match_skills

    skills = {
        "hidden_skill": _mock_module(
            "hidden_skill",
            meta={"keywords": ["secret"], "auto_trigger": False},
        )
    }
    matched = auto_match_skills("secret keyword only", all_skills=skills)
    assert matched == []


def test_orchestrator_includes_matched_skills_for_code_task():
    from core.orchestrator import orchestrate_user_input, format_matched_skills_for_prompt

    result = orchestrate_user_input("帮我在代码里找 invite 验证逻辑")
    assert isinstance(result.matched_skills, list)
    block = format_matched_skills_for_prompt(result.matched_skills)
    if result.matched_skills:
        assert "[本轮可能相关的技能]" in block


def test_orchestrator_event_includes_matched_skills():
    from core.orchestrator import orchestrate_user_input, orchestration_to_event_dict

    result = orchestrate_user_input("搜索一下 TypeScript 泛型写法")
    event = orchestration_to_event_dict(result)
    assert "matchedSkills" in event
    assert isinstance(event["matchedSkills"], list)


def test_build_system_prompt_injects_matched_skills_block():
    from core.context import build_system_prompt

    prompt = build_system_prompt(
        {"persona": {"default_mode": "coach", "current_mode": "coach", "mode_auto": True, "modes_dir": ""}},
        matched_skills_block="[本轮可能相关的技能]\n- web_search: demo",
    )
    assert "orchestration.skills" in prompt or "web_search" in prompt


if __name__ == "__main__":
    tests = [
        test_parse_skill_meta_merges_skill_and_meta,
        test_loader_get_skill_meta_from_real_skill,
        test_auto_match_skills_uses_meta_keywords,
        test_auto_match_respects_auto_trigger_false,
        test_orchestrator_includes_matched_skills_for_code_task,
        test_orchestrator_event_includes_matched_skills,
        test_build_system_prompt_injects_matched_skills_block,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
            passed += 1
        except Exception as e:
            import traceback
            print(f"  [FAIL] {t.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
