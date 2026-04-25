from memory.store import search, recent

def for_context(user_input: str = "", limit: int = 5) -> list[dict]:
    """检索与当前输入最相关的记忆，用于注入 system prompt。"""
    if user_input and len(user_input.strip()) >= 2:
        results = search(user_input.strip(), limit=limit)
        if results:
            return results
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
