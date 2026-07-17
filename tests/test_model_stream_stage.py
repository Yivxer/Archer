import time

from terminal.api.model_stream import (
    build_rescue_messages,
    has_fake_tool_markup,
    iter_model_stream,
    iter_rescue_stream,
    model_trace_metadata,
    select_model_for_turn,
    split_safe_model_chunk,
    stream_failure_events,
)


def test_model_stream_stage_emits_chunks():
    assert list(iter_model_stream([{"role": "user", "content": "hi"}], stream=lambda _: iter(["a", "b"]))) == [
        {"type": "chunk", "text": "a"}, {"type": "chunk", "text": "b"},
    ]


def test_model_stream_uses_injected_llm_client():
    class FakeClient:
        def stream_chat(self, messages, **kwargs):
            return iter(["injected"])

    assert list(iter_model_stream(
        [{"role": "user", "content": "hi"}],
        llm_client=FakeClient(),
    )) == [{"type": "chunk", "text": "injected"}]


def test_model_stream_retries_recoverable_failure_before_first_chunk():
    calls = []
    delays = []

    def flaky(messages, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise TimeoutError("provider timeout")
        yield "ok"

    events = list(iter_model_stream(
        [{"role": "user", "content": "hi"}],
        stream=flaky,
        sleep=delays.append,
        random_value=lambda: 1.0,
    ))

    assert len(calls) == 3
    assert delays == [0.5, 1.0]
    assert [event["type"] for event in events] == ["retry", "retry", "chunk"]


def test_model_stream_does_not_retry_auth_or_after_visible_chunk():
    auth_calls = []

    def auth_failure(messages, **kwargs):
        auth_calls.append(1)
        raise RuntimeError("模型 API 鉴权失败：API key 无效")
        yield

    try:
        list(iter_model_stream([], stream=auth_failure, sleep=lambda _: None))
        assert False, "auth failure should propagate"
    except RuntimeError:
        pass
    assert len(auth_calls) == 1

    partial_calls = []

    def partial_failure(messages, **kwargs):
        partial_calls.append(1)
        yield "visible"
        raise TimeoutError("late timeout")

    try:
        list(iter_model_stream([], stream=partial_failure, sleep=lambda _: None))
        assert False, "partial failure should propagate"
    except TimeoutError:
        pass
    assert len(partial_calls) == 1


def test_model_stream_uses_one_visible_default_fallback_after_primary_exhausted():
    primary_calls = []
    fallback_calls = []

    def primary(messages, **kwargs):
        primary_calls.append(1)
        raise ConnectionError("offline")
        yield

    def fallback(messages, **kwargs):
        fallback_calls.append(kwargs["model"])
        yield "fallback-ok"

    events = list(iter_model_stream(
        [], stream=primary, fallback_stream=fallback,
        fallback_model="deepseek-chat", fallback_profile="lite",
        sleep=lambda _: None, random_value=lambda: 0.0,
    ))

    assert len(primary_calls) == 3
    assert fallback_calls == ["deepseek-chat"]
    assert events[-2:] == [
        {"type": "fallback", "attempt": 1, "maxAttempts": 1, "fallbackProfile": "lite", "model": "deepseek-chat"},
        {"type": "chunk", "text": "fallback-ok"},
    ]


def test_model_selection_detects_image_attachment():
    calls = []
    model = select_model_for_turn({}, query="look", intent="chat", needs_tools=False, file_refs=[{"type": "image"}], resolver=lambda config, **kwargs: (calls.append(kwargs) or "vision", {}))
    assert model == "vision"
    assert calls[0]["has_images"] is True


def test_model_trace_metadata_excludes_credentials_path_query_and_api_key():
    metadata = model_trace_metadata({
        "api": {
            "active_profile": "lite",
            "provider": "Kimi",
            "model": "kimi-k2",
            "base_url": "https://user:secret@api.example.com:8443/v1/chat?token=leak",
            "api_key": "sk-should-never-appear",
        },
        "model_profiles": {},
    }, "kimi-k2-fast")

    assert metadata == {
        "provider": "Kimi",
        "model": "kimi-k2-fast",
        "baseUrlSummary": "https://api.example.com:8443",
    }
    assert "secret" not in str(metadata)
    assert "sk-should-never-appear" not in str(metadata)


def test_safe_chunk_stops_before_split_dsml_markup():
    buffer, text, detected = split_safe_model_chunk("hello ", "｜｜DSML｜｜call")
    assert (buffer, text, detected) == ("hello ", "", True)
    assert has_fake_tool_markup("<tool_call>bad") is True


def test_stream_failure_events_have_terminal_order():
    events = stream_failure_events(TimeoutError("timeout"), trace_id="t1", hint_factory=lambda *args, **kwargs: {"traceId": kwargs["trace_id"]})
    assert [event["type"] for event in events] == ["token", "failureHintEvent", "error", "done"]


def test_rescue_messages_preserve_invalid_reply_as_assistant_context():
    messages = build_rescue_messages([{"role": "user", "content": "hi"}], "<tool_call>bad")
    assert messages[-2] == {"role": "assistant", "content": "<tool_call>bad"}
    assert "自然语言重新回答" in messages[-1]["content"]


def test_rescue_stream_emits_chunks_and_final_text():
    events = list(iter_rescue_stream(
        [{"role": "user", "content": "hi"}],
        "<tool_call>bad",
        model="test-model",
        stream=lambda messages, **kwargs: iter(["fixed ", "reply"]),
    ))

    assert events == [
        {"type": "chunk", "text": "fixed "},
        {"type": "chunk", "text": "reply"},
        {"type": "done", "text": "fixed reply"},
    ]


def test_rescue_stream_heartbeat_is_preserved():
    def delayed_stream(messages, **kwargs):
        time.sleep(0.02)
        yield "fixed"

    events = list(iter_rescue_stream(
        [{"role": "user", "content": "hi"}],
        "<tool_call>bad",
        model="test-model",
        stream=delayed_stream,
        heartbeat_seconds=0.001,
    ))

    assert {"type": "heartbeat"} in events
    assert events[-1] == {"type": "done", "text": "fixed"}


def test_rescue_stream_failure_returns_empty_done():
    def failing_stream(messages, **kwargs):
        raise RuntimeError("boom")
        yield

    assert list(iter_rescue_stream(
        [{"role": "user", "content": "hi"}],
        "<tool_call>bad",
        model="test-model",
        stream=failing_stream,
    )) == [{"type": "done", "text": ""}]
