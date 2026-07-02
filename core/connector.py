"""Part 8.4 explainable cross-memory connections.

The first creative connector trusts only explicit memory tags. It identifies
possible associations without mutating memories or presenting them to users.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MemoryConnection:
    left_id: int | str
    right_id: int | str
    shared_tags: tuple[str, ...]
    score: float


def find_memory_connections(
    memories: list[dict[str, Any]],
    *,
    limit: int = 5,
) -> list[MemoryConnection]:
    """Find distinct memory pairs with one or more explicitly shared tags."""
    connections: list[MemoryConnection] = []
    for index, left in enumerate(memories):
        left_id = left.get("id") if isinstance(left, dict) else None
        if left_id is None:
            continue
        left_tags = _tags(left)
        if not left_tags:
            continue
        for right in memories[index + 1 :]:
            right_id = right.get("id") if isinstance(right, dict) else None
            if right_id is None or right_id == left_id:
                continue
            shared = tuple(tag for tag in left_tags if tag in set(_tags(right)))
            if not shared:
                continue
            connections.append(
                MemoryConnection(
                    left_id=left_id,
                    right_id=right_id,
                    shared_tags=shared,
                    score=round(min(0.9, 0.5 + len(shared) * 0.1), 3),
                )
            )
    connections.sort(key=lambda item: (-item.score, str(item.left_id), str(item.right_id)))
    return connections[: max(1, min(int(limit), 20))]


def _tags(memory: dict[str, Any]) -> tuple[str, ...]:
    raw = memory.get("tags") or ""
    values = raw.split(",") if isinstance(raw, str) else raw if isinstance(raw, (list, tuple, set)) else []
    seen: set[str] = set()
    tags: list[str] = []
    for value in values:
        tag = str(value or "").strip()
        if tag and tag not in seen:
            seen.add(tag)
            tags.append(tag)
    return tuple(tags)
