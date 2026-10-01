"""Run committed Archer tests in a disposable checkout with synthetic state."""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path

import tomli_w

ROOT = Path(__file__).resolve().parents[1]
SUITES = {
    "smoke": ["tests/test_smoke.py"],
    "foundation": [
        "tests/test_foundation_memory.py",
        "tests/test_memory_continuity_j8.py",
        "tests/test_context_assembly.py",
        "tests/test_persona_sources.py",
        "tests/test_persona_recall.py",
        "tests/test_journey_smoke_script.py",
        "tests/test_reflect.py",
        "tests/test_offline_runner.py",
        "tests/test_obsidian_write_preview.py",
        "tests/test_desktop_tool_router.py",
        "tests/test_user_outcome_confirmation.py",
        "tests/test_foundation_api_restart.py",
        "tests/test_thread_store.py",
        "tests/test_tool_approval_cache_replay.py",
    ],
    "full": [],
}


def prepare_config(checkout: Path) -> None:
    """Use the public template only; never copy user configuration or sources."""
    config = tomllib.loads((checkout / "templates/archer.example.toml").read_text())
    for profile in [config["api"], *config["model_profiles"].values()]:
        profile.update(base_url="http://127.0.0.1:9/v1", api_key_ref="env:ARCHER_OFFLINE_EMPTY")
    persona = checkout / "private/offline-persona"
    persona.mkdir(parents=True)
    for field, name in {
        "soul_path": "SOUL.md", "memory_path": "MEMORY.md",
        "covenant_path": "COVENANT.md", "presence_path": "PRESENCE.md",
    }.items():
        path = persona / name
        path.write_text(f"# {name}\n脱敏测试：项目代号青禾；先核对备份，再安装。\n")
        config["persona"][field] = str(path)
        # Some legacy paths use root-relative fallback instead of configuration.
        (checkout / name).write_text(path.read_text())
    profile = checkout / "memory/SOUL_PROFILE.json"
    profile.parent.mkdir(exist_ok=True)
    profile.write_text(json.dumps({"identity": {"name": "测试用户"}}, ensure_ascii=False))
    config["persona"]["soul_profile_path"] = str(profile)
    config["persona"]["history"] = {
        "covenant_dir": str(persona / "history/covenant"),
        "presence_dir": str(persona / "history/presence"),
    }
    config["memory"]["db_path"] = str(checkout / "memory/offline.db")
    config["paths"] = {
        "sessions_dir": str(checkout / "memory/offline-sessions"),
        "blog_dir": str(checkout / "private/offline-blog"),
    }
    config["obsidian"]["vault_path"] = str(checkout / "private/offline-vault")
    for path in [config["paths"]["sessions_dir"], config["paths"]["blog_dir"],
                 config["obsidian"]["vault_path"]]:
        Path(path).mkdir(parents=True)
    (checkout / "archer.toml").write_text(tomli_w.dumps(config))


def protected_roots(root: Path) -> list[str]:
    """Find private roots without copying any private configuration content."""
    protected = [root.resolve(), Path.home() / "Library/Application Support/archer-desktop"]
    config_path = root / "archer.toml"
    if config_path.exists():
        config = tomllib.loads(config_path.read_text())
        for section, fields in {
            "persona": ["soul_path", "memory_path", "covenant_path", "presence_path", "soul_profile_path"],
            "memory": ["db_path"], "obsidian": ["vault_path"],
            "paths": ["sessions_dir", "blog_dir"],
        }.items():
            for field in fields:
                value = config.get(section, {}).get(field)
                if value:
                    path = Path(value).expanduser()
                    protected.append((path if path.is_absolute() else root / path).resolve())
    return [str(path) for path in protected]


def run(suite: str, ref: str, report: Path | None) -> int:
    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=ROOT, text=True
    ).strip()
    archive = subprocess.check_output(["git", "archive", commit], cwd=ROOT)
    # Legacy macOS Markdown routing deliberately recognizes /Users/ paths.
    temporary_root = Path.home() / ".codex/tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="archer-offline-", dir=temporary_root) as temporary:
        workspace = Path(temporary)
        checkout = workspace / "source"
        checkout.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(checkout, filter="data")
        subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
        subprocess.run(["git", "add", "."], cwd=checkout, check=True)
        prepare_config(checkout)
        bootstrap = workspace / "bootstrap"
        bootstrap.mkdir()
        shutil.copy2(ROOT / "scripts/offline_test_guard.py", bootstrap)
        (bootstrap / "sitecustomize.py").write_text("from offline_test_guard import install\ninstall()\n")
        scratch = workspace / "tmp"
        scratch.mkdir()
        environment = os.environ.copy()
        environment.pop("ARCHER_OFFLINE_EMPTY", None)
        environment.update(
            PYTHONPATH=str(bootstrap), PYTHONDONTWRITEBYTECODE="1",
            TMPDIR=str(scratch), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
            ARCHER_OFFLINE_PROTECTED_ROOTS=json.dumps(protected_roots(ROOT)),
        )
        command = [sys.executable, "-m", "pytest", *SUITES[suite],
                   "-m", "not integration and not journey", "-o", "addopts=", "-q",
                   "--basetemp", str(scratch / "pytest")]
        print(f"Offline suite={suite}; committed source={commit}; disposable synthetic state", flush=True)
        result = subprocess.run(command, cwd=checkout, env=environment, check=False)
        if report:
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps({
                "suite": suite, "sourceCommit": commit, "exitCode": result.returncode,
                "syntheticState": True, "externalModelsRequested": False,
                "guards": "Python audit hooks; not an OS sandbox",
            }, indent=2))
        return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=SUITES, default="smoke")
    parser.add_argument("--ref", default="HEAD", help="committed source, excludes uncommitted edits")
    parser.add_argument("--report", type=Path, help="optional metadata report outside disposable state")
    args = parser.parse_args()
    return run(args.suite, args.ref, args.report)


if __name__ == "__main__":
    raise SystemExit(main())
