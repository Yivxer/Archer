"""Opt-in in-app delivery for the sole Part 8 live slice: thread_resume."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from core.delivery_opt_in import get_delivery_opt_in
from core.initiative_shadow import (
    count_delivered_today,
    get_shadow_log,
    list_shadow_logs,
    mark_initiative_delivered,
)
from core.presence import get_presence_state
from core.shadow_validation import (
    DEFAULT_REQUIRED_DELIVERY_OBSERVATION_DAYS,
    evaluate_delivery_gate,
    evaluate_long_term_validation,
    evaluate_shadow_validation,
)
from core.thread_clue_lifecycle import thread_clue_allows_delivery
from infrastructure.observability import trace_span
from infrastructure.outbox import (
    approve,
    cancel,
    claim_for_sending,
    enqueue,
    get_item,
    list_items,
    mark_failed,
    mark_sent,
)

THREAD_RESUME_KIND = "thread_resume"
THREAD_RESUME_OUTBOX_KIND = "initiative.thread_resume"
THREAD_RESUME_DAILY_LIMIT = 1


def delivery_gate(
    db_path: Path,
    *,
    now: datetime | None = None,
    required_observation_days: int = DEFAULT_REQUIRED_DELIVERY_OBSERVATION_DAYS,
):
    logs = list_shadow_logs(db_path, limit=500)
    manual_report = evaluate_shadow_validation(logs, now=now)
    long_term_report = evaluate_long_term_validation(logs, now=now)
    opt_in = get_delivery_opt_in(db_path)
    return evaluate_delivery_gate(
        manual_report,
        long_term_report,
        explicit_opt_in=opt_in.enabled,
        required_observation_days=required_observation_days,
    )


def queue_thread_resume(
    db_path: Path,
    log_id: int,
    *,
    now: datetime | None = None,
    required_observation_days: int = DEFAULT_REQUIRED_DELIVERY_OBSERVATION_DAYS,
) -> dict[str, Any]:
    """Queue and immediately attempt one eligible in-app delivery."""
    log = get_shadow_log(db_path, log_id)
    if log is None or log.get("kind") != THREAD_RESUME_KIND:
        return {"queued": False, "delivered": False, "reason": "not_thread_resume"}
    if log.get("delivered"):
        return {"queued": False, "delivered": True, "reason": "already_delivered"}
    if not thread_clue_allows_delivery(db_path, log):
        return {"queued": False, "delivered": False, "reason": "thread_clue_inactive"}
    gate = delivery_gate(
        db_path,
        now=now,
        required_observation_days=required_observation_days,
    )
    if not gate.can_enable_delivery:
        return {"queued": False, "delivered": False, "reason": "delivery_gate_closed"}
    if get_presence_state(db_path) != "idle":
        return {"queued": False, "delivered": False, "reason": "presence_not_idle"}
    if count_delivered_today(db_path, kind=THREAD_RESUME_KIND, now=now) >= THREAD_RESUME_DAILY_LIMIT:
        return {"queued": False, "delivered": False, "reason": "daily_limit"}

    payload = {
        "initiativeLogId": int(log_id),
        "kind": THREAD_RESUME_KIND,
        "title": str(log.get("title") or ""),
        "message": str(log.get("message") or ""),
        "channel": "archer.in_app",
    }
    item = enqueue(
        db_path,
        kind=THREAD_RESUME_OUTBOX_KIND,
        payload=payload,
        idempotency_key=f"{THREAD_RESUME_OUTBOX_KIND}:{int(log_id)}",
        now=now,
    )
    if item["status"] == "pending":
        item = approve(db_path, item["id"], now=now) or item
    delivered = process_thread_resume_outbox(
        db_path,
        now=now,
        required_observation_days=required_observation_days,
    )
    latest = get_item(db_path, item["id"]) or item
    return {
        "queued": True,
        "delivered": latest.get("status") == "sent",
        "reason": "sent" if latest.get("status") == "sent" else "queued",
        "outbox": latest,
        "processed": delivered,
    }


def process_thread_resume_outbox(
    db_path: Path,
    *,
    now: datetime | None = None,
    required_observation_days: int = DEFAULT_REQUIRED_DELIVERY_OBSERVATION_DAYS,
    sink: Callable[[Path, int, dict[str, Any]], dict[str, Any] | None] | None = None,
) -> int:
    """Retry approved/failed thread_resume items while every delivery gate remains open."""
    if not get_delivery_opt_in(db_path).enabled:
        return 0
    if get_presence_state(db_path) != "idle":
        return 0
    gate = delivery_gate(
        db_path,
        now=now,
        required_observation_days=required_observation_days,
    )
    if not gate.can_enable_delivery:
        return 0
    deliver = sink or _deliver_to_in_app
    sent = 0
    items = list_items(db_path, statuses={"approved", "failed"}, limit=100)
    for item in reversed(items):
        if item.get("kind") != THREAD_RESUME_OUTBOX_KIND:
            continue
        log_id = int(item.get("payload", {}).get("initiativeLogId") or 0)
        log = get_shadow_log(db_path, log_id)
        if log is not None and not thread_clue_allows_delivery(db_path, log):
            cancel(db_path, item["id"], now=now)
            continue
        if log is None or log.get("kind") != THREAD_RESUME_KIND:
            claimed = claim_for_sending(db_path, item["id"], now=now)
            if claimed:
                mark_failed(db_path, item["id"], "initiative log missing", now=now)
            continue
        if not log.get("delivered") and count_delivered_today(
            db_path, kind=THREAD_RESUME_KIND, now=now
        ) >= THREAD_RESUME_DAILY_LIMIT:
            break
        claimed = claim_for_sending(db_path, item["id"], now=now)
        if claimed is None:
            continue
        try:
            with trace_span(
                "initiative.thread_resume.delivery",
                outbox_id=item["id"],
                initiative_log_id=log_id,
                channel="archer.in_app",
            ):
                delivered_log = deliver(
                    db_path,
                    log_id,
                    {
                        "outboxId": item["id"],
                        "channel": "archer.in_app",
                        "status": "sent",
                        "sentAt": (now or datetime.now()).isoformat(timespec="seconds"),
                    },
                )
                if delivered_log is None:
                    raise RuntimeError("initiative log missing")
                receipt = {
                    "channel": "archer.in_app",
                    "initiativeLogId": log_id,
                    "delivered": True,
                }
                if mark_sent(db_path, item["id"], receipt, now=now) is None:
                    raise RuntimeError("outbox sent transition failed")
            sent += 1
        except Exception as exc:
            mark_failed(db_path, item["id"], str(exc), now=now)
            if not thread_clue_allows_delivery(db_path, log):
                cancel(db_path, item["id"], now=now)
    return sent


def cancel_pending_thread_resume(db_path: Path, *, now: datetime | None = None) -> int:
    cancelled = 0
    for item in list_items(db_path, statuses={"pending", "approved", "failed"}, limit=500):
        if item.get("kind") != THREAD_RESUME_OUTBOX_KIND:
            continue
        if cancel(db_path, item["id"], now=now):
            cancelled += 1
    return cancelled


def newest_undelivered_thread_resume(db_path: Path) -> dict[str, Any] | None:
    return next(
        (
            log
            for log in list_shadow_logs(db_path, limit=500)
            if log.get("kind") == THREAD_RESUME_KIND and not log.get("delivered")
        ),
        None,
    )


def _deliver_to_in_app(
    db_path: Path,
    log_id: int,
    delivery_trace: dict[str, Any],
) -> dict[str, Any] | None:
    return mark_initiative_delivered(db_path, log_id, delivery_trace=delivery_trace)
