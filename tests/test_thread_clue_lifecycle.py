from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.initiative_delivery import THREAD_RESUME_OUTBOX_KIND, process_thread_resume_outbox, queue_thread_resume
from core.initiative_feedback import claim_review_candidate
from core.initiative_shadow import get_shadow_log, record_shadow_initiative
from core.memory_grounded_companion import pending_companion_message
from core.part8_clues import record_thread_clues_from_messages
from core.part8_threads import record_unclosed_thread, scan_thread_resume_candidates
from core.thread_clue_lifecycle import expire_stale_thread_clues, get_thread_clue, transition_thread_clue
from infrastructure.outbox import approve, enqueue, get_item
from memory.thread_context import get_thread_context, update_thread_context
from terminal.api._routes import payload_post

NOW = datetime(2026, 10, 2, 12)


def _linked(db: Path, clue_id: int, *, delivered: bool = False) -> int:
    return record_shadow_initiative(
        db_path=db, event_type='initiative_due', kind='thread_resume', title='青禾资料复查',
        message='继续核对青禾资料', delivered=delivered, now=NOW,
        decision_trace={'threadId': clue_id, 'source': 'episodic', 'confidence': 0.9},
    )


@pytest.mark.parametrize('status', ['resolved', 'closed', 'dismissed', 'expired'])
def test_terminal_cue_archives_only_its_candidates_without_feedback(tmp_path: Path, status: str) -> None:
    db = tmp_path / 'memory.db'
    clue_id = record_unclosed_thread(db_path=db, session_id='s1', topic='青禾复查')
    other_id = record_unclosed_thread(db_path=db, session_id='s2', topic='蓝湾复查')
    log_id = _linked(db, clue_id)
    other_log_id = _linked(db, other_id)
    # Saved conversation capsules are a different domain, even for numeric IDs.
    update_thread_context(str(clue_id), [{'role': 'user', 'content': '保留会话目标'}], db_path=db)
    capsule = get_thread_context(str(clue_id), db_path=db)
    result = transition_thread_clue(db, clue_id, status, now=NOW)
    assert result['changed'] is True
    assert get_thread_clue(db, clue_id)['status'] == status
    assert get_thread_clue(db, other_id)['status'] == 'open'
    log = get_shadow_log(db, log_id)
    assert log['feedback'] in ('', None)
    assert log['delivered'] is False
    assert log['archived_at'] == NOW.isoformat(timespec='seconds')
    assert log['decision_trace']['threadLifecycle']['status'] == status
    assert get_shadow_log(db, other_log_id)['archived_at'] is None
    assert scan_thread_resume_candidates(db_path=db, now=NOW + timedelta(days=2), presence_state='muted') == []
    assert get_thread_context(str(clue_id), db_path=db) == capsule
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name='initiative_delivery_opt_in'").fetchone()[0] == 0


def test_repeated_transition_is_idempotent_and_conflicting_terminal_is_rejected(tmp_path: Path) -> None:
    db = tmp_path / 'memory.db'
    clue_id = record_unclosed_thread(db_path=db, topic='青禾')
    transition_thread_clue(db, clue_id, 'resolved', now=NOW)
    original = get_thread_clue(db, clue_id)
    assert transition_thread_clue(db, clue_id, 'resolved', now=NOW + timedelta(days=1))['changed'] is False
    with pytest.raises(ValueError):
        transition_thread_clue(db, clue_id, 'closed', now=NOW)
    assert get_thread_clue(db, clue_id) == original


def test_exact_source_dedup_is_concurrent_and_terminal_cue_does_not_reopen(tmp_path: Path) -> None:
    db = tmp_path / 'memory.db'
    record_unclosed_thread(db_path=db, topic='Other')
    def record(_: int) -> int:
        return record_unclosed_thread(db_path=db, topic='  Qinghe   Review ', prompt='核对来源')
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(record, range(6)))
    assert len(set(ids)) == 1
    transition_thread_clue(db, ids[0], 'dismissed', now=NOW)
    assert record_unclosed_thread(db_path=db, topic='qinghe review', prompt='核对来源') == ids[0]
    assert get_thread_clue(db, ids[0])['status'] == 'dismissed'
    assert record_unclosed_thread(db_path=db, topic='qinghe review', prompt='不同事项的新依据') != ids[0]


def test_saved_clue_replay_does_not_recreate_closed_source(tmp_path: Path) -> None:
    db = tmp_path / 'memory.db'
    messages = [{'role': 'user', 'content': '青禾计划后面继续核对来源'}]
    clue_id = record_thread_clues_from_messages(db_path=db, session_id='s1', messages=messages)[0]
    transition_thread_clue(db, clue_id, 'closed', now=NOW)
    assert record_thread_clues_from_messages(db_path=db, session_id='s1', messages=messages) == []


def test_expiry_is_explicit_and_uses_last_seen_not_created_at(tmp_path: Path) -> None:
    db = tmp_path / 'memory.db'
    old_id = record_unclosed_thread(db_path=db, topic='old', last_seen_at=NOW - timedelta(days=31))
    fresh_id = record_unclosed_thread(db_path=db, topic='fresh', last_seen_at=NOW - timedelta(days=1))
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE part8_threads SET created_at=? WHERE id=?", ((NOW - timedelta(days=90)).isoformat(), fresh_id))
    assert get_thread_clue(db, old_id)['status'] == 'open'
    assert expire_stale_thread_clues(db, now=NOW) == [old_id]
    assert get_thread_clue(db, fresh_id)['status'] == 'open'
    assert expire_stale_thread_clues(db, now=NOW) == []
    with pytest.raises(ValueError):
        expire_stale_thread_clues(db, max_idle_days=0, now=NOW)


def test_closing_cancels_pending_outbox_and_blocks_queue_retry_and_chat(tmp_path: Path) -> None:
    db = tmp_path / 'memory.db'
    clue_id = record_unclosed_thread(db_path=db, topic='青禾')
    log_id = _linked(db, clue_id)
    item = enqueue(db, kind=THREAD_RESUME_OUTBOX_KIND, payload={'initiativeLogId': log_id}, idempotency_key='cue-test', now=NOW)
    approve(db, item['id'], now=NOW)
    transition_thread_clue(db, clue_id, 'closed', now=NOW)
    assert get_item(db, item['id'])['status'] == 'cancelled'
    assert queue_thread_resume(db, log_id, now=NOW)['reason'] == 'thread_clue_inactive'
    assert process_thread_resume_outbox(db, now=NOW) == 0
    assert pending_companion_message(db) is None
    assert get_shadow_log(db, log_id)['delivered'] is False


def test_closed_delivered_cue_is_not_added_to_chat(tmp_path: Path) -> None:
    db = tmp_path / 'memory.db'
    clue_id = record_unclosed_thread(db_path=db, topic='青禾')
    log_id = _linked(db, clue_id, delivered=True)
    assert pending_companion_message(db)['id'] == log_id
    transition_thread_clue(db, clue_id, 'resolved', now=NOW)
    assert pending_companion_message(db) is None
    assert get_shadow_log(db, log_id)['delivered'] is True


def test_daily_exposure_does_not_return_a_closed_candidate_or_fake_feedback(tmp_path: Path) -> None:
    db = tmp_path / 'memory.db'
    clue_id = record_unclosed_thread(db_path=db, topic='青禾')
    log_id = _linked(db, clue_id)
    assert claim_review_candidate(db, surface='today', now=NOW)['item']['id'] == log_id
    transition_thread_clue(db, clue_id, 'dismissed', now=NOW)
    assert claim_review_candidate(db, surface='today', now=NOW)['item'] is None
    assert get_shadow_log(db, log_id)['feedback'] in ('', None)


def test_api_status_controls_validate_and_preserve_context_scope(tmp_path: Path) -> None:
    db = tmp_path / 'memory.db'
    clue_id = record_unclosed_thread(db_path=db, topic='青禾')
    context = SimpleNamespace(db_path=db, now=lambda: NOW)
    path = f'/initiative-threads/{clue_id}/status'
    assert payload_post(path, {'status': 'open'}, context)[0] == 400
    assert payload_post('/initiative-threads/999999/status', {'status': 'closed'}, context)[0] == 404
    assert payload_post(path, {'status': 'closed'}, context)[0] == 200
    assert payload_post(path, {'status': 'resolved'}, context)[0] == 409
    assert payload_post('/initiative-threads/expire', {'maxIdleDays': True}, context)[0] == 400
    assert payload_post('/initiative-threads/expire', {'maxIdleDays': 30}, context) == (200, {'ok': True, 'expiredIds': []})


def test_close_between_outbox_claim_and_delivery_cannot_send_stale_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from core import initiative_delivery
    from core.delivery_opt_in import set_delivery_opt_in
    from core.initiative_shadow import mark_initiative_delivered

    db = tmp_path / 'memory.db'
    clue_id = record_unclosed_thread(db_path=db, topic='青禾')
    log_id = _linked(db, clue_id)
    item = enqueue(db, kind=THREAD_RESUME_OUTBOX_KIND, payload={'initiativeLogId': log_id}, idempotency_key='race-test', now=NOW)
    approve(db, item['id'], now=NOW)
    set_delivery_opt_in(db, enabled=True, reason='synthetic test', now=NOW)
    monkeypatch.setattr(initiative_delivery, 'delivery_gate', lambda *args, **kwargs: SimpleNamespace(can_enable_delivery=True))

    def close_then_deliver(path: Path, candidate_id: int, trace: dict) -> dict | None:
        transition_thread_clue(path, clue_id, 'closed', now=NOW)
        return mark_initiative_delivered(path, candidate_id, delivery_trace=trace)

    assert process_thread_resume_outbox(db, now=NOW, sink=close_then_deliver) == 0
    assert get_shadow_log(db, log_id)['delivered'] is False
    assert get_shadow_log(db, log_id)['decision_trace']['threadLifecycle']['status'] == 'closed'
    assert get_item(db, item['id'])['status'] == 'cancelled'
