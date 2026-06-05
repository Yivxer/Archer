"""
a4.py — A4 记忆系统升级的轻量策略层

本模块先不改数据库 schema。
它提供：
- A4 记忆类型集合
- depth 规范化（1-5）
- metadata JSON 载体
- reflection_anchor 触发判断
- 检索候选排序/截断策略
"""
from __future__ import annotations

A4_MEMORY_TYPES = [
    "fact",
    "preference",
    "emotion_pattern",
    "value",
    "value_conflict",
    "life_theme",
    "self_narrative",
    "project_mythology",
    "relationship_pattern",
    "creative_identity",
    "growth_marker",
    "reflection_anchor",
]

_SOUL_TYPES = {
    "emotion_pattern",
    "value",
    "value_conflict",
    "life_theme",
    "self_narrative",
    "project_mythology",
    "relationship_pattern",
    "creative_identity",
    "growth_marker",
    "reflection_anchor",
}

_REFLECTION_ANCHOR_SIGNALS = (
    "不是工具",
    "灵魂伴侣",
    "灵魂伴生体",
    "自己能做",
    "尽量自己",
    "我发现",
    "我意识到",
    "我真正",
    "对我来说",
    "第一性原理",
    "见路不走",
)

_TASK_ONLY_SIGNALS = (
    "帮我改",
    "按钮",
    "bug",
    "报错",
    "运行",
    "测试",
    "生成",
)

_INTENT_TYPE_PRIORITY = {
    "reflection": {
        "reflection_anchor": 0,
        "life_theme": 1,
        "self_narrative": 2,
        "value": 3,
        "emotion_pattern": 4,
    },
    "emotional": {
        "emotion_pattern": 0,
        "reflection_anchor": 1,
        "recurring_fear": 2,
        "value_conflict": 3,
        "relationship_pattern": 4,
    },
    "project": {
        "project_mythology": 0,
        "creative_identity": 1,
        "growth_marker": 2,
        "value": 3,
    },
    "decision": {
        "value": 0,
        "value_conflict": 1,
        "life_theme": 2,
        "reflection_anchor": 3,
    },
}


def clamp_depth(value: object) -> int:
    """把 depth 规范到 1-5；1=事实，5=精神母题。"""
    try:
        depth = int(value)
    except Exception:
        depth = 3
    return max(1, min(5, depth))


def type_family(memory_type: str) -> str:
    if memory_type in _SOUL_TYPES:
        return "soul"
    if memory_type in {"fact", "preference"}:
        return "base"
    return "legacy"


def normalize_memory_candidate(candidate: dict) -> dict:
    """规范化 A4 候选记忆；metadata 作为未来不改 schema 的承载层。"""
    content = str(candidate.get("content", "")).strip()
    memory_type = str(candidate.get("type", "fact")).strip() or "fact"
    if memory_type not in A4_MEMORY_TYPES:
        memory_type = "fact"

    try:
        importance = int(candidate.get("importance", 3))
    except Exception:
        importance = 3
    importance = max(1, min(5, importance))

    depth = clamp_depth(candidate.get("depth", 3))
    metadata = dict(candidate.get("metadata") or {})
    metadata.update({
        "depth": depth,
        "type_family": type_family(memory_type),
    })

    return {
        "content": content,
        "tags": str(candidate.get("tags", "")).strip(),
        "type": memory_type,
        "importance": importance,
        "depth": depth,
        "metadata": metadata,
    }


def should_create_reflection_anchor(sentence: str) -> bool:
    """判断一句话是否像反思锚点，而不是普通执行请求。"""
    text = sentence.strip()
    if len(text) < 8:
        return False
    if any(signal in text for signal in _TASK_ONLY_SIGNALS) and not any(
        signal in text for signal in _REFLECTION_ANCHOR_SIGNALS
    ):
        return False
    return any(signal in text for signal in _REFLECTION_ANCHOR_SIGNALS)


def _memory_depth(memory: dict) -> int:
    if "depth" in memory:
        return clamp_depth(memory.get("depth"))
    metadata = memory.get("metadata") or {}
    if isinstance(metadata, dict):
        return clamp_depth(metadata.get("depth", 3))
    return 3


def select_context_memories(
    memories: list[dict],
    intent: str | None = None,
    trigger: str | None = None,
    limit: int = 7,
) -> list[dict]:
    """从候选记忆里选择本轮上下文，最多 7 条，深层/锚点优先。"""
    if limit <= 0:
        return []

    priority = _INTENT_TYPE_PRIORITY.get(intent or "", {})

    def score(memory: dict) -> tuple[int, int, int, int]:
        memory_type = memory.get("type", "")
        trigger_bonus = 0 if trigger and memory_type == trigger else 1
        type_rank = priority.get(memory_type, 20)
        depth_rank = -_memory_depth(memory)
        importance_rank = -int(memory.get("importance", 3) or 3)
        return (trigger_bonus, type_rank, depth_rank, importance_rank)

    return sorted(memories, key=score)[:limit]
