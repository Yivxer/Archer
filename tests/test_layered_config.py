"""P5.7 — Layered config merge tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.context import build_system_prompt
from core.layered_config import (
    extract_markdown_section,
    load_layered_file,
    load_project_archer_layers,
    load_project_persona_layers,
    merge_layered_markdown,
    resolve_project_root,
)
from core.persona import build_core_persona


def test_merge_layered_markdown_appends_override():
    merged = merge_layered_markdown("base text", "override text", label="local")
    assert "base text" in merged
    assert "[local override]" in merged
    assert "override text" in merged


def test_load_layered_file_merges_local_sibling(tmp_path):
    base = tmp_path / "COVENANT.md"
    local = tmp_path / "COVENANT.local.md"
    base.write_text("base covenant", encoding="utf-8")
    local.write_text("personal covenant", encoding="utf-8")

    text = load_layered_file(str(base))
    assert "base covenant" in text
    assert "personal covenant" in text


def test_load_layered_file_missing_paths_are_safe():
    assert load_layered_file("") == ""
    assert load_layered_file(str(Path("/tmp/does-not-exist-covenant.md"))) == ""


def test_project_archer_layers_merge_order(tmp_path):
    (tmp_path / "ARCHER.md").write_text("project rules", encoding="utf-8")
    (tmp_path / "ARCHER.local.md").write_text("personal project rules", encoding="utf-8")

    merged = load_project_archer_layers(project_root=tmp_path)
    assert merged.index("project rules") < merged.index("personal project rules")
    assert "[ARCHER.local override]" in merged


def test_resolve_project_root_prefers_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHER_PROJECT_ROOT", str(tmp_path))
    assert resolve_project_root() == tmp_path.resolve()


def test_build_system_prompt_includes_project_archer(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHER_PROJECT_ROOT", str(tmp_path))
    (tmp_path / "ARCHER.md").write_text("keep commits small", encoding="utf-8")

    cfg = {
        "persona": {
            "default_mode": "coach",
            "modes": {"coach": {"name": "教练", "prompt": "coach mode"}},
        }
    }
    prompt = build_system_prompt(cfg, heavy=False)
    assert "keep commits small" in prompt
    assert "context:archer_project" in prompt


def test_build_core_persona_merges_archer_persona_section(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHER_PROJECT_ROOT", str(tmp_path))
    (tmp_path / "ARCHER.md").write_text(
        "## Persona\nAlways answer in one paragraph.\n\n## Project\nOther stuff",
        encoding="utf-8",
    )

    cfg = {"persona": {}}
    persona = build_core_persona(cfg=cfg)
    assert "Always answer in one paragraph." in persona
    assert "[ARCHER.persona override]" in persona
    assert "Other stuff" not in persona


def test_extract_markdown_section_is_case_insensitive():
    text = "## Persona\nOne line\n\n## Other\nignored"
    assert extract_markdown_section(text, "persona") == "One line"


def test_load_project_persona_layers_without_heading_uses_full_file(tmp_path):
    (tmp_path / "ARCHER.md").write_text("single-layer persona note", encoding="utf-8")
    layers = load_project_persona_layers(project_root=tmp_path)
    assert layers == "single-layer persona note"
