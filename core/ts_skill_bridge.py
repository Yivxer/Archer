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


def _project_root() -> Path:
    env_root = os.environ.get("ARCHER_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()
    return _PROJECT_ROOT


def _runner_path() -> Path | None:
    candidate = _project_root() / _RUNNER_REL
    return candidate if candidate.is_file() else None


def list_ts_local_skills() -> list[str]:
    """Return skill names registered in the TS runner, or [] if unavailable."""
    node = shutil.which("node")
    runner = _runner_path()
    if not node or not runner:
        return []
    try:
        proc = subprocess.run(
            [node, str(runner), "--list"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(_project_root()),
        )
        if proc.returncode != 0:
            return []
        payload = json.loads(proc.stdout.strip() or "[]")
        return [str(x) for x in payload] if isinstance(payload, list) else []
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return []


def try_execute_ts_skill(skill_name: str, args: dict) -> ToolResult | None:
    """Execute via TS registry when the Desktop runner is built; otherwise None."""
    node = shutil.which("node")
    runner = _runner_path()
    if not node or not runner:
        return None

    try:
        proc = subprocess.run(
            [
                node,
                str(runner),
                skill_name,
                json.dumps(args, ensure_ascii=False),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(_project_root()),
        )
    except (OSError, subprocess.TimeoutExpired):
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
    )
