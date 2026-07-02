"""P5.10 — Token usage tracking tests."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.llm import get_last_usage, get_session_tokens, reset_session_tokens
from core.session import Session
from core.session_store import dump_session_file, load_session_payload, read_session_file
from core.token_usage import record_call_usage, reset_session_usage, status_payload
from terminal.api._routes import _save_session, payload_get
from terminal.state import State


@pytest.fixture(autouse=True)
def _reset_tokens():
    reset_session_usage()
    yield
    reset_session_usage()


def test_record_call_usage_accumulates_session_and_last_call():
    record_call_usage(prompt_tokens=100, completion_tokens=40, total_tokens=140)
    record_call_usage(prompt_tokens=50, completion_tokens=10, total_tokens=60)

    assert get_session_tokens() == 200
    assert get_last_usage() == {
        "prompt_tokens": 50,
        "completion_tokens": 10,
        "total_tokens": 60,
    }


def test_reset_session_tokens_clears_counters():
    record_call_usage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    reset_session_tokens()
    assert get_session_tokens() == 0
    assert get_last_usage()["total_tokens"] == 0


def test_state_exposes_session_token_usage():
    record_call_usage(prompt_tokens=12, completion_tokens=8, total_tokens=20)
    usage = State().session_token_usage
    assert usage["total_tokens"] == 20
    assert usage["call_count"] == 1


def test_session_save_persists_token_usage(tmp_path, monkeypatch):
    import core.session as sess_mod

    monkeypatch.setattr(sess_mod, "SESSIONS_DIR", tmp_path)
    record_call_usage(prompt_tokens=30, completion_tokens=20, total_tokens=50)

    session = Session()
    session.add("你好", "嗨")
    saved = session.save()
    raw = json.loads(saved.read_text(encoding="utf-8"))

    assert isinstance(raw, dict)
    assert len(raw["messages"]) == 2
    assert raw["tokenUsage"]["totalTokens"] == 50


def test_session_store_reads_legacy_list_and_new_object():
    messages, usage, meta = load_session_payload(
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hey"}]
    )
    assert len(messages) == 2
    assert usage is None
    assert meta is None

    wrapped, wrapped_usage, wrapped_meta = load_session_payload(
        {
            "messages": messages,
            "tokenUsage": {"totalTokens": 12, "promptTokens": 8, "completionTokens": 4, "callCount": 1},
            "meta": {"expertId": "developer", "expertLabel": "开发工程师"},
        }
    )
    assert len(wrapped) == 2
    assert wrapped_usage["totalTokens"] == 12
    assert wrapped_meta["expertId"] == "developer"


def test_status_route_includes_token_usage(monkeypatch):
    record_call_usage(prompt_tokens=100, completion_tokens=25, total_tokens=125)
    monkeypatch.setattr(
        "terminal.api._routes._load_config",
        lambda: {"context": {"token_limit": 1000}, "persona": {"mode_auto": True, "default_mode": "listener"}},
    )
    monkeypatch.setattr("terminal.api._routes._memory", lambda limit=100: [])
    monkeypatch.setattr("terminal.api._routes._skills", lambda: [])

    status, payload = payload_get("/status")

    assert status == 200
    assert payload["tokenUsage"]["sessionTotal"] == 125
    assert payload["tokenUsage"]["limit"] == 1000
    assert payload["tokenUsage"]["lastCallTotal"] == 125


def test_save_session_api_writes_token_usage(tmp_path, monkeypatch):
    monkeypatch.setattr("core.session.SESSIONS_DIR", tmp_path)
    record_call_usage(prompt_tokens=11, completion_tokens=9, total_tokens=20)

    result = _save_session(
        {
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "world"},
            ]
        }
    )

    path = tmp_path / f"{result['id']}.json"
    messages, usage, _meta = read_session_file(path)
    assert len(messages) == 2
    assert usage["totalTokens"] == 20


def test_llm_stream_chat_records_usage_when_enabled(monkeypatch):
    from core import llm

    class FakeUsage:
        prompt_tokens = 7
        completion_tokens = 3
        total_tokens = 10

    class FakeChunk:
        def __init__(self, *, content: str = "", usage=None):
            self.choices = [MagicMock(delta=MagicMock(content=content))] if content else []
            self.usage = usage

    class FakeStream:
        def __iter__(self):
            yield FakeChunk(content="hi")
            yield FakeChunk(usage=FakeUsage())

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = FakeStream()
    monkeypatch.setattr(llm, "_get_client", lambda: (fake_client, {"api": {"model": "test-model", "base_url": "http://test"}}))

    chunks = list(llm.stream_chat([{"role": "user", "content": "x"}], track_usage=True))

    assert "".join(chunks) == "hi"
    assert get_session_tokens() == 10


def test_status_payload_percent_used():
    record_call_usage(total_tokens=250)
    payload = status_payload(token_limit=1000)
    assert payload["percentUsed"] == 0.25
