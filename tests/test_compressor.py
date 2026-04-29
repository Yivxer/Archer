from core.compressor import estimate_history_tokens, should_compress


def test_estimate_history_tokens_counts_content():
    history = [
        {"role": "user", "content": "x" * 400},
        {"role": "assistant", "content": "y" * 400},
    ]
    assert estimate_history_tokens(history) >= 200


def test_should_compress_uses_estimate_when_usage_missing():
    history = []
    for _ in range(6):
        history.append({"role": "user", "content": "x" * 400})
        history.append({"role": "assistant", "content": "y" * 400})
    assert should_compress(history, prompt_tokens=0, token_limit=500) is True


def test_should_compress_prefers_provider_usage_when_present():
    history = []
    for _ in range(6):
        history.append({"role": "user", "content": "x" * 400})
        history.append({"role": "assistant", "content": "y" * 400})
    assert should_compress(history, prompt_tokens=10, token_limit=500) is False
