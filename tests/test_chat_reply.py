from types import SimpleNamespace

from terminal.api.chat_reply import ChatReplyDependencies, iter_chat_reply_events


def _collect(generator):
    events = []
    while True:
        try:
            events.append(next(generator))
        except StopIteration as done:
            return events, done.value


def _dependencies(*, stream, rescue=None, fake=False):
    return ChatReplyDependencies(
        select_model=lambda config, **kwargs: "test-model",
        load_config=lambda: {},
        iter_stream=stream,
        iter_rescue=rescue or (lambda *args, **kwargs: iter([{"type": "done", "text": ""}])),
        has_fake_markup=lambda text: fake,
        split_safe_chunk=lambda buffer, chunk: (buffer + chunk, chunk, False),
        failure_events=lambda exc, **kwargs: [{"type": "error", "detail": str(exc)}],
        empty_events=lambda **kwargs: [{"type": "empty"}],
    )


def test_chat_reply_streams_chunks_and_returns_full_reply():
    events, reply = _collect(iter_chat_reply_events(
        [{"role": "user", "content": "hi"}], query="hi", intent="chat", file_refs=[],
        selected_tools={}, memory_scope=[], trace_id="trace-1", had_tool_activity=False,
        runtime_context=None,
        dependencies=_dependencies(stream=lambda *args, **kwargs: iter([{"type": "chunk", "text": "hello"}])),
    ))

    assert events == [{"type": "token", "text": "hello"}]
    assert reply == "hello"


def test_chat_reply_emits_heartbeat_and_uses_runtime_llm_client():
    client = object()
    captured = []

    def stream(messages, **kwargs):
        captured.append(kwargs["llm_client"])
        return iter([{"type": "heartbeat"}, {"type": "chunk", "text": "ok"}])

    events, reply = _collect(iter_chat_reply_events(
        [], query="hi", intent="chat", file_refs=[], selected_tools={"web_search": object()},
        memory_scope=["local"], trace_id="trace-1", had_tool_activity=False,
        runtime_context=SimpleNamespace(llm_client=client), dependencies=_dependencies(stream=stream),
    ))

    assert captured == [client]
    assert events[0]["statusEvent"]["intentLabel"] == "模型响应中"
    assert reply == "ok"


def test_chat_reply_replaces_fake_markup_with_rescue_reply():
    events, reply = _collect(iter_chat_reply_events(
        [], query="hi", intent="chat", file_refs=[], selected_tools={}, memory_scope=[], trace_id="trace-1",
        had_tool_activity=False, runtime_context=None,
        dependencies=_dependencies(
            stream=lambda *args, **kwargs: iter([{"type": "chunk", "text": "<tool_call>"}]),
            rescue=lambda *args, **kwargs: iter([{"type": "chunk", "text": "fixed"}, {"type": "done", "text": "fixed"}]),
            fake=True,
        ),
    ))

    assert events[-1] == {"type": "token", "text": "fixed"}
    assert reply == "fixed"


def test_chat_reply_failure_returns_none_after_terminal_events():
    def failing_stream(*args, **kwargs):
        raise RuntimeError("boom")
        yield

    events, reply = _collect(iter_chat_reply_events(
        [], query="hi", intent="chat", file_refs=[], selected_tools={}, memory_scope=[], trace_id="trace-1",
        had_tool_activity=False, runtime_context=None, dependencies=_dependencies(stream=failing_stream),
    ))

    assert events == [{"type": "error", "detail": "boom"}]
    assert reply is None


def test_chat_reply_emits_empty_receipt_for_blank_reply():
    events, reply = _collect(iter_chat_reply_events(
        [], query="hi", intent="chat", file_refs=[], selected_tools={}, memory_scope=[], trace_id="trace-1",
        had_tool_activity=True, runtime_context=None,
        dependencies=_dependencies(stream=lambda *args, **kwargs: iter([])),
    ))

    assert events == [{"type": "empty"}]
    assert reply == ""
