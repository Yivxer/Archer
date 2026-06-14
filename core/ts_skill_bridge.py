"""Bridge Python tool runtime to Desktop TS local skills via a Node subprocess."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from core.tool_runtime import ToolResult

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_RUNNER_REL = Path("client/desktop/out/main/runLocalSkill.js")
_RUNNER_TS = Path("client/desktop/src/main/runLocalSkill.ts")
_TSX_CLI = Path("client/desktop/node_modules/tsx/dist/cli.mjs")


def _project_root() -> Path:
    env_root = os.environ.get("ARCHER_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()
    return _PROJECT_ROOT


def runner_mode() -> str:
    """Return how the TS runner would be invoked: built | dev | unavailable."""
    root = _project_root()
    if (root / _RUNNER_REL).is_file():
        return "built"
    node = shutil.which("node")
    ts_src = root / _RUNNER_TS
    if node and ts_src.is_file() and (root / _TSX_CLI).is_file():
        return "dev"
    return "unavailable"


def _runner_argv() -> list[str] | None:
    """Resolve Node command argv prefix for the local skill runner."""
    node = shutil.which("node")
    if not node:
        return None

    root = _project_root()
    built = root / _RUNNER_REL
    if built.is_file():
        return [node, str(built)]

    ts_src = root / _RUNNER_TS
    tsx_cli = root / _TSX_CLI
    if ts_src.is_file() and tsx_cli.is_file():
        return [node, str(tsx_cli), str(ts_src)]

    return None


def _run_runner(extra_args: list[str], *, timeout: int) -> subprocess.CompletedProcess | None:
    argv = _runner_argv()
    if not argv:
        return None
    try:
        return subprocess.run(
            [*argv, *extra_args],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(_project_root()),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def list_ts_local_skills() -> list[str]:
    """Return skill names registered in the TS runner, or [] if unavailable."""
    proc = _run_runner(["--list"], timeout=10)
    if proc is None or proc.returncode != 0:
        return []
    try:
        payload = json.loads((proc.stdout or "").strip() or "[]")
        return [str(x) for x in payload] if isinstance(payload, list) else []
    except json.JSONDecodeError:
        return []


def try_execute_ts_skill(skill_name: str, args: dict) -> ToolResult | None:
    """Execute via TS registry when the Desktop runner is available; otherwise None."""
    proc = _run_runner(
        [skill_name, json.dumps(args, ensure_ascii=False)],
        timeout=30,
    )
    if proc is None:
        return None

    stdout = (proc.stdout or "").strip()
    if not stdout:
        return None

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    if payload.get("fallback") is True:
        return None

    ok = bool(payload.get("ok"))
    output = str(payload.get("output") or "")
    error = payload.get("error")
    summary = output.split("\n", 1)[0][:200] if output else str(error or "TS skill finished")
    runtime_meta = {"runtime": "ts", "runner": runner_mode()}
    if not ok:
        return ToolResult(
            ok=False,
            skill=skill_name,
            summary=summary,
            content_preview=output,
            error={
                "type": "TsSkillError",
                "message": str(error or summary),
                "retryable": False,
            },
            meta=runtime_meta,
        )

    max_inline = 12_000
    truncated = len(output) > max_inline
    preview = output[:max_inline] if truncated else output
    return ToolResult(
        ok=True,
        skill=skill_name,
        summary=summary,
        content_preview=preview,
        truncated=truncated,
        tokens_estimate=max(1, len(output) // 4),
        meta=runtime_meta,
    )
