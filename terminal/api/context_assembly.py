"""I/O-backed context assembly stages for Desktop chat turns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class ContextAssemblyResult:
    messages: list[dict]
    events: list[dict]


def assemble_memory_context(
    messages: list[dict],
    *,
    query: str,
    prior_history: list[dict],
    intent: str,
    needs_memory: bool,
    memory_mode: str,
    retrieve_limit: int,
    expert: dict,
    event_factory: Callable[..., dict],
    augment_query: Callable | None = None,
    retrieve: Callable | None = None,
    format_retrieval: Callable | None = None,
    expert_tags: Callable | None = None,
) -> ContextAssemblyResult:
    if memory_mode == "off":
        return ContextAssemblyResult(
            messages,
            [event_factory(
                "memory-retrieve", "memory.retrieve", "complete", "low",
                "记忆上下文已关闭", "mode: off, injected: False",
            )],
        )
    if memory_mode == "conservative" and not needs_memory:
        return ContextAssemblyResult(
            messages,
            [event_factory(
                "memory-retrieve", "memory.retrieve", "complete", "low",
                "保守模式：本轮未触发记忆检索",
                f"mode: {memory_mode}, intent: {intent}, needs_memory: False",
            )],
        )

    events = [event_factory(
        "memory-retrieve", "memory.retrieve", "running", "low",
        "检索与当前输入相关的本地记忆",
        f"mode: {memory_mode}, scope: local memory, limit: {retrieve_limit}",
    )]
    try:
        if augment_query is None:
            from core.context import augment_retrieval_query

            augment_query = augment_retrieval_query
        if retrieve is None or format_retrieval is None:
            from memory.retrieve import for_context, format_for_prompt

            retrieve = retrieve or for_context
            format_retrieval = format_retrieval or format_for_prompt
        if expert_tags is None:
            from core.experts import expert_memory_tags

            expert_tags = expert_memory_tags
        retrieval_kwargs = {
            "limit": retrieve_limit,
            "intent": intent,
            "tag_hints": expert_tags(expert) or None,
        }
        rewritten_query = augment_query(query, prior_history)
        try:
            core, related = retrieve(rewritten_query, **retrieval_kwargs)
        except TypeError as exc:
            if "tag_hints" not in str(exc):
                raise
            retrieval_kwargs.pop("tag_hints", None)
            core, related = retrieve(rewritten_query, **retrieval_kwargs)
        memory_context = format_retrieval(core, related)
        enriched = messages
        if memory_context:
            enriched = [{
                "role": "system",
                "content": (
                    "以下是 Archer 本地记忆检索结果。只在明显相关时使用；"
                    "不要主动逐条展示记忆内容，也不要声称已经展示全部记忆。\n\n"
                    f"{memory_context}"
                ),
            }, *messages]
        events.append(event_factory(
            "memory-retrieve", "memory.retrieve", "complete", "low",
            "已完成本地记忆检索",
            f"mode: {memory_mode}, core: {len(core)}, related: {len(related)}, injected: {bool(memory_context)}",
        ))
        return ContextAssemblyResult(enriched, events)
    except Exception as exc:
        events.append(event_factory(
            "memory-retrieve", "memory.retrieve", "blocked", "low",
            "本地记忆检索失败，已跳过", str(exc)[:240],
        ))
        return ContextAssemblyResult(messages, events)
