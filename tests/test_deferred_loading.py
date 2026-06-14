"""P5.5 — Deferred skill loading tests."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


def _write_skill(path: Path, name: str, *, body: str = "") -> None:
    path.write_text(
        textwrap.dedent(
            f"""
            SKILL = {{"name": "{name}", "description": "{name} skill", "risk": "low"}}
            __meta__ = {{"name": "{name}", "keywords": ["{name}"], "auto_trigger": True}}

            def schema():
                return {{
                    "type": "function",
                    "function": {{
                        "name": "{name}",
                        "description": "{name}",
                        "parameters": {{"type": "object", "properties": {{}}}},
                    }},
                }}

            def run(args):
                return "{name}-ok"
            {body}
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def skill_dir(tmp_path, monkeypatch):
    import skills.loader as loader

    monkeypatch.setattr(loader, "SKILLS_DIR", tmp_path)
    loader.reset_skill_registry()
    yield tmp_path
    loader.reset_skill_registry()


def test_register_all_skills_does_not_import_modules(skill_dir, monkeypatch):
    import skills.loader as loader

    _write_skill(skill_dir / "alpha.py", "alpha")
    _write_skill(skill_dir / "beta.py", "beta")

    calls = {"count": 0}
    real_load = loader._load_module

    def counting_load(path):
        calls["count"] += 1
        return real_load(path)

    monkeypatch.setattr(loader, "_load_module", counting_load)

    registry = loader.register_all_skills(force=True)

    assert set(registry.keys()) == {"alpha", "beta"}
    assert registry.get_meta("alpha").description == "alpha skill"
    assert calls["count"] == 0


def test_load_skill_full_imports_on_first_access(skill_dir, monkeypatch):
    import skills.loader as loader

    _write_skill(skill_dir / "alpha.py", "alpha")
    loader.register_all_skills(force=True)

    calls = {"count": 0}
    real_load = loader._load_module

    def counting_load(path):
        calls["count"] += 1
        return real_load(path)

    monkeypatch.setattr(loader, "_load_module", counting_load)

    mod = loader.load_skill_full("alpha")
    again = loader.load_skill_full("alpha")

    assert mod.run({}) == "alpha-ok"
    assert again is mod
    assert calls["count"] == 1


def test_lru_cache_evicts_least_recently_used(skill_dir, monkeypatch):
    import skills.loader as loader

    monkeypatch.setenv("ARCHER_SKILL_CACHE_SIZE", "2")
    _write_skill(skill_dir / "a.py", "a")
    _write_skill(skill_dir / "b.py", "b")
    _write_skill(skill_dir / "c.py", "c")
    loader.register_all_skills(force=True)

    calls = {"count": 0}
    real_load = loader._load_module

    def counting_load(path):
        calls["count"] += 1
        return real_load(path)

    monkeypatch.setattr(loader, "_load_module", counting_load)

    loader.load_skill_full("a")
    loader.load_skill_full("b")
    loader.load_skill_full("c")
    loader.load_skill_full("a")

    assert calls["count"] == 4


def test_get_tools_only_loads_selected_subset(skill_dir, monkeypatch):
    import skills.loader as loader

    _write_skill(skill_dir / "alpha.py", "alpha")
    _write_skill(skill_dir / "beta.py", "beta")
    registry = loader.register_all_skills(force=True)

    calls = {"count": 0}
    real_load = loader._load_module

    def counting_load(path):
        calls["count"] += 1
        return real_load(path)

    monkeypatch.setattr(loader, "_load_module", counting_load)

    tools = loader.get_tools(registry.resolve_subset({"alpha"}))

    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "alpha"
    assert calls["count"] == 1


def test_auto_match_skills_uses_meta_without_full_import(skill_dir, monkeypatch):
    import skills.loader as loader
    from core.skill_router import auto_match_skills

    _write_skill(skill_dir / "alpha.py", "alpha")
    _write_skill(skill_dir / "beta.py", "beta")
    registry = loader.register_all_skills(force=True)

    calls = {"count": 0}
    real_load = loader._load_module

    def counting_load(path):
        calls["count"] += 1
        return real_load(path)

    monkeypatch.setattr(loader, "_load_module", counting_load)

    matched = auto_match_skills("请用 alpha 查一下", all_skills=registry)

    assert "alpha" in matched
    assert calls["count"] == 0


def test_load_skills_registry_still_supports_full_iteration(skill_dir):
    import skills.loader as loader

    _write_skill(skill_dir / "alpha.py", "alpha")
    registry = loader.register_all_skills(force=True)

    mod = registry["alpha"]
    assert hasattr(mod, "schema")
    assert hasattr(mod, "run")
