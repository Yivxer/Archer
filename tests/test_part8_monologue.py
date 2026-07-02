from datetime import datetime


def test_monologue_records_internal_thought_as_shadow_material(tmp_path):
    from core.monologue import init_table, list_monologues, record_monologue

    db_path = tmp_path / "archer.db"
    init_table(db_path)

    monologue_id = record_monologue(
        db_path=db_path,
        source="rules",
        thought="用户连续说继续，说明当前需要保持工程推进节奏。",
        trigger="session_end",
        now=datetime(2026, 6, 26, 9, 0, 0),
        trace={"reason": "continuation"},
    )

    items = list_monologues(db_path)

    assert items[0]["id"] == monologue_id
    assert items[0]["delivered"] is False
    assert items[0]["source"] == "rules"
    assert items[0]["trigger"] == "session_end"
    assert items[0]["trace"]["reason"] == "continuation"


def test_monologue_generation_uses_llm_until_daily_budget_is_exhausted(tmp_path):
    from core.monologue import generate_monologue, list_monologues

    db_path = tmp_path / "archer.db"
    calls = []

    def fake_llm(messages):
        calls.append(messages)
        return "这次会话的核心线索是 Part 8 需要小步推进。"

    first = generate_monologue(
        db_path=db_path,
        messages=[{"role": "user", "content": "继续做 Part 8"}],
        now=datetime(2026, 6, 26, 10, 0, 0),
        daily_llm_limit=1,
        llm_generator=fake_llm,
    )
    second = generate_monologue(
        db_path=db_path,
        messages=[{"role": "user", "content": "继续"}],
        now=datetime(2026, 6, 26, 11, 0, 0),
        daily_llm_limit=1,
        llm_generator=fake_llm,
    )

    assert first.source == "llm"
    assert second.source == "rules"
    assert second.trace["reason"] == "daily_llm_budget_exhausted"
    assert len(calls) == 1
    assert [item["source"] for item in list_monologues(db_path)] == ["rules", "llm"]


def test_rule_monologue_extracts_compact_signal_without_llm(tmp_path):
    from core.monologue import generate_monologue

    result = generate_monologue(
        db_path=tmp_path / "archer.db",
        messages=[
            {"role": "user", "content": "Archer 的 part8 继续做，先做线索层，不要真实推送。"},
            {"role": "assistant", "content": "我会先做 shadow。"},
        ],
        now=datetime(2026, 6, 26, 12, 0, 0),
        daily_llm_limit=0,
        llm_generator=lambda _messages: "should not be called",
    )

    assert result.source == "rules"
    assert "Archer" in result.thought
    assert "真实推送" in result.thought
    assert result.delivered is False


def test_clue_layer_records_unclosed_thread_from_session_messages(tmp_path):
    from core.part8_clues import extract_unclosed_thread, record_thread_clues_from_messages
    from core.part8_threads import list_open_threads

    db_path = tmp_path / "archer.db"
    messages = [
        {"role": "user", "content": "Archer 的 Part 8 继续做，先把线索层做完，后面再测试。"},
        {"role": "assistant", "content": "我先做 shadow 线索层。"},
    ]

    clue = extract_unclosed_thread(messages)
    created = record_thread_clues_from_messages(
        db_path=db_path,
        session_id="s1",
        messages=messages,
        now=datetime(2026, 6, 26, 13, 0, 0),
    )
    threads = list_open_threads(db_path)

    assert clue is not None
    assert clue.topic == "Archer 的 Part 8 继续做"
    assert created == [threads[0]["id"]]
    assert threads[0]["topic"] == "Archer 的 Part 8 继续做"
    assert "线索层做完" in threads[0]["prompt"]


def test_clue_layer_does_not_duplicate_same_open_topic(tmp_path):
    from core.part8_clues import record_thread_clues_from_messages
    from core.part8_threads import list_open_threads

    db_path = tmp_path / "archer.db"
    messages = [{"role": "user", "content": "视频剪辑计划继续，剪完第一版再回看节奏。"}]

    first = record_thread_clues_from_messages(
        db_path=db_path,
        session_id="s1",
        messages=messages,
        now=datetime(2026, 6, 26, 13, 0, 0),
    )
    second = record_thread_clues_from_messages(
        db_path=db_path,
        session_id="s2",
        messages=messages,
        now=datetime(2026, 6, 26, 14, 0, 0),
    )

    assert len(first) == 1
    assert second == []
    assert len(list_open_threads(db_path)) == 1


def test_chat_stream_records_monologue_and_thread_clue_shadow_material(tmp_path, monkeypatch):
    import memory.store as store
    from core.monologue import list_monologues
    from core.part8_threads import list_open_threads
    from terminal.api._tools import _iter_chat_chunks

    original_db_path = store.DB_PATH
    store.DB_PATH = tmp_path / "archer.db"
    try:
        store.init_db()
        monkeypatch.setattr("core.llm.stream_chat", lambda messages, **kwargs: iter(["ok"]))

        stream = _iter_chat_chunks(
            [{"role": "user", "content": "Archer 的 Part 8 继续做，先做线索层，后面我再测试。"}],
            memory_mode="off",
            obsidian_mode="off",
        )
        first_chunk = next(stream)

        monologues = list_monologues(store.DB_PATH)
        threads = list_open_threads(store.DB_PATH)
        assert first_chunk.get("type") in {"orchestrationEvent", "planEvent", "statusEvent", "toolEvent", "ready", "initiativeEvent"}
        assert monologues[0]["source"] == "rules"
        assert monologues[0]["delivered"] is False
        assert threads[0]["topic"] == "Archer 的 Part 8 继续做"
    finally:
        store.DB_PATH = original_db_path
