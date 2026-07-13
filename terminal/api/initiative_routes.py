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


def _initiative_shadow(path: str) -> dict:
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
        store.init_db()
        return {
            "ok": True,
            "shadow": True,
            "delivered": False,
            "limit": limit,
            "globalThrottleActive": is_global_throttle_active(store.DB_PATH),
            "presenceState": get_presence_state(store.DB_PATH),
            "items": list_shadow_logs(store.DB_PATH, limit=limit),
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


def _initiative_shadow_report() -> dict:
    def _build() -> dict:
        import memory.store as store
        from core.initiative_shadow import list_shadow_logs
        from core.shadow_validation import evaluate_shadow_validation

        store.init_db()
        report = evaluate_shadow_validation(list_shadow_logs(store.DB_PATH, limit=100))
        return {"ok": True, "shadow": True, "report": report.to_dict()}

    return _safe_initiative_shadow("report", _build)


def _initiative_shadow_long_term_report() -> dict:
    def _build() -> dict:
        import memory.store as store
        from core.initiative_shadow import list_shadow_logs
        from core.shadow_validation import evaluate_long_term_validation

        store.init_db()
        report = evaluate_long_term_validation(list_shadow_logs(store.DB_PATH, limit=500))
        return {"ok": True, "shadow": True, "report": report.to_dict()}

    return _safe_initiative_shadow("long_term_report", _build)


def _initiative_shadow_delivery_gate() -> dict:
    def _build() -> dict:
        import memory.store as store
        from core.delivery_opt_in import get_delivery_opt_in
        from core.initiative_shadow import list_shadow_logs
        from core.shadow_validation import evaluate_delivery_gate, evaluate_long_term_validation, evaluate_shadow_validation

        store.init_db()
        logs = list_shadow_logs(store.DB_PATH, limit=500)
        manual_report = evaluate_shadow_validation(logs)
        long_term_report = evaluate_long_term_validation(logs)
        opt_in = get_delivery_opt_in(store.DB_PATH)
        gate = evaluate_delivery_gate(manual_report, long_term_report, explicit_opt_in=opt_in.enabled)
        return {"ok": True, "shadow": True, "optIn": opt_in.to_dict(), "gate": gate.to_dict()}

    return _safe_initiative_shadow("delivery_gate", _build)


def _initiative_shadow_review_packet() -> dict:
    def _build() -> dict:
        import memory.store as store
        from core.delivery_opt_in import get_delivery_opt_in
        from core.initiative_shadow import list_shadow_logs
        from core.shadow_validation import evaluate_delivery_gate, evaluate_long_term_validation, evaluate_shadow_validation

        store.init_db()
        logs = list_shadow_logs(store.DB_PATH, limit=500)
        manual_report = evaluate_shadow_validation(logs)
        long_term_report = evaluate_long_term_validation(logs)
        opt_in = get_delivery_opt_in(store.DB_PATH)
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


def _initiative_shadow_feedback(log_id: str, payload: dict) -> tuple[int, dict]:
    import memory.store as store
    from core.initiative_shadow import record_shadow_feedback

    feedback = str(payload.get("feedback") or "").strip()
    if feedback not in {"acknowledged", "too_frequent"}:
        return 400, {"ok": False, "error": "feedback must be acknowledged or too_frequent"}
    try:
        numeric_id = int(log_id)
    except ValueError:
        return 400, {"ok": False, "error": "invalid initiative id"}
    ok = record_shadow_feedback(db_path=store.DB_PATH, log_id=numeric_id, feedback=feedback)
    return (200, {"ok": True, "id": numeric_id, "feedback": feedback}) if ok else (404, {"ok": False, "error": "initiative not found"})


def _initiative_presence(payload: dict) -> tuple[int, dict]:
    import memory.store as store
    from core.presence import set_presence_state

    state = str(payload.get("state") or "").strip()
    if state not in {"idle", "muted", "engaged"}:
        return 400, {"ok": False, "error": "state must be idle, engaged, or muted"}
    result = set_presence_state(store.DB_PATH, state)
    return 200, {"ok": True, "state": result.state, "reason": result.reason}


def _initiative_delivery_opt_in(payload: dict) -> tuple[int, dict]:
    import memory.store as store
    from core.delivery_opt_in import set_delivery_opt_in
    from core.initiative_shadow import list_shadow_logs
    from core.shadow_validation import evaluate_delivery_gate, evaluate_long_term_validation, evaluate_shadow_validation

    if "enabled" not in payload or not isinstance(payload.get("enabled"), bool):
        return 400, {"ok": False, "error": "enabled must be a boolean"}
    opt_in = set_delivery_opt_in(
        store.DB_PATH,
        enabled=bool(payload.get("enabled")),
        reason=str(payload.get("reason") or ""),
    )
    logs = list_shadow_logs(store.DB_PATH, limit=500)
    manual_report = evaluate_shadow_validation(logs)
    long_term_report = evaluate_long_term_validation(logs)
    gate = evaluate_delivery_gate(manual_report, long_term_report, explicit_opt_in=opt_in.enabled)
    return 200, {"ok": True, "shadow": True, "optIn": opt_in.to_dict(), "gate": gate.to_dict()}


# ---------------------------------------------------------------------------

