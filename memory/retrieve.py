from memory.store import search, recent

def for_context(user_input: str = "", limit: int = 5) -> list[dict]:
    """检索与当前输入最相关的记忆，用于注入 system prompt。"""
    if user_input:
        seen, results = set(), []
        for word in [w for w in user_input if len(w) > 1][:4]:
            for m in search(word, limit=3):
                if m["id"] not in seen:
                    seen.add(m["id"])
                    results.append(m)
        if results:
            return results[:limit]
    return recent(limit)

def format_for_prompt(memories: list[dict]) -> str:
    if not memories:
        return ""
    lines = ["## 记忆库\n"]
    for m in memories:
        stars = "★" * min(m.get("importance", 3), 5)
        line = f"- [{stars}] {m['content']}"
        if m.get("tags"):
            line += f"  #{m['tags'].replace(',', ' #')}"
        lines.append(line)
    return "\n".join(lines)
