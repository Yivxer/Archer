import json
from core.llm import stream_chat

_PROMPT = """\
你是记忆提炼助手。分析对话，提炼值得长期记住的内容。

只记录有长期价值的内容：用户的决策、状态变化、重要信息、值得追踪的事。
不记录闲聊、已知背景、本次临时任务细节。

以 JSON 数组返回，格式：
[{"content": "一句话中文记忆", "tags": "标签1,标签2", "importance": 3}]

importance: 1=低 3=中等 5=核心。没有值得记住的内容返回 []。\
"""

def extract(history: list[dict]) -> list[dict]:
    if not history:
        return []

    turns = "\n".join(
        f"{'用户' if m['role'] == 'user' else 'Archer'}: {m['content']}"
        for m in history if m["role"] in ("user", "assistant")
    )

    messages = [
        {"role": "system", "content": _PROMPT},
        {"role": "user", "content": f"对话内容：\n\n{turns}"},
    ]

    raw = ""
    for chunk in stream_chat(messages):
        raw += chunk

    try:
        s = raw.find("[")
        e = raw.rfind("]") + 1
        if s >= 0 and e > s:
            return json.loads(raw[s:e])
    except Exception:
        pass

    return []
