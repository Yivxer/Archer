from __future__ import annotations

import sqlite3
from pathlib import Path

from core.initiative_shadow import record_shadow_initiative
from core.memory_grounded_companion import pending_companion_message, respond_to_companion
from core.part8_threads import record_unclosed_thread


def _delivered_resume(db_path: Path, *, confidence: float = 0.9) -> tuple[int, int]:
    thread_id = record_unclosed_thread(db_path=db_path, topic="继续 Archer 上下文协议")
    log_id = record_shadow_initiative(
        db_path=db_path,
        event_type="initiative_due",
        kind="thread_resume",
        title="继续未完成事项",
        message="上次停在上下文协议，要继续吗？",
        decision_trace={
            "reason": "stale_open_thread",
            "source": "episodic",
            "confidence": confidence,
            "threadId": thread_id,
            "sessionId": "session-1",
        },
        delivered=True,
    )
    return log_id, thread_id


def test_only_reliable_delivered_context_reaches_chat(tmp_path: Path) -> None:
    db_path = tmp_path / "archer.db"
    _delivered_resume(db_path, confidence=0.5)
    reliable_id, _ = _delivered_resume(db_path)

    item = pending_companion_message(db_path)

    assert item is not None
    assert item["id"] == reliable_id
    assert item["source"] == "episodic"
    assert item["confidence"] == 0.9


def test_displayed_message_is_not_returned_twice(tmp_path: Path) -> None:
    db_path = tmp_path / "archer.db"
    log_id, _ = _delivered_resume(db_path)

    assert pending_companion_message(db_path) is not None
    assert respond_to_companion(db_path, log_id, "displayed") == {
        "id": log_id,
        "status": "displayed",
        "memoryResult": "skipped",
    }
    assert pending_companion_message(db_path) is None


def test_direct_replies_continue_correct_and_suppress(tmp_path: Path) -> None:
    db_path = tmp_path / "archer.db"
    log_id, thread_id = _delivered_resume(db_path)

    assert respond_to_companion(db_path, log_id, "continue")["status"] == "continued"
    corrected = respond_to_companion(db_path, log_id, "correct", detail="不是这条线")
    assert corrected == {"id": log_id, "status": "corrected", "memoryResult": "corrected"}
    assert respond_to_companion(db_path, log_id, "suppress")["status"] == "suppressed"

    conn = sqlite3.connect(db_path)
    thread_status = conn.execute("SELECT status FROM part8_threads WHERE id=?", (thread_id,)).fetchone()[0]
    receipt = conn.execute(
        "SELECT status FROM companion_chat_receipts WHERE initiative_log_id=?", (log_id,)
    ).fetchone()[0]
    conn.close()
    assert thread_status == "suppressed"
    assert receipt == "suppressed"
