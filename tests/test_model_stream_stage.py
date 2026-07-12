from terminal.api.model_stream import iter_model_stream


def test_model_stream_stage_emits_chunks():
    assert list(iter_model_stream([{"role": "user", "content": "hi"}], stream=lambda _: iter(["a", "b"]))) == [
        {"type": "chunk", "text": "a"}, {"type": "chunk", "text": "b"},
    ]
