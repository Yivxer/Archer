import time

from terminal.api.model_stream import (
    build_rescue_messages,
    has_fake_tool_markup,
    iter_model_stream,
    iter_rescue_stream,
    select_model_for_turn,
    split_safe_model_chunk,
    stream_failure_events,
)


def test_model_stream_stage_emits_chunks():
    assert list(iter_model_stream([{"role": "user", "content": "hi"}], stream=lambda _: iter(["a", "b"]))) == [
        {"type": "chunk", "text": "a"}, {"type": "chunk", "text": "b"},
    ]


def test_model_selection_detects_image_attachment():
    calls = []
    model = select_model_for_turn({}, query="look", intent="chat", needs_tools=False, file_refs=[{"type": "image"}], resolver=lambda config, **kwargs: (calls.append(kwargs) or "vision", {}))
    assert model == "vision"
    assert calls[0]["has_images"] is True


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
