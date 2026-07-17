from __future__ import annotations

from datetime import datetime, timedelta

from core.delivery_opt_in import set_delivery_opt_in
from core.initiative_delivery import (
    THREAD_RESUME_OUTBOX_KIND,
    cancel_pending_thread_resume,
    process_thread_resume_outbox,
    queue_thread_resume,
)
from core.initiative_shadow import (
    get_shadow_log,
    record_shadow_feedback,
    record_shadow_initiative,
)
from core.presence import set_presence_state
from infrastructure.observability import span_recording
from infrastructure.outbox import (
    approve,
    claim_for_sending,
    enqueue,
    get_item,
    init_outbox_table,
    list_items,
    recover_interrupted,
)
from terminal.api.initiative_routes import _initiative_delivery_opt_in


NOW = datetime(2026, 7, 17, 12, 0, 0)


def _record(db_path, when: datetime, *, suffix: str) -> int:
    return record_shadow_initiative(
        db_path=db_path,
        event_type="initiative.due",
        kind="thread_resume",
        title=f"话题 {suffix}",
        message=f"继续 {suffix}",
        now=when,
        decision_trace={"threadId": suffix},
    )


def _seed_open_gate(db_path) -> int:
    ids = [
        _record(db_path, NOW - timedelta(days=14), suffix="old"),
        _record(db_path, NOW - timedelta(days=7), suffix="middle"),
        _record(db_path, NOW, suffix="latest"),
    ]
    for log_id in ids:
        assert record_shadow_feedback(
            db_path=db_path,
            log_id=log_id,
            feedback="acknowledged",
            now=NOW,
        )
    return ids[-1]


def _enqueue_approved(db_path, log_id: int):
    log = get_shadow_log(db_path, log_id)
    item = enqueue(
        db_path,
        kind=THREAD_RESUME_OUTBOX_KIND,
        payload={
            "initiativeLogId": log_id,
            "kind": "thread_resume",
            "title": log["title"],
            "message": log["message"],
            "channel": "archer.in_app",
        },
        idempotency_key=f"{THREAD_RESUME_OUTBOX_KIND}:{log_id}",
        now=NOW,
    )
    return approve(db_path, item["id"], now=NOW)


def test_no_opt_in_keeps_thread_resume_shadow_only(tmp_path):
    db_path = tmp_path / "memory.db"
    log_id = _seed_open_gate(db_path)

    result = queue_thread_resume(db_path, log_id, now=NOW)

    assert result == {"queued": False, "delivered": False, "reason": "delivery_gate_closed"}
    assert get_shadow_log(db_path, log_id)["delivered"] is False
    init_outbox_table(db_path)
    assert list_items(db_path) == []


def test_observation_gate_cannot_be_bypassed_by_opt_in(tmp_path):
    db_path = tmp_path / "memory.db"
    log_id = _record(db_path, NOW, suffix="new")
    set_delivery_opt_in(db_path, enabled=True, reason="test", now=NOW)

    result = queue_thread_resume(db_path, log_id, now=NOW)

    assert result["reason"] == "delivery_gate_closed"
    assert get_shadow_log(db_path, log_id)["delivered"] is False


def test_eligible_thread_resume_delivers_once_with_trace_and_receipt(tmp_path):
    db_path = tmp_path / "memory.db"
    log_id = _seed_open_gate(db_path)
    set_delivery_opt_in(db_path, enabled=True, reason="explicit_test_opt_in", now=NOW)

    with span_recording() as spans:
        result = queue_thread_resume(db_path, log_id, now=NOW)

    assert result["queued"] is True
    assert result["delivered"] is True
    assert get_shadow_log(db_path, log_id)["delivered"] is True
    item = result["outbox"]
    assert item["status"] == "sent"
    assert item["result"] == {
        "channel": "archer.in_app",
        "initiativeLogId": log_id,
        "delivered": True,
    }
    assert [span["name"] for span in spans] == ["initiative.thread_resume.delivery"]

    repeated = queue_thread_resume(db_path, log_id, now=NOW)
    assert repeated == {"queued": False, "delivered": True, "reason": "already_delivered"}
    assert len(list_items(db_path)) == 1


def test_daily_limit_blocks_second_thread_resume(tmp_path):
    db_path = tmp_path / "memory.db"
    first_id = _seed_open_gate(db_path)
    set_delivery_opt_in(db_path, enabled=True, reason="test", now=NOW)
    assert queue_thread_resume(db_path, first_id, now=NOW)["delivered"] is True
    second_id = _record(db_path, NOW + timedelta(minutes=1), suffix="second")

    result = queue_thread_resume(db_path, second_id, now=NOW + timedelta(minutes=1))

    assert result["reason"] == "daily_limit"
    assert get_shadow_log(db_path, second_id)["delivered"] is False
    assert len(list_items(db_path)) == 1


def test_non_idle_presence_never_queues_delivery(tmp_path):
    db_path = tmp_path / "memory.db"
    log_id = _seed_open_gate(db_path)
    set_delivery_opt_in(db_path, enabled=True, reason="test", now=NOW)
    set_presence_state(db_path, "muted")

    result = queue_thread_resume(db_path, log_id, now=NOW)

    assert result["reason"] == "presence_not_idle"
    assert get_shadow_log(db_path, log_id)["delivered"] is False


def test_opt_out_cancels_unsent_thread_resume(tmp_path):
    db_path = tmp_path / "memory.db"
    log_id = _seed_open_gate(db_path)
    item = _enqueue_approved(db_path, log_id)

    assert cancel_pending_thread_resume(db_path, now=NOW) == 1
    assert get_item(db_path, item["id"])["status"] == "cancelled"
    assert get_shadow_log(db_path, log_id)["delivered"] is False


def test_opt_out_api_cancels_unsent_items_in_runtime_database(tmp_path):
    db_path = tmp_path / "memory.db"
    log_id = _seed_open_gate(db_path)
    item = _enqueue_approved(db_path, log_id)

    class Context:
        def __init__(self, path):
            self.db_path = path

        def now(self):
            return NOW

    status, body = _initiative_delivery_opt_in(
        {"enabled": False, "reason": "desktop_review_revoke"},
        Context(db_path),
    )

    assert status == 200
    assert body["optIn"]["enabled"] is False
    assert body["cancelled"] == 1
    assert get_item(db_path, item["id"])["status"] == "cancelled"


def test_crash_recovery_retries_only_after_gates_are_rechecked(tmp_path):
    db_path = tmp_path / "memory.db"
    log_id = _seed_open_gate(db_path)
    set_delivery_opt_in(db_path, enabled=True, reason="test", now=NOW)
    item = _enqueue_approved(db_path, log_id)
    assert claim_for_sending(db_path, item["id"], now=NOW)["status"] == "sending"
    assert recover_interrupted(db_path, now=NOW) == 1

    assert process_thread_resume_outbox(db_path, now=NOW) == 1
    assert get_item(db_path, item["id"])["status"] == "sent"
    assert get_shadow_log(db_path, log_id)["delivered"] is True


def test_failed_in_app_delivery_uses_outbox_retry(tmp_path):
    db_path = tmp_path / "memory.db"
    log_id = _seed_open_gate(db_path)
    set_delivery_opt_in(db_path, enabled=True, reason="test", now=NOW)
    item = _enqueue_approved(db_path, log_id)

    def fail_sink(*_args):
        raise RuntimeError("renderer unavailable")

    assert process_thread_resume_outbox(db_path, now=NOW, sink=fail_sink) == 0
    failed = get_item(db_path, item["id"])
    assert failed["status"] == "failed"
    assert "renderer unavailable" in failed["lastError"]
    assert get_shadow_log(db_path, log_id)["delivered"] is False

    assert process_thread_resume_outbox(db_path, now=NOW + timedelta(seconds=6)) == 1
    assert get_item(db_path, item["id"])["status"] == "sent"
