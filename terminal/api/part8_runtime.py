"""RuntimeContext-aware Part 8 chat-side helpers."""
from __future__ import annotations

from core.runtime_context import RuntimeContext


def _initiative_event_from_log(log: dict) -> dict:
    trace = log.get("decision_trace") if isinstance(log.get("decision_trace"), dict) else {}
    return {
        "id": f"initiative-{log.get('id')}",
        "kind": str(log.get("kind") or ""),
        "title": str(log.get("title") or ""),
        "message": str(log.get("message") or ""),
        "shadow": True,
        "delivered": bool(log.get("delivered", False)),
        "decisionTrace": trace,
        "createdAt": str(log.get("created_at") or ""),
    }


def _runtime_values(runtime_context: RuntimeContext | None):
    if runtime_context is not None:
        return runtime_context.db_path, runtime_context.now()
    import memory.store as store
    return store.DB_PATH, None


def _yield_shadow_initiative_events(runtime_context: RuntimeContext | None = None):
    """Emit Part 8 contract events without delivering them outside Archer."""
    try:
        from core.part8_threads import scan_thread_resume_candidates

        db_path, now = _runtime_values(runtime_context)
        for log in scan_thread_resume_candidates(db_path=db_path, now=now):
            try:
                from core.initiative_delivery import queue_thread_resume
                from core.initiative_shadow import get_shadow_log

                queue_thread_resume(db_path, int(log["id"]), now=now)
                log = get_shadow_log(db_path, int(log["id"])) or log
            except Exception:
                pass
            yield {
                "type": "initiativeEvent",
                "initiativeEvent": _initiative_event_from_log(log),
            }
    except Exception:
        return


def _record_part8_shadow_material(
    messages: list[dict],
    runtime_context: RuntimeContext | None = None,
) -> None:
    """Record shadow-only monologue and continuity clues in the selected DB."""
    try:
        from core.monologue import generate_monologue
        from core.part8_clues import record_thread_clues_from_messages

        db_path, now = _runtime_values(runtime_context)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        generate_monologue(db_path=db_path, messages=messages, now=now)
        record_thread_clues_from_messages(db_path=db_path, messages=messages, now=now)
    except Exception:
        return
