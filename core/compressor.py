"""
上下文压缩（对标 Claude Code 的 compaction 机制）。

策略：
  - 对话历史超过 COMPRESS_THRESHOLD 条消息时触发
  - 把早期历史（最近 KEEP_RECENT 条之前的部分）发给 LLM 生成摘要
  - 用一条 system 摘要消息替换早期历史，保留最近若干轮完整对话
  - 摘要本身也会记录"压缩前共 N 轮"，方便回溯
"""
from core.llm import stream_chat

COMPRESS_THRESHOLD = 20   # 超过 20 条消息（10 轮）触发
KEEP_RECENT        = 8    # 始终保留最近 8 条（4 轮）完整对话

_SYSTEM_PROMPT = """\
你是对话历史压缩助手。
将以下对话压缩成简洁的结构化摘要，保留：
- 用户当前正在做什么（进行中的任务、项目）
- 已做出的关键决策和结论
- 重要的上下文事实（路径、配置、选择了哪种方案）
- 未解决的问题或待确认事项

丢弃：闲聊、重复确认、已完成且无后续影响的细节。
输出控制在 200 字以内，使用要点列表。\
"""

def should_compress(history: list[dict]) -> bool:
    return len(history) >= COMPRESS_THRESHOLD

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
        "content": (
            f"[对话历史摘要｜原始 {total_rounds} 轮，已压缩]\n\n{summary}"
        ),
    }
    return [compressed_msg, *recent]

def _summarize(history: list[dict]) -> str:
    turns = "\n".join(
        f"{'用户' if m['role'] == 'user' else 'Archer'}: {m['content'][:300]}"
        for m in history
        if m["role"] in ("user", "assistant")
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": f"对话内容：\n\n{turns}"},
    ]
    result = ""
    for chunk in stream_chat(messages):
        result += chunk
    return result.strip()
