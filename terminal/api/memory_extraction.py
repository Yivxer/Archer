"""Behavior-preserving background memory extraction stage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class MemoryExtractionPorts:
    extract: Callable
    save: Callable
    add_pending: Callable
    is_duplicate: Callable[[str], bool]
    is_low_quality: Callable[[str, str], bool]


@dataclass(frozen=True)
class MemoryExtractionResult:
    saved: int = 0
    staged: int = 0
    skipped_duplicate: int = 0
    skipped_low_quality: int = 0
    skip_reason: str = ""


def should_auto_save_memory(memory: dict, sensitive: bool) -> bool:
    if sensitive:
        return False
    memory_type = str(memory.get("type", "insight") or "insight")
    if memory_type in {
        "emotion_pattern", "value", "value_conflict", "life_theme",
        "self_narrative", "relationship_pattern", "project_mythology",
        "reflection_anchor",
    }:
        return False
    try:
        confidence = float(memory.get("confidence", 0.7) or 0.7)
    except Exception:
        confidence = 0.0
    try:
        depth = int(memory.get("depth", 3) or 3)
    except Exception:
        depth = 3
    return confidence >= 0.75 and depth <= 3


def _latest_user_text(history: list[dict]) -> str:
    for message in reversed(history):
        if message.get("role") == "user":
            return str(message.get("content", "") or "").strip()
    return ""


def _session_summary(history: list[dict]) -> str:
    for message in history:
        if message.get("role") == "user":
            content = str(message.get("content", "") or "").strip()
            if content:
                return content[:80]
    return ""


def extract_memories(
    history: list[dict], *, ports: MemoryExtractionPorts,
    orchestrate: Callable, build_policy: Callable, format_reason: Callable,
) -> MemoryExtractionResult:
    if len(history) < 2:
        return MemoryExtractionResult(skip_reason="history_too_short")

    latest_user = _latest_user_text(history)
    policy = None
    suggest_reason = ""
    if latest_user:
        policy = build_policy(orchestrate(latest_user, history=history[:-1]))
        if not policy.should_extract:
            return MemoryExtractionResult(skip_reason="candidate_policy")
        suggest_reason = format_reason(policy, latest_user)

    extract_kwargs = {}
    if policy:
        extract_kwargs = {
            "candidate_types": policy.candidate_types,
            "sensitive": policy.sensitive,
        }
    memories, _ = ports.extract(history, **extract_kwargs)
    saved = staged = skipped_duplicate = skipped_low_quality = 0
    session_summary = _session_summary(history)

    for memory in memories:
        content = memory.get("content", "")
        memory_type = memory.get("type", "insight")
        if ports.is_low_quality(content, memory_type):
            skipped_low_quality += 1
            continue
        if ports.is_duplicate(content):
            skipped_duplicate += 1
            continue

        common = {
            "content": content,
            "tags": memory.get("tags", ""),
            "type": memory_type,
            "importance": memory.get("importance", 3),
            "source": "desktop",
            "confidence": memory.get("confidence", 0.7),
            "depth": memory.get("depth", 3),
            "block_type": memory.get("block_type"),
            "label": memory.get("label"),
        }
        if should_auto_save_memory(memory, policy.sensitive if policy else False):
            ports.save(**common)
            saved += 1
        else:
            ports.add_pending(
                **common,
                suggest_reason=suggest_reason,
                session_summary=session_summary,
            )
            staged += 1

    return MemoryExtractionResult(
        saved=saved,
        staged=staged,
        skipped_duplicate=skipped_duplicate,
        skipped_low_quality=skipped_low_quality,
    )
