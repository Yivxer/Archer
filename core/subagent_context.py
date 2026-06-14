"""P5.4 — Subagent / child-job isolated context helpers."""
from __future__ import annotations

from typing import Mapping

MAX_PARALLEL_CHILD_JOBS = 3

SUBTASK_ALLOW_LIST = frozenset({
    "web_search",
    "web_fetch",
    "file_ops",
    "file_search",
    "obsidian_read",
    "obsidian_search",
    "code_search",
    "pdf_reader",
    "rss_reader",
    "weather",
})

SUBTASK_ENRICHMENT_SKILLS = frozenset({"web_search", "web_fetch"})


def build_subagent_system_prompt(
    cfg: dict,
    task_title: str,
    task_prompt: str,
    *,
    agent_type: str | None = None,
) -> str:
    """Minimal persona for isolated subtasks (no Soul/Memory/work context)."""
    from core.context import build_desktop_core_prompt
    from memory.subtask import get_agent_system_prompt

    core = build_desktop_core_prompt()
    agent_block = ""
    if agent_type:
        agent_block = get_agent_system_prompt(agent_type) + "\n\n"

    title = (task_title or "子任务").strip()
    prompt = (task_prompt or "").strip()
    return (
        f"{core}\n\n"
        f"{agent_block}"
        "[子任务隔离模式]\n"
        "你在独立子任务上下文中运行：不访问主对话历史、完整 Soul 分层或长期记忆检索。\n"
        "默认仅可使用只读类工具（搜索、读取、抓取）。副作用工具在后台子任务中不可用。\n"
        "只完成下方任务并返回简洁结果。\n\n"
        f"任务标题：{title}\n"
        f"任务目标：{prompt}"
    )


def filter_subagent_skills(skills: Mapping[str, object]) -> dict:
    return {name: mod for name, mod in skills.items() if name in SUBTASK_ALLOW_LIST}


def select_subagent_enrichment_skills(user_input: str) -> frozenset[str]:
    """Pick read-only enrichment tools for isolated background jobs."""
    from core.skill_router import select_skills
    from skills.loader import load_skills

    routed = select_skills(user_input, filter_subagent_skills(load_skills()))
    return frozenset(name for name in routed if name in SUBTASK_ENRICHMENT_SKILLS)


def is_isolated_job(job: dict | None) -> bool:
    if not job:
        return False
    if job.get("isolated") is True:
        return True
    return bool(job.get("parentJobId"))
