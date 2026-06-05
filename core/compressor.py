"""
上下文压缩（对标 Claude Code 的 compaction 机制）。

策略：
  - 对话历史超过 COMPRESS_THRESHOLD 条消息时触发
  - 把早期历史（最近 KEEP_RECENT 条之前的部分）发给 LLM 生成摘要
  - 用一条 system 摘要消息替换早期历史，保留最近若干轮完整对话
  - 摘要本身也会记录"压缩前共 N 轮"，方便回溯
"""
from core.llm import stream_chat

COMPRESS_THRESHOLD = 20       # 超过 20 条消息（10 轮）触发
KEEP_RECENT        = 8        # 始终保留最近 8 条（4 轮）完整对话
DEFAULT_TOKEN_LIMIT = 1_000_000
CHARS_PER_TOKEN_ESTIMATE = 4

_SYSTEM_PROMPT = """\
你是对话历史压缩助手。把旧对话压缩成稳定、可继续执行的结构化上下文。

必须按以下格式输出，缺失则写“无”：
当前任务：
- ...

已确认决策：
- ...

关键事实：
- ...

文件与路径：
- ...

待办/未解决：
- ...

用户偏好：
- ...

要求：
- 只保留未来继续对话需要的信息。
- 保留具体文件名、路径、命令、配置值、已采用方案。
- 不保留闲聊、重复确认、已完成且无后续影响的过程细节。
- 不编造，不确定就不要写。
- 总长度控制在 500 字以内。\
"""

def should_compress(
    history: list[dict],
    *,
    prompt_tokens: int = 0,
    token_limit: int = DEFAULT_TOKEN_LIMIT,
) -> bool:
    has_compressible_history = len(history) > KEEP_RECENT + 1
    effective_tokens = prompt_tokens or estimate_history_tokens(history)
    if has_compressible_history and token_limit > 0 and effective_tokens >= token_limit:
        return True
    return len(history) >= COMPRESS_THRESHOLD


def estimate_history_tokens(history: list[dict]) -> int:
    """Provider 不返回 usage 时的本地粗估，偏保守触发压缩即可。"""
    chars = 0
    for msg in history:
        content = msg.get("content", "")
        if isinstance(content, str):
            chars += len(content)
        else:
            chars += len(str(content))
        chars += len(str(msg.get("role", ""))) + 4
    return max(1, chars // CHARS_PER_TOKEN_ESTIMATE)

def compress(history: list[dict]) -> list[dict]:
    """
    压缩历史，返回新的 history 列表。
    结构：[system 摘要消息, ...最近 KEEP_RECENT 条]
    """
    if len(history) <= KEEP_RECENT:
        return history

    old    = history[:-KEEP_RECENT]
    recent = history[-KEEP_RECENT:]

    summary = _summarize(old)
    total_rounds = len(history) // 2

    compressed_msg = {
        "role": "system",
        "content": f"[对话历史摘要｜原始 {total_rounds} 轮，已压缩]\n\n{summary}",
    }
    return [compressed_msg, *recent]

def _summarize(history: list[dict]) -> str:
    turns = "\n".join(
        f"{'用户' if m['role'] == 'user' else 'Archer'}: {m['content'][:800]}"
        for m in history
        if m["role"] in ("user", "assistant")
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": f"对话内容：\n\n{turns}"},
    ]
    result = ""
    for chunk in stream_chat(messages, track_usage=False):
        result += chunk
    return result.strip()
