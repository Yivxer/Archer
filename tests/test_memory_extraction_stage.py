from types import SimpleNamespace
import sqlite3

from core.runtime_context import create_runtime_context
from memory.store import init_db
from terminal.api.memory_extraction import (
    MemoryExtractionPorts,
    build_runtime_memory_extraction_ports,
    extract_memories,
)


def _ports(memories, *, saved=None, pending=None, duplicate=None, low_quality=None):
    saved = saved if saved is not None else []
    pending = pending if pending is not None else []
    return MemoryExtractionPorts(
        extract=lambda history, **kwargs: (memories, {}),
        save=lambda **kwargs: saved.append(kwargs),
        add_pending=lambda **kwargs: pending.append(kwargs),
        is_duplicate=lambda content: bool(duplicate and duplicate(content)),
        is_low_quality=lambda content, memory_type: bool(low_quality and low_quality(content, memory_type)),
    )


def _policy(*, should_extract=True, sensitive=False, candidate_types=None):
    return SimpleNamespace(
        should_extract=should_extract,
        sensitive=sensitive,
        candidate_types=candidate_types or ["insight"],
    )


def _extract(history, ports, policy):
    return extract_memories(
        history,
        ports=ports,
        orchestrate=lambda latest, history: object(),
        build_policy=lambda orchestration: policy,
        format_reason=lambda active_policy, latest: "candidate reason",
    )


def test_memory_extraction_policy_skip_does_not_call_model():
    ports = _ports([])
    ports.extract = lambda history, **kwargs: (_ for _ in ()).throw(AssertionError("model called"))

    result = _extract(
        [{"role": "user", "content": "remember this"}, {"role": "assistant", "content": "ok"}],
        ports,
        _policy(should_extract=False),
    )

    assert result.skip_reason == "candidate_policy"


def test_memory_extraction_filters_duplicate_and_low_quality_memories():
    ports = _ports(
        [
            {"content": "duplicate", "type": "insight"},
            {"content": "low", "type": "insight"},
        ],
        duplicate=lambda content: content == "duplicate",
        low_quality=lambda content, memory_type: content == "low",
    )

    result = _extract(
        [{"role": "user", "content": "remember this"}, {"role": "assistant", "content": "ok"}],
        ports,
        _policy(),
    )

    assert result.skipped_duplicate == 1
    assert result.skipped_low_quality == 1
    assert result.saved == result.staged == 0


def test_memory_extraction_auto_saves_high_confidence_memory():
    saved = []
    ports = _ports(
        [{"content": "stable preference", "type": "preference", "confidence": 0.9, "depth": 2}],
        saved=saved,
    )

    result = _extract(
        [{"role": "user", "content": "remember this"}, {"role": "assistant", "content": "ok"}],
        ports,
        _policy(),
    )

    assert result.saved == 1
    assert saved[0]["content"] == "stable preference"


def test_memory_extraction_stages_sensitive_memory_with_session_summary():
    pending = []
    ports = _ports(
        [{"content": "private fact", "type": "insight", "confidence": 0.95, "depth": 1}],
        pending=pending,
    )

    result = _extract(
        [{"role": "user", "content": "a" * 100}, {"role": "assistant", "content": "ok"}],
        ports,
        _policy(sensitive=True),
    )

    assert result.staged == 1
    assert pending[0]["suggest_reason"] == "candidate reason"
    assert pending[0]["session_summary"] == "a" * 80


def test_runtime_memory_extraction_ports_isolate_database_and_llm(tmp_path):
    class FakeClient:
        def stream_chat(self, messages, **kwargs):
            return iter(['{"memories":[{"content":"isolated stable preference","type":"preference","confidence":0.9,"depth":2}]}'])

        def chat(self, messages, **kwargs):
            return ""

    first = create_runtime_context(
        db_path=tmp_path / "first.db",
        llm_client=FakeClient(),
    )
    second = create_runtime_context(
        db_path=tmp_path / "second.db",
        llm_client=FakeClient(),
    )
    init_db(first.db_path)
    init_db(second.db_path)

    ports = build_runtime_memory_extraction_ports(first)
    result = _extract(
        [{"role": "user", "content": "remember this preference"}, {"role": "assistant", "content": "ok"}],
        ports,
        _policy(),
    )

    assert result.staged == 1
    with sqlite3.connect(first.db_path) as connection:
        assert connection.execute("SELECT content FROM pending_memories").fetchone()[0] == "isolated stable preference"
    with sqlite3.connect(second.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM pending_memories").fetchone()[0] == 0
