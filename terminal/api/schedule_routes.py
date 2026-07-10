"""Schedule API handlers backed by an explicit RuntimeContext."""
from __future__ import annotations

import re

from core.runtime_context import RuntimeContext, create_runtime_context


def _context(context: RuntimeContext | None) -> RuntimeContext:
    if context is not None:
        return context
    import memory.store as store
    return create_runtime_context(db_path=store.DB_PATH)


def list_schedules(context: RuntimeContext | None = None) -> dict:
    from core.scheduler import (
        format_task,
        init_schedule_table,
        list_tasks,
        sync_schedules_json,
    )

    runtime = _context(context)
    init_schedule_table(runtime.db_path)
    json_path = sync_schedules_json(
        runtime.db_path,
        now=runtime.now(),
        output_path=runtime.db_path.parent / "schedules.json",
    )
    return {
        "ok": True,
        "jsonPath": str(json_path),
        "tasks": [format_task(task) for task in list_tasks(runtime.db_path)],
    }


def add_schedule(payload: dict, context: RuntimeContext | None = None) -> tuple[int, dict]:
    from core.scheduler import add_task, format_task, get_task, init_schedule_table, parse_interval
    from skills.loader import register_all_skills

    runtime = _context(context)
    init_schedule_table(runtime.db_path)
    skill_name = str(payload.get("skillName") or payload.get("skill_name") or "").strip()
    interval = str(payload.get("interval") or payload.get("intervalSpec") or "").strip()
    label = str(payload.get("label") or "").strip()
    catchup = str(payload.get("catchup") or "latest").strip()
    args = payload.get("args") if isinstance(payload.get("args"), dict) else None
    if not skill_name or not interval:
        return 400, {"ok": False, "error": "skillName and interval are required"}
    if skill_name not in register_all_skills():
        return 400, {"ok": False, "error": f"unknown skill: {skill_name}"}
    try:
        parse_interval(interval)
    except ValueError as exc:
        return 400, {"ok": False, "error": str(exc)}
    task_id = add_task(
        skill_name,
        interval,
        label,
        args=args,
        catchup=catchup,
        db_path=runtime.db_path,
        now=runtime.now(),
        output_path=runtime.db_path.parent / "schedules.json",
    )
    return 200, {"ok": True, "task": format_task(get_task(task_id, runtime.db_path))}


def schedule_action(
    task_id: str,
    action: str,
    payload: dict | None = None,
    context: RuntimeContext | None = None,
) -> tuple[int, dict]:
    from core.scheduler import format_task, get_task, init_schedule_table, remove_task, run_task_by_id, set_enabled
    from skills.loader import register_all_skills

    if not re.fullmatch(r"[0-9]+", task_id):
        return 400, {"ok": False, "error": "task id must be numeric"}
    runtime = _context(context)
    init_schedule_table(runtime.db_path)
    tid = int(task_id)
    task = get_task(tid, runtime.db_path)
    if task is None and action != "remove":
        return 404, {"ok": False, "error": "task_not_found", "id": tid}
    if action == "remove":
        ok = remove_task(
            tid,
            runtime.db_path,
            output_path=runtime.db_path.parent / "schedules.json",
        )
        return (200 if ok else 404), {"ok": ok, "id": tid}
    if action in {"enable", "disable"}:
        ok = set_enabled(
            tid,
            action == "enable",
            runtime.db_path,
            output_path=runtime.db_path.parent / "schedules.json",
        )
        task = get_task(tid, runtime.db_path)
        return 200, {"ok": ok, "task": format_task(task) if task else None}
    if action == "run":
        result = run_task_by_id(
            tid,
            register_all_skills(),
            runtime.db_path,
            now=runtime.now(),
            output_path=runtime.db_path.parent / "schedules.json",
        )
        task = get_task(tid, runtime.db_path)
        if result is None and task is None:
            return 404, {"ok": False, "error": "task_not_found", "id": tid}
        if result is None:
            return 400, {"ok": False, "error": "skill_not_loaded", "id": tid, "skillName": task["skill_name"]}
        return 200, {
            "ok": result.ok,
            "task": format_task(task) if task else None,
            "summary": result.summary,
            "preview": (result.content_preview or "")[:600],
        }
    return 400, {"ok": False, "error": f"unknown action: {action}"}
