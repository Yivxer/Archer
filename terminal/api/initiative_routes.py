"""Part 8 proactive and initiative-shadow API domain."""

from __future__ import annotations

import re
from pathlib import Path

from terminal.api._tools import _failure_hint_event


# Proactive touch route
# ---------------------------------------------------------------------------

def _proactive_touch(cfg: dict) -> dict:
    from core.proactive import scan_proactive_touch
    from core.session import SESSIONS_DIR
    from memory.store import DB_PATH

    proactive_cfg = cfg.get("proactive", {}) if isinstance(cfg.get("proactive", {}), dict) else {}
    enabled = proactive_cfg.get("enabled", True) is not False
    return {
        "enabled": enabled,
        "items": scan_proactive_touch(DB_PATH, Path(SESSIONS_DIR), cfg=cfg) if enabled else [],
    }


def _initiative_shadow(path: str, runtime_context=None) -> dict:
    def _build() -> dict:
        import memory.store as store
        from core.initiative_shadow import is_global_throttle_active, list_shadow_logs
        from core.presence import get_presence_state

        limit_match = re.search(r"(?:\?|&)limit=([0-9]+)", path)
        try:
            limit = int(limit_match.group(1)) if limit_match else 20
        except Exception:
            limit = 20
        limit = max(1, min(limit, 100))
        db_path = getattr(runtime_context, "db_path", store.DB_PATH)
        return {
            "ok": True,
            "shadow": True,
            "delivered": False,
            "limit": limit,
            "globalThrottleActive": is_global_throttle_active(db_path),
            "presenceState": get_presence_state(db_path),
            "items": list_shadow_logs(db_path, limit=limit),
        }

    return _safe_initiative_shadow("list", _build)


def _initiative_shadow_failure(exc: Exception, *, operation: str) -> dict:
    hint = _failure_hint_event(exc, stage=f"initiative_shadow.{operation}")
    return {
        "ok": False,
        "shadow": True,
        "delivered": False,
        "stage": f"initiative_shadow.{operation}",
        "error": str(exc) or type(exc).__name__,
        "failureKeyword": hint.get("keyword", "runtime_failure"),
        "failureHint": hint,
    }


def _safe_initiative_shadow(operation: str, producer) -> dict:
    try:
        return producer()
    except Exception as exc:
        return _initiative_shadow_failure(exc, operation=operation)


def _initiative_shadow_report(runtime_context=None) -> dict:
    def _build() -> dict:
        import memory.store as store
        from core.initiative_shadow import list_shadow_logs
        from core.shadow_validation import evaluate_shadow_validation

        db_path = getattr(runtime_context, "db_path", store.DB_PATH)
        now = runtime_context.now() if runtime_context is not None else None
        report = evaluate_shadow_validation(list_shadow_logs(db_path, limit=100), now=now)
        return {"ok": True, "shadow": True, "report": report.to_dict()}

    return _safe_initiative_shadow("report", _build)


def _initiative_shadow_long_term_report(runtime_context=None) -> dict:
    def _build() -> dict:
        import memory.store as store
        from core.initiative_shadow import list_shadow_logs
        from core.shadow_validation import evaluate_long_term_validation

        db_path = getattr(runtime_context, "db_path", store.DB_PATH)
        now = runtime_context.now() if runtime_context is not None else None
        report = evaluate_long_term_validation(list_shadow_logs(db_path, limit=500), now=now)
        return {"ok": True, "shadow": True, "report": report.to_dict()}

    return _safe_initiative_shadow("long_term_report", _build)


def _initiative_shadow_delivery_gate(runtime_context=None) -> dict:
    def _build() -> dict:
        import memory.store as store
        from core.delivery_opt_in import get_delivery_opt_in
        from core.initiative_shadow import list_shadow_logs
        from core.shadow_validation import evaluate_delivery_gate, evaluate_long_term_validation, evaluate_shadow_validation

        db_path = getattr(runtime_context, "db_path", store.DB_PATH)
        now = runtime_context.now() if runtime_context is not None else None
        logs = list_shadow_logs(db_path, limit=500)
        manual_report = evaluate_shadow_validation(logs, now=now)
        long_term_report = evaluate_long_term_validation(logs, now=now)
        opt_in = get_delivery_opt_in(db_path)
        gate = evaluate_delivery_gate(manual_report, long_term_report, explicit_opt_in=opt_in.enabled)
        return {"ok": True, "shadow": True, "optIn": opt_in.to_dict(), "gate": gate.to_dict()}

    return _safe_initiative_shadow("delivery_gate", _build)


def _initiative_shadow_review_packet(runtime_context=None) -> dict:
    def _build() -> dict:
        import memory.store as store
        from core.delivery_opt_in import get_delivery_opt_in
        from core.initiative_shadow import list_shadow_logs
        from core.shadow_validation import evaluate_delivery_gate, evaluate_long_term_validation, evaluate_shadow_validation

        db_path = getattr(runtime_context, "db_path", store.DB_PATH)
        now = runtime_context.now() if runtime_context is not None else None
        logs = list_shadow_logs(db_path, limit=500)
        manual_report = evaluate_shadow_validation(logs, now=now)
        long_term_report = evaluate_long_term_validation(logs, now=now)
        opt_in = get_delivery_opt_in(db_path)
        delivery_gate = evaluate_delivery_gate(manual_report, long_term_report, explicit_opt_in=opt_in.enabled)
        recommended_action = "manual_opt_in_available" if delivery_gate.can_enable_delivery else "keep_shadow"
        return {
            "ok": True,
            "shadow": True,
            "optIn": opt_in.to_dict(),
            "recommendedAction": recommended_action,
            "manualReport": manual_report.to_dict(),
            "longTermReport": long_term_report.to_dict(),
            "deliveryGate": delivery_gate.to_dict(),
        }

    return _safe_initiative_shadow("review_packet", _build)


def _initiative_shadow_feedback(log_id: str, payload: dict, runtime_context=None) -> tuple[int, dict]:
    import memory.store as store
    from core.initiative_feedback import normalize_surface, record_interaction
    from core.initiative_shadow import record_shadow_feedback

    feedback = str(payload.get("feedback") or "").strip()
    if feedback not in {"acknowledged", "too_frequent"}:
        return 400, {"ok": False, "error": "feedback must be acknowledged or too_frequent"}
    try:
        numeric_id = int(log_id)
    except ValueError:
        return 400, {"ok": False, "error": "invalid initiative id"}
    try:
        surface = normalize_surface(payload.get("surface"))
    except ValueError as exc:
        return 400, {"ok": False, "error": str(exc)}
    db_path = getattr(runtime_context, "db_path", store.DB_PATH)
    now = runtime_context.now() if runtime_context is not None else None
    ok = record_shadow_feedback(db_path=db_path, log_id=numeric_id, feedback=feedback, now=now)
    if ok:
        record_interaction(
            db_path,
            event_type="feedback",
            surface=surface,
            value=feedback,
            initiative_log_id=numeric_id,
            now=now,
        )
    return (200, {"ok": True, "id": numeric_id, "feedback": feedback}) if ok else (404, {"ok": False, "error": "initiative not found"})


def _initiative_presence(payload: dict, runtime_context=None) -> tuple[int, dict]:
    import memory.store as store
    from core.initiative_feedback import normalize_surface, record_interaction
    from core.presence import set_presence_state

    state = str(payload.get("state") or "").strip()
    if state not in {"idle", "muted", "engaged"}:
        return 400, {"ok": False, "error": "state must be idle, engaged, or muted"}
    try:
        surface = normalize_surface(payload.get("surface"))
    except ValueError as exc:
        return 400, {"ok": False, "error": str(exc)}
    db_path = getattr(runtime_context, "db_path", store.DB_PATH)
    now = runtime_context.now() if runtime_context is not None else None
    result = set_presence_state(db_path, state, now=now)
    if state in {"muted", "idle"}:
        record_interaction(
            db_path,
            event_type="mute" if state == "muted" else "unmute",
            surface=surface,
            value=state,
            now=now,
        )
    return 200, {"ok": True, "state": result.state, "reason": result.reason}


def _initiative_review_candidate(payload: dict, runtime_context=None) -> tuple[int, dict]:
    import memory.store as store
    from core.initiative_feedback import claim_review_candidate, normalize_surface

    try:
        surface = normalize_surface(payload.get("surface"), default="chat_workspace")
    except ValueError as exc:
        return 400, {"ok": False, "error": str(exc)}
    if surface != "chat_workspace":
        return 400, {"ok": False, "error": "review candidate surface must be chat_workspace"}
    db_path = getattr(runtime_context, "db_path", store.DB_PATH)
    now = runtime_context.now() if runtime_context is not None else None
    return 200, claim_review_candidate(db_path, surface=surface, now=now)


def _initiative_exposure_report(path: str, runtime_context=None) -> dict:
    def _build() -> dict:
        import memory.store as store
        from core.initiative_feedback import exposure_report, normalize_surface

        surface_match = re.search(r"(?:\?|&)surface=([a-z0-9_-]+)", path)
        days_match = re.search(r"(?:\?|&)days=([0-9]+)", path)
        surface = normalize_surface(surface_match.group(1) if surface_match else "chat_workspace")
        days = int(days_match.group(1)) if days_match else 14
        db_path = getattr(runtime_context, "db_path", store.DB_PATH)
        now = runtime_context.now() if runtime_context is not None else None
        return {"ok": True, "shadow": True, "report": exposure_report(db_path, surface=surface, days=days, now=now)}

    return _safe_initiative_shadow("exposure_report", _build)


def _companion_pending(runtime_context=None) -> tuple[int, dict]:
    import memory.store as store
    from core.memory_grounded_companion import pending_companion_message

    db_path = getattr(runtime_context, "db_path", store.DB_PATH)
    item = pending_companion_message(db_path)
    return 200, {"ok": True, "item": item}


def _companion_respond(log_id: str, payload: dict, runtime_context=None) -> tuple[int, dict]:
    import memory.store as store
    from core.memory_grounded_companion import ALLOWED_RESPONSES, respond_to_companion

    try:
        numeric_id = int(log_id)
    except ValueError:
        return 400, {"ok": False, "error": "invalid companion message id"}
    response = str(payload.get("response") or "").strip()
    if response not in ALLOWED_RESPONSES:
        return 400, {"ok": False, "error": "unsupported companion response"}
    db_path = getattr(runtime_context, "db_path", store.DB_PATH)
    now = runtime_context.now() if runtime_context is not None else None
    result = respond_to_companion(
        db_path,
        numeric_id,
        response,
        detail=str(payload.get("detail") or ""),
        now=now,
    )
    if result is None:
        return 404, {"ok": False, "error": "companion message not found"}
    return 200, {"ok": True, **result}


def _initiative_delivery_opt_in(payload: dict, runtime_context=None) -> tuple[int, dict]:
    import memory.store as store
    from core.initiative_delivery import (
        cancel_pending_thread_resume,
        newest_undelivered_thread_resume,
        queue_thread_resume,
    )
    from core.delivery_opt_in import set_delivery_opt_in
    from core.initiative_shadow import list_shadow_logs
    from core.shadow_validation import evaluate_delivery_gate, evaluate_long_term_validation, evaluate_shadow_validation

    if "enabled" not in payload or not isinstance(payload.get("enabled"), bool):
        return 400, {"ok": False, "error": "enabled must be a boolean"}
    db_path = getattr(runtime_context, "db_path", store.DB_PATH)
    now = runtime_context.now() if runtime_context is not None else None
    enabled = bool(payload.get("enabled"))
    opt_in = set_delivery_opt_in(
        db_path,
        enabled=enabled,
        reason=str(payload.get("reason") or ""),
        now=now,
    )
    cancelled = cancel_pending_thread_resume(db_path, now=now) if not enabled else 0
    logs = list_shadow_logs(db_path, limit=500)
    manual_report = evaluate_shadow_validation(logs, now=now)
    long_term_report = evaluate_long_term_validation(logs, now=now)
    gate = evaluate_delivery_gate(manual_report, long_term_report, explicit_opt_in=opt_in.enabled)
    delivery = None
    if enabled and gate.can_enable_delivery:
        candidate = newest_undelivered_thread_resume(db_path)
        if candidate is not None:
            delivery = queue_thread_resume(db_path, candidate["id"], now=now)
    return 200, {
        "ok": True,
        "shadow": not bool(delivery and delivery.get("delivered")),
        "optIn": opt_in.to_dict(),
        "gate": gate.to_dict(),
        "delivery": delivery,
        "cancelled": cancelled,
    }


# ---------------------------------------------------------------------------
