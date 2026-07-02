"""
memory_save — 主动保存记忆或心迹（v1.5）

让 LLM 在对话中主动调用，将值得保留的内容写入记忆库。

两种使用场景：
  insight（默认）：被触动的理解时刻，"我这次真正理解了什么"。
                  不是推断，是确认。触发条件稀少，有意义才记。
  memory：一般性长期记忆（偏好、事实、决策等）。
"""

SKILL = {
    "name": "memory_save",
    "description": "主动保存记忆或心迹到记忆库",
    "version": "1.0.0",
    "author": "archer-builtin",
}


def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "memory_save",
            "description": (
                "将值得长期保留的内容写入记忆库。"
                "两种场景：\n"
                "1. insight（心迹）：对话中真正被触动、确认理解了用户什么的时刻。"
                "不是每轮都触发——只在真实发生改变时记录。"
                "importance 建议 4-5。\n"
                "2. memory（记忆）：需要长期记住的偏好、事实、决策或上下文。"
                "importance 建议 2-4。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "要保存的内容，一句话描述，简洁具体",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["insight", "memory", "preference", "decision", "todo", "context"],
                        "description": "记忆类型，默认 insight",
                    },
                    "importance": {
                        "type": "integer",
                        "description": "重要性 1-5，insight 建议 4-5，一般记忆建议 2-3",
                    },
                    "tags": {
                        "type": "string",
                        "description": "标签（逗号分隔），如 '枫弋,写作,洞察'",
                    },
                },
                "required": ["content"],
            },
        },
    }


def run(args: dict) -> str:
    content    = (args.get("content") or "").strip()
    mtype      = args.get("type", "insight")
    importance = int(args.get("importance") or (4 if mtype == "insight" else 3))
    tags       = (args.get("tags") or "").strip()

    if not content:
        return "保存失败：content 不能为空"

    valid_types = {"insight", "memory", "preference", "decision", "todo", "context",
                   "identity", "project", "risk", "reflection"}
    if mtype not in valid_types:
        mtype = "insight"

    importance = max(1, min(5, importance))

    try:
        from core.context import load_config
        from core.experts import active_expert, merge_expert_tags

        cfg = load_config()
        tags = merge_expert_tags(tags, active_expert(cfg))
    except Exception:
        pass

    try:
        from memory.store import save
        mid = save(content, tags=tags, type=mtype, importance=importance)
        type_label = "心迹" if mtype == "insight" else "记忆"
        return f"已保存{type_label} #{mid}（importance={importance}）：{content[:60]}"
    except Exception as e:
        return f"保存失败：{e}"
