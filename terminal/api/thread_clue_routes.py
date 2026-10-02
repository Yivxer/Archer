"""Part 8 cue controls; these never mutate conversation threads or consent."""
from __future__ import annotations

from typing import Any

from core.thread_clue_lifecycle import expire_stale_thread_clues, transition_thread_clue


def thread_clue_action(clue_id: str, payload: dict, runtime_context: Any = None) -> tuple[int, dict]:
    from memory.store import DB_PATH

    numeric_id = int(clue_id)
    if not 0 < numeric_id < 2**63:
        return 400, {"ok": False, "error": "invalid thread clue id"}
    db_path = getattr(runtime_context, "db_path", None) or DB_PATH
    now = runtime_context.now() if runtime_context is not None else None
    status = str(payload.get("status") or "")
    from core.thread_clue_lifecycle import TERMINAL_STATES

    if status not in TERMINAL_STATES:
        return 400, {"ok": False, "error": "unsupported thread clue status"}
    try:
        result = transition_thread_clue(db_path, numeric_id, status, now=now)
    except ValueError as exc:
        return 409, {"ok": False, "error": str(exc)}
    if result is None:
        return 404, {"ok": False, "error": "thread clue not found"}
    return 200, {"ok": True, **result}


def thread_clue_expire(payload: dict, runtime_context: Any = None) -> tuple[int, dict]:
    from memory.store import DB_PATH

    days = payload.get("maxIdleDays", 30)
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 365:
        return 400, {"ok": False, "error": "maxIdleDays must be between 1 and 365"}
    db_path = getattr(runtime_context, "db_path", None) or DB_PATH
    now = runtime_context.now() if runtime_context is not None else None
    ids = expire_stale_thread_clues(db_path, max_idle_days=days, now=now)
    return 200, {"ok": True, "expiredIds": ids}
