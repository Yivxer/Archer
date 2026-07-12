from terminal.api.model_stream import iter_model_stream, select_model_for_turn


def test_model_stream_stage_emits_chunks():
    assert list(iter_model_stream([{"role": "user", "content": "hi"}], stream=lambda _: iter(["a", "b"]))) == [
        {"type": "chunk", "text": "a"}, {"type": "chunk", "text": "b"},
    ]


def test_model_selection_detects_image_attachment():
    calls = []
    model = select_model_for_turn({}, query="look", intent="chat", needs_tools=False, file_refs=[{"type": "image"}], resolver=lambda config, **kwargs: (calls.append(kwargs) or "vision", {}))
    assert model == "vision"
    assert calls[0]["has_images"] is True
