from terminal.api.model_stream import has_fake_tool_markup, iter_model_stream, select_model_for_turn, split_safe_model_chunk, stream_failure_events


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
