import json
import sqlite3
from datetime import datetime


def test_event_bus_publishes_session_event_to_subscribers():
    from core.event_bus import ArcherEvent, ArcherEventBus

    seen = []
    bus = ArcherEventBus()
    bus.subscribe("session_end", seen.append)

    event = ArcherEvent(
        type="session_end",
        source="test",
        payload={"sessionId": "s1"},
        priority=1,
        created_at=datetime(2026, 6, 25, 9, 0, 0),
    )

    published = bus.publish(event)

    assert published is event
    assert seen == [event]
    assert event.to_payload()["type"] == "session_end"
    assert event.to_payload()["payload"]["sessionId"] == "s1"


def test_shadow_initiative_log_defaults_to_not_delivered(tmp_path):
    from core.initiative_shadow import init_table, list_shadow_logs, record_shadow_initiative

    db_path = tmp_path / "archer.db"
    init_table(db_path)

    log_id = record_shadow_initiative(
        db_path=db_path,
        event_type="initiative_due",
        kind="thread_resume",
        title="Follow up on unfinished topic",
        message="Last time you mentioned Part 8. Any movement?",
        now=datetime(2026, 6, 25, 10, 0, 0),
        decision_trace={"trigger": "session_gap", "score": 0.72},
    )

    logs = list_shadow_logs(db_path)
    assert log_id == logs[0]["id"]
    assert logs[0]["delivered"] is False
    assert logs[0]["event_type"] == "initiative_due"
    assert logs[0]["decision_trace"]["trigger"] == "session_gap"

    row = sqlite3.connect(db_path).execute(
        "SELECT delivered, decision_trace_json FROM initiative_sent_log WHERE id=?",
        (log_id,),
    ).fetchone()
    assert row[0] == 0
    assert json.loads(row[1])["score"] == 0.72


def test_shadow_initiative_arbiter_respects_daily_limit_and_muted(tmp_path):
    from core.initiative_shadow import (
        InitiativeDecision,
        init_table,
        normalize_presence_state,
        record_shadow_initiative,
        should_record_shadow_initiative,
    )

    db_path = tmp_path / "archer.db"
    init_table(db_path)
    now = datetime(2026, 6, 25, 12, 0, 0)

    assert should_record_shadow_initiative(db_path, now=now) == InitiativeDecision(
        allowed=True,
        reason="within_daily_limit",
    )

    for idx in range(3):
        record_shadow_initiative(
            db_path=db_path,
            event_type="initiative_due",
            kind="thread_resume",
            title=f"Candidate {idx}",
            message="shadow only",
            now=now.replace(hour=idx + 8),
            decision_trace={"idx": idx},
        )

    assert should_record_shadow_initiative(db_path, now=now) == InitiativeDecision(
        allowed=False,
        reason="daily_limit_reached",
    )
    assert should_record_shadow_initiative(db_path, now=now, presence_state="muted") == InitiativeDecision(
        allowed=False,
        reason="presence_muted",
    )
    assert normalize_presence_state("engaged") == "engaged"
    assert normalize_presence_state("idle") == "idle"
    assert normalize_presence_state("muted") == "muted"
    assert normalize_presence_state("unknown") == "idle"


def test_shadow_initiative_global_throttle_after_too_frequent_feedback(tmp_path):
    from core.initiative_shadow import (
        InitiativeDecision,
        init_table,
        record_shadow_initiative,
        record_shadow_feedback,
        should_record_shadow_initiative,
    )

    db_path = tmp_path / "archer.db"
    init_table(db_path)
    now = datetime(2026, 6, 25, 12, 0, 0)
    log_id = record_shadow_initiative(
        db_path=db_path,
        event_type="initiative_due",
        kind="thread_resume",
        title="Candidate",
        message="shadow only",
        now=now.replace(hour=8),
        decision_trace={},
    )
    record_shadow_feedback(
        db_path=db_path,
        log_id=log_id,
        feedback="too_frequent",
        now=now.replace(hour=9),
    )

    assert should_record_shadow_initiative(db_path, now=now.replace(hour=10)) == InitiativeDecision(
        allowed=False,
        reason="global_throttle_active",
    )
    assert should_record_shadow_initiative(
        db_path,
        now=datetime(2026, 6, 28, 10, 0, 0),
    ) == InitiativeDecision(
        allowed=True,
        reason="within_daily_limit",
    )


def test_shadow_arbiter_respects_persisted_presence_mute(tmp_path):
    from core.initiative_shadow import InitiativeDecision, init_table, should_record_shadow_initiative
    from core.presence import set_presence_state

    db_path = tmp_path / "archer.db"
    init_table(db_path)
    set_presence_state(db_path, "muted")

    assert should_record_shadow_initiative(db_path, presence_state="idle") == InitiativeDecision(
        allowed=False,
        reason="presence_muted",
    )


def test_unclosed_thread_can_be_stored_and_resumed_as_shadow_initiative(tmp_path):
    from core.part8_threads import (
        init_table,
        list_open_threads,
        record_unclosed_thread,
        scan_thread_resume_candidates,
    )
    from core.initiative_shadow import list_shadow_logs

    db_path = tmp_path / "archer.db"
    init_table(db_path)

    thread_id = record_unclosed_thread(
        db_path=db_path,
        session_id="s1",
        topic="Part 8 shadow 垂直切片",
        prompt="继续把 Part 8 做成可回看的影子链路",
        last_seen_at=datetime(2026, 6, 20, 20, 0, 0),
    )

    open_threads = list_open_threads(db_path)
    assert open_threads[0]["id"] == thread_id
    assert open_threads[0]["status"] == "open"
    assert open_threads[0]["topic"] == "Part 8 shadow 垂直切片"

    created = scan_thread_resume_candidates(
        db_path=db_path,
        now=datetime(2026, 6, 25, 9, 0, 0),
        min_gap_days=2,
    )

    assert len(created) == 1
    assert created[0]["kind"] == "thread_resume"
    assert created[0]["delivered"] is False
    assert created[0]["decision_trace"]["threadId"] == thread_id
    assert "Part 8" in created[0]["message"]

    logs = list_shadow_logs(db_path)
    assert logs[0]["kind"] == "thread_resume"


def test_thread_resume_scan_does_not_duplicate_existing_shadow_candidate(tmp_path):
    from core.part8_threads import init_table, record_unclosed_thread, scan_thread_resume_candidates
    from core.initiative_shadow import list_shadow_logs

    db_path = tmp_path / "archer.db"
    init_table(db_path)
    record_unclosed_thread(
        db_path=db_path,
        session_id="s1",
        topic="视频剪辑计划",
        prompt="剪完第一版再回看节奏",
        last_seen_at=datetime(2026, 6, 20, 20, 0, 0),
    )

    scan_thread_resume_candidates(db_path=db_path, now=datetime(2026, 6, 25, 9, 0, 0))
    scan_thread_resume_candidates(db_path=db_path, now=datetime(2026, 6, 25, 10, 0, 0))

    logs = list_shadow_logs(db_path)
    assert len(logs) == 1
    assert logs[0]["decision_trace"]["reason"] == "stale_open_thread"


def test_chat_stream_emits_shadow_initiative_event_for_stale_thread(tmp_path, monkeypatch):
    import memory.store as store
    from core.part8_threads import record_unclosed_thread
    from terminal.api._tools import _iter_chat_chunks

    original_db_path = store.DB_PATH
    store.DB_PATH = tmp_path / "archer.db"
    try:
        store.init_db()
        record_unclosed_thread(
            db_path=store.DB_PATH,
            session_id="s1",
            topic="Part 8 SSE 预留契约",
            prompt="只做 shadow event，不推送 UI",
            last_seen_at=datetime(2026, 6, 20, 9, 0, 0),
        )
        monkeypatch.setattr("core.llm.stream_chat", lambda messages, **kwargs: iter(["ok"]))

        chunks = []
        for chunk in _iter_chat_chunks(
            [{"role": "user", "content": "在吗"}],
            memory_mode="off",
            obsidian_mode="off",
        ):
            chunks.append(chunk)
            if chunk.get("type") == "ready":
                break

        event = next(chunk["initiativeEvent"] for chunk in chunks if chunk.get("type") == "initiativeEvent")
        assert event["kind"] == "thread_resume"
        assert event["delivered"] is False
        assert event["shadow"] is True
        assert event["decisionTrace"]["reason"] == "stale_open_thread"
        assert "Part 8" in event["message"]
    finally:
        store.DB_PATH = original_db_path


def test_session_end_event_bus_drives_thread_resume_shadow_candidate(tmp_path):
    from core.event_bus import ArcherEvent, ArcherEventBus
    from core.initiative_shadow import list_shadow_logs
    from core.part8_threads import (
        init_table,
        record_unclosed_thread,
        register_part8_thread_handlers,
    )

    db_path = tmp_path / "archer.db"
    init_table(db_path)
    record_unclosed_thread(
        db_path=db_path,
        session_id="s1",
        topic="Event Bus 串联 8.0",
        prompt="session_end 后只生成 shadow candidate",
        last_seen_at=datetime(2026, 6, 20, 9, 0, 0),
    )
    bus = ArcherEventBus()
    register_part8_thread_handlers(bus, db_path=db_path)

    bus.publish(
        ArcherEvent(
            type="session_end",
            source="test",
            payload={"sessionId": "s2", "presenceState": "idle"},
            created_at=datetime(2026, 6, 25, 9, 0, 0),
        )
    )

    logs = list_shadow_logs(db_path)
    assert len(logs) == 1
    assert logs[0]["kind"] == "thread_resume"
    assert logs[0]["delivered"] is False
    assert logs[0]["decision_trace"]["reason"] == "stale_open_thread"
