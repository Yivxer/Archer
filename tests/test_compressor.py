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


# ── 长上下文压力测试（50+ 轮对话）───────────────────────────────────────────

def _build_long_history(rounds: int = 55, chars_per_msg: int = 600) -> list[dict]:
    """构造 rounds 轮（2*rounds 条消息）合成对话历史。"""
    history: list[dict] = []
    for i in range(rounds):
        history.append({"role": "user", "content": f"第 {i+1} 轮用户消息：" + "z" * chars_per_msg})
        history.append({"role": "assistant", "content": f"第 {i+1} 轮回复：" + "w" * chars_per_msg})
    return history


def test_should_compress_triggers_on_55_rounds():
    """55 轮（110 条消息）远超 COMPRESS_THRESHOLD(20)，必须触发。"""
    history = _build_long_history(rounds=55)
    assert should_compress(history) is True


def test_should_compress_triggers_on_50_rounds_with_low_token_limit():
    """50 轮 + 低 token_limit 时，基于本地估算也应触发。"""
    history = _build_long_history(rounds=50)
    assert should_compress(history, prompt_tokens=0, token_limit=10_000) is True


def test_estimate_history_tokens_grows_with_rounds():
    """token 估算应随轮数线性增长，50 轮远大于 10 轮。"""
    small = _build_long_history(rounds=10, chars_per_msg=400)
    large = _build_long_history(rounds=50, chars_per_msg=400)
    small_tokens = estimate_history_tokens(small)
    large_tokens = estimate_history_tokens(large)
    assert large_tokens > small_tokens * 4
    assert large_tokens > 10_000


def test_trim_preserves_recent_50_rounds():
    """_trim_model_messages_for_context 在 50+ 轮时保留 system 前缀和最近消息。"""
    from terminal.api._tools import _trim_model_messages_for_context

    messages = [{"role": "system", "content": "system prompt"}]
    for idx in range(55):
        messages.append({"role": "user", "content": f"压力测试用户第 {idx} 轮"})
        messages.append({"role": "assistant", "content": f"压力测试回复第 {idx} 轮"})
    messages.append({"role": "user", "content": "最终任务：请总结以上对话"})

    trimmed = _trim_model_messages_for_context(messages, keep_recent=10, threshold=20)

    assert trimmed[0] == {"role": "system", "content": "system prompt"}
    assert "[长上下文保护]" in trimmed[1]["content"]
    assert "[线程情境胶囊]" in trimmed[1]["content"]
    assert "旧对话已省略" not in trimmed[1]["content"]
    assert "压力测试用户第 0 轮" in trimmed[1]["content"]
    assert trimmed[-1]["content"] == "最终任务：请总结以上对话"
    assert len(trimmed) <= 13
    assert all("压力测试用户第 0 轮" not in str(m.get("content", "")) for m in trimmed[2:])


def test_trim_preserves_multiple_system_prefixes_under_50_rounds():
    """50+ 轮时多个 system 前缀（安全规则、用户偏好）必须全部保留。"""
    from terminal.api._tools import _trim_model_messages_for_context

    messages = [
        {"role": "system", "content": "核心系统提示"},
        {"role": "system", "content": "安全规则：禁止未经确认的远程部署"},
        {"role": "system", "content": "用户偏好：Obsidian vault 边界不可越界"},
    ]
    for idx in range(55):
        messages.append({"role": "user", "content": f"长对话用户消息 {idx}"})
        messages.append({"role": "assistant", "content": f"长对话回复 {idx}"})

    trimmed = _trim_model_messages_for_context(messages, keep_recent=12, threshold=40)
    joined = "\n".join(str(item.get("content", "")) for item in trimmed)

    assert trimmed[0]["content"] == "核心系统提示"
    assert "安全规则" in joined
    assert "用户偏好" in joined
    assert "[长上下文保护]" in joined
    assert "[线程情境胶囊]" in joined
    assert "目标：长对话用户消息 0" in joined
    assert "长对话回复 54" in joined


def test_trim_does_not_activate_below_threshold():
    """9 轮（19 条消息）不超 threshold=20，不应触发裁剪。"""
    from terminal.api._tools import _trim_model_messages_for_context

    messages = [{"role": "system", "content": "sys"}]
    for idx in range(9):
        messages.append({"role": "user", "content": f"u{idx}"})
        messages.append({"role": "assistant", "content": f"a{idx}"})

    trimmed = _trim_model_messages_for_context(messages, keep_recent=10, threshold=20)
    assert trimmed == messages
