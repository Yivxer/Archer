from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "docs" / "part8-module-graduation.json"
IGNORED_PARTS = {".git", ".venv", ".worktrees", "node_modules", "tests", "__pycache__"}


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _production_python_files() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*.py")
        if not IGNORED_PARTS.intersection(path.relative_to(ROOT).parts)
    ]


def _external_calls(module_names: set[str], entrypoints: set[str], owner_files: set[str]) -> set[str]:
    calls: set[str] = set()
    for path in _production_python_files():
        relative = path.relative_to(ROOT).as_posix()
        if relative in owner_files:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        direct_names: dict[str, str] = {}
        module_aliases: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in module_names:
                for alias in node.names:
                    if alias.name in entrypoints:
                        direct_names[alias.asname or alias.name] = alias.name
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in module_names:
                        module_aliases.add(alias.asname or alias.name.rsplit(".", 1)[-1])
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id in direct_names:
                calls.add(f"{relative}:{direct_names[node.func.id]}")
            elif (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in entrypoints
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in module_aliases
            ):
                calls.add(f"{relative}:{node.func.attr}")
    return calls


def test_production_scan_excludes_independent_worktrees(tmp_path, monkeypatch):
    monkeypatch.setattr(__import__(__name__, fromlist=["ROOT"]), "ROOT", tmp_path)
    live = tmp_path / "core" / "live.py"
    archived = tmp_path / ".worktrees" / "old" / "core" / "live.py"
    for path in (live, archived):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pass\n", encoding="utf-8")
    assert _production_python_files() == [live]


@pytest.mark.contract
def test_part8_graduation_registry_names_every_audited_module_and_live_slice():
    registry = _registry()

    assert set(registry["modules"]) == {
        "attention",
        "threshold",
        "opportunity",
        "creative",
        "retention",
    }
    assert all(module["state"] == "frozen" for module in registry["modules"].values())
    assert registry["activeVerticalSlices"]["thread_resume"] == {
        "state": "shadow",
        "producer": "core.part8_threads.scan_thread_resume_candidates",
        "productionCaller": "terminal.api.part8_runtime._yield_shadow_initiative_events",
        "eventType": "initiativeEvent",
        "delivered": False,
    }


@pytest.mark.contract
def test_frozen_part8_entrypoints_have_no_external_production_callers():
    registry = _registry()
    violations: dict[str, set[str]] = {}

    for name, module in registry["modules"].items():
        owner_files = set(module["files"])
        module_names = {
            path.removesuffix(".py").replace("/", ".")
            for path in owner_files
        }
        calls = _external_calls(module_names, set(module["entrypoints"]), owner_files)
        if calls:
            violations[name] = calls

    assert violations == {}, (
        "A frozen Part 8 entrypoint gained a production caller. "
        "Graduate it into a named vertical slice before wiring it: "
        f"{violations}"
    )
