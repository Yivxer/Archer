"""
soul.py — SOUL.md 演化系统

规则：
- 永不自动覆写 SOUL.md
- 所有变更以 diff proposal 形式呈现，用户审阅后才能写入
- 写入方式：在 SOUL.md 末尾追加带时间戳的演化记录块
- 识别触发词：identity/decision 类型记忆，或 obsidian_hint == 'SOUL.md'
"""
from datetime import datetime
from pathlib import Path

from memory.store import add_soul_proposal, list_soul_proposals, resolve_soul_proposal


# 触发 SOUL 演化提议的记忆类型
SOUL_RELEVANT_TYPES = {"identity", "decision"}
# 触发提议的最低重要度
SOUL_MIN_IMPORTANCE = 4


def should_propose(memory: dict) -> bool:
    """判断一条记忆是否值得生成 SOUL 演化提议。"""
    if memory.get("obsidian_hint") == "SOUL.md":
        return True
    if memory.get("type") in SOUL_RELEVANT_TYPES and memory.get("importance", 0) >= SOUL_MIN_IMPORTANCE:
        return True
    return False


def propose_from_memories(memories: list[dict], source: str = "reflect") -> list[int]:
    """
    从一批记忆中过滤出 SOUL 相关的内容，生成提议。
    返回新创建的提议 ID 列表。
    """
    ids = []
    for m in memories:
        if should_propose(m):
            pid = add_soul_proposal(m["content"], source=source)
            ids.append(pid)
    return ids


def propose_from_obsidian_hints(hints: list[dict], source: str = "extract") -> list[int]:
    """从 extract.py 返回的 obsidian_hints 中过滤 SOUL.md 相关内容，生成提议。"""
    ids = []
    for hint in hints:
        if hint.get("file") == "SOUL.md" and hint.get("content", "").strip():
            pid = add_soul_proposal(hint["content"], source=source)
            ids.append(pid)
    return ids


def get_pending() -> list[dict]:
    return list_soul_proposals("pending")


def accept(pid: int | str, soul_path: str) -> tuple[list[int], list[str]]:
    """
    接受提议，追加写入 SOUL.md。
    返回 (处理的ID列表, 写入的内容列表)。
    永不覆写原文，只在文件末尾追加。
    """
    proposals = list_soul_proposals("pending")
    if str(pid) != "all":
        proposals = [p for p in proposals if p["id"] == int(pid)]

    if not proposals:
        return [], []

    path = Path(soul_path).expanduser()
    if not path.exists():
        return [], []

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines_to_append = []
    for p in proposals:
        lines_to_append.append(
            f"\n\n---\n## 演化记录 [{now_str}]\n\n{p['content']}\n"
        )

    with open(path, "a", encoding="utf-8") as f:
        f.writelines(lines_to_append)

    ids = resolve_soul_proposal(pid, accepted=True)
    written = [p["content"] for p in proposals]
    return ids, written


def reject(pid: int | str) -> list[int]:
    return resolve_soul_proposal(pid, accepted=False)
