"""job_enrichment.py — 后台 job 上下文增强 helper。

从 `job_routes.py` 抽出的 memory / web_search / web_fetch 上下文增强逻辑，
供 `_run_job_chat_with_tools` 和 `_run_isolated_child_job_chat` 复用，避免
逻辑漂移和重复代码。

设计约束：
- 只执行低风险只读操作（memory retrieval / web_search / web_fetch）
- 任何子步骤失败必须被吞掉并返回失败标记，不抛异常给上层
- 每个失败应记 structlog warning，带 job_id 便于定位
"""
from __future__ import annotations

import re
from typing import Any

from infrastructure.observability import get_logger

_log = get_logger("archer.job")


def enrich_with_memory(
    prompt: str,
    config: Any,
    intent_info: dict[str, Any],
    *,
    job_id: str,
) -> tuple[list[str], list[str]]:
    """检索本地记忆，返回 (system_context_parts, tool_parts)。

    失败时返回空列表并在 tool_parts 中加入失败标记。
    """
    system_parts: list[str] = []
    tool_parts: list[str] = []
    try:
        from core.agent_profile import build_personality_injection, join_profile_layers
        from core.experts import active_expert, expert_memory_tags, format_expert_block
        from memory.retrieve import for_context, format_for_prompt

        expert = active_expert(config)
        profile_block = join_profile_layers({
            "expert_overlay": format_expert_block(expert),
            "personality": build_personality_injection(expert),
        })
        if profile_block:
            system_parts.append(profile_block)

        retrieval_kwargs: dict[str, Any] = {
            "limit": 5,
            "intent": intent_info.get("intent", ""),
            "tag_hints": expert_memory_tags(expert) or None,
        }
        try:
            core, related = for_context(prompt, **retrieval_kwargs)
        except TypeError as exc:
            if "tag_hints" not in str(exc):
                raise
            retrieval_kwargs.pop("tag_hints", None)
            core, related = for_context(prompt, **retrieval_kwargs)
        mem_ctx = format_for_prompt(core, related)
        if mem_ctx:
            system_parts.append(
                "以下是 Archer 本地记忆检索结果。只在明显相关时使用。\n\n" + mem_ctx
            )
            tool_parts.append(f"[memory] 检索到 {len(core)}+{len(related)} 条相关记忆")
    except Exception as exc:
        tool_parts.append(f"[memory] 检索失败: {exc}")
        _log.warning("job_chat_memory_failed", job_id=job_id, error=str(exc))
    return system_parts, tool_parts


def enrich_with_web_search(
    prompt: str,
    *,
    job_id: str,
) -> tuple[list[str], list[str]]:
    """执行 web_search（如果 prompt 命中搜索意图），返回 (system_parts, tool_parts)。"""
    system_parts: list[str] = []
    tool_parts: list[str] = []
    try:
        from skills.web_search import run as web_search_run

        result = web_search_run({"query": prompt[:200], "max_results": 5})
        if result and not str(result).startswith("未找到"):
            system_parts.append(f"互联网搜索结果（{prompt[:80]}）：\n{result}")
            tool_parts.append("[web_search] 搜索完成")
    except Exception as exc:
        tool_parts.append(f"[web_search] 失败: {exc}")
        _log.warning("job_chat_web_search_failed", job_id=job_id, error=str(exc))
    return system_parts, tool_parts


def enrich_with_web_fetch(
    prompt: str,
    *,
    job_id: str,
) -> tuple[list[str], list[str]]:
    """如果 prompt 含 URL，执行 web_fetch，返回 (system_parts, tool_parts)。"""
    system_parts: list[str] = []
    tool_parts: list[str] = []
    url_match = re.search(r'https?://[^\s）)>"\'<\]]+', prompt)
    if not url_match:
        return system_parts, tool_parts
    target_url = url_match.group(0).rstrip(".。，,;；")
    try:
        from skills.web_fetch import run as web_fetch_run

        fetch = web_fetch_run({"url": target_url, "max_chars": 4000})
        if fetch:
            system_parts.append(f"网页内容（{target_url}）：\n{fetch}")
            tool_parts.append(f"[web_fetch] {target_url}")
    except Exception as exc:
        tool_parts.append(f"[web_fetch] 失败: {exc}")
        _log.warning(
            "job_chat_web_fetch_failed", job_id=job_id,
            url=target_url, error=str(exc),
        )
    return system_parts, tool_parts


def enrich_context_for_chat(
    prompt: str,
    config: Any,
    intent_info: dict[str, Any],
    selected_skills: dict[str, Any],
    *,
    job_id: str,
) -> tuple[list[str], list[str]]:
    """合并 memory + web_search + web_fetch 三个增强源。

    `selected_skills` 是 `_filter_api_skills_for_intent` 的返回值，用于判断
    是否触发 web_search / web_fetch。memory 始终尝试。
    """
    system_parts: list[str] = []
    tool_parts: list[str] = []

    mem_sys, mem_tools = enrich_with_memory(
        prompt, config, intent_info, job_id=job_id,
    )
    system_parts.extend(mem_sys)
    tool_parts.extend(mem_tools)

    if "web_search" in selected_skills:
        ws_sys, ws_tools = enrich_with_web_search(prompt, job_id=job_id)
        system_parts.extend(ws_sys)
        tool_parts.extend(ws_tools)

    if "web_fetch" in selected_skills:
        wf_sys, wf_tools = enrich_with_web_fetch(prompt, job_id=job_id)
        system_parts.extend(wf_sys)
        tool_parts.extend(wf_tools)

    return system_parts, tool_parts
