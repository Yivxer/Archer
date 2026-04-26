import json
from core.llm import stream_chat

_PROMPT = """\
你是严格的长期记忆提炼助手。分析对话，只提炼确定、稳定、未来仍有用的内容。

只记录这些内容：
- 用户明确表达的长期偏好、稳定习惯、价值判断
- 已经做出的决策，以及该决策未来会影响后续协作
- 长期项目的当前状态、关键约束、明确下一步
- 用户明确说“记住”“以后按这个来”“我想长期这样”

不要记录这些内容：
- 闲聊、临时调试、一次性任务执行细节
- UI 细节、代码改动过程、排查中的临时猜测
- 你自己的建议，除非用户明确采纳为决策
- 不确定、可能很快过期、只在当前会话有效的信息
- 已有记忆的同义重复

type 从以下分类中选一个：
- identity：身份信息（我是谁、价值观、核心特征）
- preference：偏好（做事方式、沟通风格、喜好）
- project：项目（进展、卡点、里程碑）
- decision：决策（做了哪个选择、为什么）
- todo：待办（要做什么、下一步）
- insight：洞察（学到了什么、新的理解）
- risk：风险（潜在问题、要警惕的事）
- context：临时上下文（当前场景）

如果提炼内容涉及以下情况，在 obsidian_hint 字段给出写回建议：
- 用户价值观/防御模式/核心特征变化 → "SOUL.md"
- 新项目/人生方向/当前目标变化 → "MEMORY.md"
- 否则留空字符串

以 JSON 格式返回：
{
  "memories": [
    {"content": "一句话中文记忆", "tags": "标签1,标签2", "type": "insight", "importance": 3, "obsidian_hint": ""}
  ]
}

importance: 1=低 3=中等 5=核心。identity 和 decision 类型至少给 4 分。
每次最多返回 3 条。拿不准就不要写入。
没有值得记住的内容返回 {"memories": []}。\
"""

_VALID_TYPES = {
    "identity", "preference", "project", "decision",
    "todo", "insight", "risk", "context",
}

def _clean_memory(m: dict) -> dict | None:
    content = str(m.get("content", "")).strip()
    if len(content) < 8:
        return None

    mtype = str(m.get("type", "insight")).strip()
    if mtype not in _VALID_TYPES:
        mtype = "insight"

    try:
        importance = int(m.get("importance", 3))
    except Exception:
        importance = 3
    importance = max(1, min(5, importance))

    # 临时上下文低价值时不写库，避免把一次性任务污染长期记忆。
    if mtype == "context" and importance < 4:
        return None

    if mtype in {"identity", "decision"}:
        importance = max(4, importance)

    return {
        "content": content,
        "tags": str(m.get("tags", "")).strip(),
        "type": mtype,
        "importance": importance,
        "confidence": 0.7,
        "obsidian_hint": str(m.get("obsidian_hint", "")).strip(),
    }

def extract(history: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    返回 (memories, obsidian_suggestions)
    obsidian_suggestions: [{"file": "SOUL.md|MEMORY.md", "content": "..."}]
    """
    if not history:
        return [], []

    turns = "\n".join(
        f"{'用户' if m['role'] == 'user' else 'Archer'}: {m['content']}"
        for m in history if m["role"] in ("user", "assistant")
    )

    messages = [
        {"role": "system", "content": _PROMPT},
        {"role": "user", "content": f"对话内容：\n\n{turns}"},
    ]

    raw = ""
    for chunk in stream_chat(messages, track_usage=False):
        raw += chunk

    try:
        s = raw.find("{")
        e = raw.rfind("}") + 1
        if s >= 0 and e > s:
            data = json.loads(raw[s:e])
            raw_memories = data.get("memories", [])
            memories = []
            seen = set()
            for item in raw_memories:
                if not isinstance(item, dict):
                    continue
                cleaned = _clean_memory(item)
                if not cleaned or cleaned["content"] in seen:
                    continue
                seen.add(cleaned["content"])
                memories.append(cleaned)
                if len(memories) >= 3:
                    break
            obsidian = [
                {"file": m["obsidian_hint"], "content": m["content"]}
                for m in memories if m.get("obsidian_hint")
            ]
            return memories, obsidian
    except Exception:
        pass

    return [], []
