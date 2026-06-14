"""P5.12 — Plugin bundle install/list/remove tests."""
from __future__ import annotations

import json
import shutil
import textwrap
import zipfile
from pathlib import Path

import pytest

from core.hooks import HookRegistry
from core.plugin import (
    detect_conflicts,
    install_plugin,
    list_installed,
    load_plugin_hook_definitions,
    materialize_plugin_source,
    remove_plugin,
    resolve_plugin_root,
)
from core.stance import available_modes
from skills.loader import register_all_skills, reset_skill_registry


def _write_demo_plugin(root, *, skill_name: str = "demo_hello") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "name": "demo-plugin",
                "version": "1.0.0",
                "description": "Demo bundle",
                "hooks": {
                    "SessionStart": [
                        {"type": "command", "command": "echo '{\"continue\": true}'"},
                    ]
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    skills_dir = root / "skills"
    skills_dir.mkdir()
    (skills_dir / f"{skill_name}.py").write_text(
        textwrap.dedent(
            f"""
            SKILL = {{"name": "{skill_name}", "description": "demo", "risk": "low"}}

            def schema():
                return {{
                    "type": "function",
                    "function": {{
                        "name": "{skill_name}",
                        "description": "demo",
                        "parameters": {{"type": "object", "properties": {{}}}},
                    }},
                }}

            def run(args):
                return "ok"
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    modes_dir = root / "modes"
    modes_dir.mkdir()
    (modes_dir / "demo_mode.md").write_text("[模式：Demo]\n插件模式。", encoding="utf-8")


@pytest.fixture
def plugin_home(tmp_path, monkeypatch):
    plugins_base = tmp_path / "plugins"
    monkeypatch.setattr("core.plugin.plugins_dir", lambda default=None: plugins_base)
    monkeypatch.setattr("core.plugin.ROOT", tmp_path)
    reset_skill_registry()
    yield plugins_base
    reset_skill_registry()


def test_resolve_plugin_root_supports_dot_archer_plugin(tmp_path):
    bundle = tmp_path / "bundle"
    inner = bundle / ".archer-plugin"
    inner.mkdir(parents=True)
    (inner / "plugin.json").write_text('{"name":"x","version":"1.0.0"}', encoding="utf-8")
    assert resolve_plugin_root(bundle) == inner


def test_install_list_remove_plugin(plugin_home, tmp_path):
    source = tmp_path / "src"
    _write_demo_plugin(source)

    record = install_plugin(source, base=plugin_home)
    assert record["name"] == "demo-plugin"
    assert record["skill_count"] == 1
    assert record["mode_count"] == 1

    items = list_installed(plugin_home)
    assert len(items) == 1
    assert items[0]["name"] == "demo-plugin"

    registry = register_all_skills(force=True)
    assert "demo_hello" in registry

    modes = available_modes({"persona": {"modes": {}, "modes_dir": ""}})
    assert "demo_mode" in modes

    remove_plugin("demo-plugin", base=plugin_home)
    assert list_installed(plugin_home) == []


def test_conflict_detects_duplicate_skill(plugin_home, tmp_path):
    source = tmp_path / "src"
    _write_demo_plugin(source, skill_name="file_ops")
    from core.plugin import detect_conflicts, load_manifest, validate_manifest

    manifest = validate_manifest(load_manifest(source))
    issues = detect_conflicts(manifest, source, base=plugin_home)
    assert any("file_ops" in issue for issue in issues)


def test_install_rejects_conflicts(plugin_home, tmp_path):
    source = tmp_path / "src"
    _write_demo_plugin(source, skill_name="file_ops")
    try:
        install_plugin(source, base=plugin_home)
        raise AssertionError("expected conflict")
    except ValueError as exc:
        assert "冲突" in str(exc)


def test_plugin_hooks_merge_into_registry(plugin_home, tmp_path):
    source = tmp_path / "src"
    _write_demo_plugin(source)
    install_plugin(source, base=plugin_home)

    hooks = load_plugin_hook_definitions(plugin_home)
    assert any(h.event == "SessionStart" for h in hooks)

    reg = HookRegistry.from_config({"hooks": {"enabled": True}})
    assert len(reg.for_event("SessionStart")) >= 1


def test_install_from_zip_archive(plugin_home, tmp_path):
    source = tmp_path / "src"
    _write_demo_plugin(source)
    zip_base = tmp_path / "bundle"
    shutil.make_archive(str(zip_base), "zip", root_dir=source)
    zip_path = Path(f"{zip_base}.zip")

    record = install_plugin(zip_path, base=plugin_home)
    assert record["name"] == "demo-plugin"
    assert list_installed(plugin_home)


def test_zip_slip_is_rejected(plugin_home, tmp_path):
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("../escape/plugin.json", '{"name":"x","version":"1.0.0"}')

    with pytest.raises(ValueError, match="越界"):
        install_plugin(zip_path, base=plugin_home)


def test_materialize_local_directory(tmp_path):
    source = tmp_path / "src"
    _write_demo_plugin(source)
    path, cleanup = materialize_plugin_source(source)
    assert resolve_plugin_root(path).name == "src"
    assert cleanup is None
