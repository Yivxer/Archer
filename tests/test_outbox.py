from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from infrastructure.outbox import (
    approve,
    cancel,
    claim_for_sending,
    enqueue,
    get_item,
    list_items,
    mark_failed,
    mark_sent,
    recover_interrupted,
)
from memory.migrations import run_migrations
from core.runtime_context import create_runtime_context
from terminal.api.fastapi_app import create_app


NOW = datetime(2026, 7, 16, 23, 0, 0)


def _new_item(db_path, *, key="tool:one", max_attempts=3):
    return enqueue(
        db_path,
        kind="tool.execute",
        payload={"skillName": "safe_tool", "args": {"value": "x"}},
        idempotency_key=key,
        max_attempts=max_attempts,
        now=NOW,
    )


def test_outbox_idempotency_reuses_same_payload_and_rejects_collision(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)

    first = _new_item(db_path)
    second = _new_item(db_path)

    assert first["status"] == "pending"
    assert first["reused"] is False
    assert second["id"] == first["id"]
    assert second["reused"] is True
    with pytest.raises(ValueError, match="different outbox payload"):
        enqueue(
            db_path, kind="tool.execute", payload={"different": True},
            idempotency_key="tool:one", now=NOW,
        )


def test_outbox_happy_path_is_pending_approved_sending_sent(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    item = _new_item(db_path)

    approved = approve(db_path, item["id"], now=NOW)
    claimed = claim_for_sending(db_path, item["id"], now=NOW)
    sent = mark_sent(db_path, item["id"], {"ok": True}, now=NOW)

    assert approved["status"] == "approved"
    assert claimed["status"] == "sending"
    assert claimed["attempts"] == 1
    assert sent["status"] == "sent"
    assert sent["result"] == {"ok": True}
    assert claim_for_sending(db_path, item["id"], now=NOW) is None


def test_outbox_failure_uses_backoff_and_stops_at_retry_limit(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    item = _new_item(db_path, max_attempts=2)
    approve(db_path, item["id"], now=NOW)
    claim_for_sending(db_path, item["id"], now=NOW)

    failed = mark_failed(db_path, item["id"], "network", now=NOW, base_delay_seconds=5)

    assert failed["status"] == "failed"
    assert failed["nextAttemptAt"] == (NOW + timedelta(seconds=5)).isoformat(timespec="seconds")
    assert claim_for_sending(db_path, item["id"], now=NOW) is None
    assert claim_for_sending(db_path, item["id"], now=NOW, force=True)["attempts"] == 2
    mark_failed(db_path, item["id"], "forced retry failed", now=NOW)
    assert claim_for_sending(db_path, item["id"], now=NOW, force=True) is None


def test_outbox_automatic_retry_waits_for_backoff(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    item = _new_item(db_path, key="tool:auto", max_attempts=3)
    approve(db_path, item["id"], now=NOW)
    claim_for_sending(db_path, item["id"], now=NOW)
    failed = mark_failed(db_path, item["id"], "network", now=NOW, base_delay_seconds=5)

    assert failed["nextAttemptAt"] == (NOW + timedelta(seconds=5)).isoformat(timespec="seconds")
    assert claim_for_sending(db_path, item["id"], now=NOW) is None
    claimed = claim_for_sending(db_path, item["id"], now=NOW + timedelta(seconds=5))
    assert claimed["attempts"] == 2


def test_outbox_recovery_moves_interrupted_sends_to_retryable_failed(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    item = _new_item(db_path)
    approve(db_path, item["id"], now=NOW)
    claim_for_sending(db_path, item["id"], now=NOW)

    recovered = recover_interrupted(db_path, now=NOW + timedelta(minutes=1))
    restored = get_item(db_path, item["id"])

    assert recovered == 1
    assert restored["status"] == "failed"
    assert restored["lastError"] == "interrupted during sending"
    assert claim_for_sending(db_path, item["id"], now=NOW + timedelta(minutes=1))["status"] == "sending"


def test_fastapi_startup_recovers_interrupted_outbox_delivery(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    item = _new_item(db_path)
    approve(db_path, item["id"], now=NOW)
    claim_for_sending(db_path, item["id"], now=NOW)
    context = create_runtime_context(db_path=db_path, clock=lambda: NOW + timedelta(minutes=1))
    app = create_app("test-token", runtime_context=context)

    with TestClient(app):
        assert app.state.outbox_recovered == 1

    assert get_item(db_path, item["id"])["status"] == "failed"


def test_outbox_cancel_and_filtered_list(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    item = _new_item(db_path)

    assert cancel(db_path, item["id"], now=NOW)["status"] == "cancelled"
    assert approve(db_path, item["id"], now=NOW) is None
    assert [entry["id"] for entry in list_items(db_path, statuses={"cancelled"})] == [item["id"]]
