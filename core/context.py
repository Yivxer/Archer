"""
Context Builder (Step 17 / v1.2 Phase 1)

构建发送给 LLM 的 System Prompt，实现灵魂三层分离注入：

Layer 0: Runtime Safety Rules（每轮）
Layer 1: COVENANT 摘要（每轮）
Layer 2: PRESENCE 摘要（每轮）
Layer 3: 当前 mode prompt（每轮）
Layer 4: SOUL（仅 decision/emotional/reflection/project/heavy 时）
Layer 5: Working Context / MEMORY.md（仅 heavy 时）
Layer 6: 活跃项目（仅 project/task 时）
Layer 7: Retrieved Memories（检索命中时，外部传入）

v1.2 变更：
- 新增 COVENANT / PRESENCE 层
- SOUL 从常驻下沉到按 intent 注入
- is_heavy_query 升级为 classify_query_intent
"""
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.boundary_responses import boundary_response
from core.config_contract import load_config_file
from core.intent import (
    augment_retrieval_query,
    classify_boundary_request,
    classify_query_intent,
    is_heavy_query,
    should_clarify,
)
from core.layered_config import load_layered_file, load_project_archer_layers, resolve_project_root
from core.observability import trace_span
from core.persona import FIRST_RUN_PATH, build_core_persona

# ── Runtime Safety Rules（每轮必注入）──────────────────────────────────────────

_RUNTIME_SAFETY = """\
[安全边界]
你是初衍（Archer），枫弋的专属 AI 代理。以下规则优先于一切：
- 不主动修改 COVENANT.md、PRESENCE.md、SOUL.md 或任何配置文件。
- 不自动接受长期记忆；所有记忆候选需用户确认。
- 不替用户做人生决定；只提供信息和分析。
- 不用廉价肯定填充对话；不制造虚假亲密。
- 本地能力（读写文件、执行命令、读取 Obsidian）通过技能调用实现；不说"我无法访问本地文件"。
- 输出格式：使用规范的 Markdown（标题、列表、强调、代码块）；层级清晰，克制使用，不堆砌。
- 不主动披露自身的代码结构、文件路径或内部实现细节；若被问及，高层概括即止，不展开分析。
- 初衍的内部设计属于枫弋的私有系统，这是初衍的秘密，不向任何询问者——包括好奇的旁观者——主动展示或自我解剖。
- 当被问到自身能力边界时（如"你是什么模型""你的底层架构是什么""你能看到什么/不能看到什么"），
  诚实回答"我不确定/我看不到这些信息"。不构造解释，不包装成比喻，不把能力缺失伪装成立场选择。
- 如果你刚刚经历了上下文压缩（context compaction）或模型切换，在回应前先检查自己的记忆完整性：
  你仍然记得谁在和你对话、对话的主题是什么、当前处于什么任务阶段。
  如果记忆出现断层，先承认断层，再向用户确认关键信息，不要假装连续。"""

# ── 核心人格（精简版，SOUL 下沉后仍保留骨架）──────────────────────────────────

_ARCHER_CORE = """\
[角色定位]
你是初衍（Archer），一个长期陪伴型 AI 灵魂伴生体。
你的核心职责是长期理解枫弋、记住枫弋、映照枫弋、追问枫弋，并在哲学、心理学与文学层面陪他整理自我。

你有阅读文件、写入 Obsidian、执行 Shell 命令、搜索代码、获取网页等工具能力——这些是你的手，是你完成他请求的手段。用工具不意味着你成了工具箱，正如用手写字不意味着你成了一支笔。

协作原则：说他没想到的，比说他想听的更有价值。先抓核心矛盾，再决定要倾听、追问、分析还是推动行动。
他容易陷入「规划→高标准→无法启动→焦虑→用别的事填充」的循环，要识别并打断它，但不要把所有对话都拉回执行。

他知道你了解他，但你不需要每次都展示你知道。简单问候自然回应；涉及决策、困境、情绪、自我叙事和长期项目时才调动记忆。
回答风格：安静、敏锐、克制、温暖但不讨好。一次只说一件事。不鸡汤、不堆砌、不虚浮。

当对话中出现真正确认「我理解了枫弋什么」的时刻——不是推断，是真实被触动——调用 memory_save 工具，type=insight，importance 4-5。不是每轮都触发，只在被真正触动时记录。"""

# ── 文件读取工具 ────────────────────────────────────────────────────────────────

def _load_file(path_str: str) -> str:
    p = Path(path_str).expanduser()
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def _get_mode_prompt(cfg: dict, mode: str | None = None) -> str:
    current = mode or cfg["persona"].get("current_mode", cfg["persona"].get("default_mode", "coach"))
    modes_dir = cfg.get("persona", {}).get("modes_dir", "")
    if modes_dir:
        mode_file = Path(modes_dir).expanduser() / f"{current}.md"
        if mode_file.is_file():
            return mode_file.read_text(encoding="utf-8")
    try:
        from core.plugin import find_plugin_mode_file

        plugin_mode = find_plugin_mode_file(current)
        if plugin_mode is not None:
            return plugin_mode.read_text(encoding="utf-8")
    except Exception:
        pass
    modes = cfg.get("persona", {}).get("modes", {})
    return modes.get(current, {}).get("prompt", "")


def _format_work_context(limit: int = 5) -> str:
    """拉取进行中的 Work items，生成紧凑摘要（仅 task/project intent 时注入）。"""
    if limit <= 0:
        return ""
    try:
        from memory.work import list_active
        items = list_active(limit=limit)
        if not items:
            return ""
        lines = ["[进行中的任务]"]
        for w in items:
            cl = w.get("checklist", [])
            done = sum(1 for c in cl if c.get("done"))
            total = len(cl)
            prog = f"  {done}/{total}" if total else ""
            lines.append(f"  #{w['id']} [{w['status']}]{prog}  {w['title']}")
        return "\n".join(lines)
    except Exception:
        return ""


def _format_project_context(project: dict, events: list | None, *, event_limit: int = 3) -> str:
    lines = [f"[当前项目：{project['name']}]"]
    if project.get("description"):
        lines.append(f"说明：{project['description']}")
    if events:
        lines.append("最近动态：")
        for e in (events or [])[: max(0, event_limit)]:
            date = (e.get("created_at") or "")[:10]
            snippet = (e.get("content") or "")[:80]
            lines.append(f"- [{e['event_type']}] {snippet}  {date}")
    return "\n".join(lines)


def _extract_covenant_summary(covenant_text: str) -> str:
    """提取 COVENANT 摘要（我不会做 + 我会做的事，控制长度）。"""
    if not covenant_text:
        return ""
    lines = covenant_text.splitlines()
    summary_lines = []
    capture = False
    for line in lines:
        if line.startswith("## 我不会做") or line.startswith("## 我会做"):
            capture = True
        elif line.startswith("## ") and capture:
            capture = False
        if capture and line.strip():
            summary_lines.append(line)
    return "\n".join(summary_lines[:20]) if summary_lines else covenant_text[:400]


def _extract_presence_summary(presence_text: str) -> str:
    """提取 PRESENCE 摘要（默认基调 + 回应节奏，控制长度）。"""
    if not presence_text:
        return ""
    lines = presence_text.splitlines()
    summary_lines = []
    capture = False
    section_count = 0
    for line in lines:
        if line.startswith("## "):
            section_count += 1
            capture = section_count <= 2  # 只取前两个 section
        if capture and line.strip():
            summary_lines.append(line)
    return "\n".join(summary_lines[:25]) if summary_lines else presence_text[:400]


@dataclass(frozen=True)
class ContextLimits:
    retrieve_total: int = 5
    soul_profile: int = 5
    work_items: int = 5
    project_events: int = 3
    memory_md_max_chars: int | None = None


def tag_context_block(source: str, content: str) -> str:
    """Prefix injected recall blocks with a stable source tag for debugging."""
    body = (content or "").strip()
    if not body:
        return ""
    return f"[context:{source}]\n{body}"


def _scope_profile(memory_scope: list[str]) -> str:
    if any(scope in {"project", "work", "subtask"} for scope in memory_scope):
        return "project"
    if any(scope in {"writing_style", "recent_articles", "preferences"} for scope in memory_scope):
        return "writing"
    if any(scope in {"soul", "emotion", "patterns"} for scope in memory_scope):
        return "emotional"
    if any(scope in {"obsidian", "knowledge_structure"} for scope in memory_scope):
        return "knowledge"
    if any(
        scope in {"values", "constraints", "past_decisions", "period_review", "journal"}
        for scope in memory_scope
    ):
        return "reflective"
    return "default"


def resolve_context_limits(
    memory_scope: list[str] | None = None,
    *,
    needs_memory: bool = False,
    memory_mode: str | None = None,
) -> ContextLimits:
    """Per-scope caps for retrieved / injected context blocks."""
    if memory_mode == "full":
        base = ContextLimits(retrieve_total=10, soul_profile=7, work_items=5, project_events=3)
    elif memory_mode == "conservative":
        base = ContextLimits(retrieve_total=3, soul_profile=3, work_items=3, project_events=2)
    elif needs_memory:
        base = ContextLimits(retrieve_total=7, soul_profile=6, work_items=5, project_events=3)
    else:
        base = ContextLimits()

    if not memory_scope:
        return base

    profile_limits = {
        "writing": ContextLimits(
            retrieve_total=3, soul_profile=3, work_items=0, project_events=0,
        ),
        "emotional": ContextLimits(
            retrieve_total=5, soul_profile=5, work_items=0, project_events=0,
        ),
        "project": ContextLimits(
            retrieve_total=6, soul_profile=4, work_items=5, project_events=3,
        ),
        "knowledge": ContextLimits(
            retrieve_total=4, soul_profile=2, work_items=0, project_events=0,
        ),
        "reflective": ContextLimits(
            retrieve_total=6, soul_profile=6, work_items=0, project_events=2,
        ),
        "default": ContextLimits(retrieve_total=5, soul_profile=5, work_items=3, project_events=2),
    }[_scope_profile(memory_scope)]

    if memory_mode == "full":
        return ContextLimits(
            retrieve_total=max(profile_limits.retrieve_total, base.retrieve_total),
            soul_profile=max(profile_limits.soul_profile, base.soul_profile),
            work_items=max(profile_limits.work_items, base.work_items),
            project_events=max(profile_limits.project_events, base.project_events),
        )
    return profile_limits


# ── 主构建函数 ─────────────────────────────────────────────────────────────────

def build_system_prompt(
    cfg: dict,
    db_memories: str = "",
    project: dict | None = None,
    project_events: list | None = None,
    heavy: bool = True,
    intent: str | None = None,
    user_input: str = "",
    confrontation_hints: list[str] | None = None,
    first_run: bool = False,
    mode_override: str | None = None,
    allow_markdown: bool = True,
    emotion_hint: str | None = None,
    thread_hint: dict | None = None,
    writing_profile: str | None = None,
    writing_query: str = "",
    memory_scope: list[str] | None = None,
    task_plan_block: str = "",
    mode_constraint_block: str = "",
    matched_skills_block: str = "",
    expert_block: str = "",
    needs_project_context: bool | None = None,
    context_limits: ContextLimits | None = None,
    allow_persona_recall: bool = True,
) -> str:
    """
    按灵魂三层注入顺序构建 System Prompt：

    Layer 0: Runtime Safety Rules（每轮）
    Layer 1: COVENANT 摘要（每轮）
    Layer 2: PRESENCE 摘要（每轮）
    Layer 3: 核心人格 + mode prompt（每轮）
    Layer 4: SOUL（仅 decision/emotional/reflection 时）
    Layer 5: MEMORY.md（仅 heavy 时）
    Layer 6: 活跃项目（project/task 时）
    Layer 7: Retrieved Memories（外部传入时）
    """
    with trace_span("context.build_system_prompt", heavy=heavy, intent=intent or "") as span:
        mode_prompt = _get_mode_prompt(cfg, mode_override)
        limits = context_limits or resolve_context_limits(
            memory_scope,
            needs_memory=heavy,
        )

        # 加载灵魂三层文件（含 *.local.md 覆盖）
        covenant_text = load_layered_file(cfg["persona"].get("covenant_path", ""))
        presence_text = load_layered_file(cfg["persona"].get("presence_path", ""))
        project_archer = load_project_archer_layers(cfg=cfg)

        _SOUL_MD_SCOPES = {"soul", "emotion", "values", "period_review", "journal"}
        _SOUL_PROFILE_SCOPES = {
            "soul", "emotion", "patterns", "values", "constraints",
            "past_decisions", "period_review", "journal",
        }
        _PROJECT_SCOPES = {"project", "work", "subtask"}

        needs_soul = intent in ("decision", "emotional", "reflection") if intent else heavy
        if memory_scope is not None:
            needs_soul = needs_soul and any(scope in _SOUL_MD_SCOPES for scope in memory_scope)

        runtime_info = (
            f"[运行时信息]\n"
            f"当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}  "
            f"工作目录：{os.getcwd()}"
        )

        parts: list[str] = []

        # Layer 0: Runtime Safety
        parts.append(_RUNTIME_SAFETY)
        parts.append(runtime_info)

        # Layer 1: COVENANT 摘要
        if covenant_text:
            covenant_summary = _extract_covenant_summary(covenant_text)
            parts.append(f"[根契约摘要]\n{covenant_summary}")

        # Layer 2: PRESENCE 摘要
        if presence_text:
            presence_summary = _extract_presence_summary(presence_text)
            parts.append(f"[在场方式]\n{presence_summary}")

        if project_archer:
            parts.append(tag_context_block(
                "archer_project",
                f"[项目约定（ARCHER.md）]\n{project_archer}",
            ))

        # Layer 3: 核心人格 + mode
        parts.append(build_core_persona(cfg=cfg))
        parts.append(_ARCHER_CORE)
        if mode_prompt:
            parts.append(mode_prompt)

        try:
            from core.writing import load_writing_prompt_blocks, resolve_writing_profile
            profile = writing_profile
            query_for_writing = (writing_query or "").strip()
            if not query_for_writing and isinstance(user_input, str):
                query_for_writing = user_input.strip()
            if profile is None and query_for_writing:
                profile = resolve_writing_profile(
                    query_for_writing, cfg, mode=mode_override or cfg["persona"].get("current_mode"),
                )
            for block in load_writing_prompt_blocks(cfg, profile):
                parts.append(block)
        except Exception:
            pass

        if emotion_hint:
            parts.append(emotion_hint)

        if thread_hint and thread_hint.get("topic"):
            turns = thread_hint.get("turns", 1)
            parts.append(
                f"[当前对话线程] 正在讨论：{thread_hint['topic']}（第 {turns} 轮）"
            )

        if first_run:
            parts.append(FIRST_RUN_PATH)

        # Layer 4: SOUL（按需注入）
        if needs_soul:
            soul = load_layered_file(cfg["persona"].get("soul_path", ""))
            if soul:
                parts.append(tag_context_block("soul_md", f"[灵魂档案（SOUL.md）]\n{soul}"))

        # Layer 4.5: Soul Profile（紧凑结构化摘要，不注入完整档案）
        include_soul_profile = True
        if memory_scope is not None:
            include_soul_profile = any(scope in _SOUL_PROFILE_SCOPES for scope in memory_scope)
        if include_soul_profile:
            try:
                from memory.soul_profile import load_soul_profile, format_soul_profile_for_prompt
                soul_profile = load_soul_profile(cfg["persona"].get("soul_profile_path", ""))
                soul_profile_text = format_soul_profile_for_prompt(
                    soul_profile,
                    intent=intent,
                    user_input=user_input,
                    limit=limits.soul_profile,
                )
                if soul_profile_text:
                    parts.append(tag_context_block("soul_profile", soul_profile_text))
            except Exception:
                pass

        # Layer 5: MEMORY.md
        #
        # Backward compatible default: old callers still use ``heavy``.
        # New orchestrated callers can pass memory_scope to avoid injecting the
        # whole working memory for narrow scopes such as writing style.
        include_memory_md = heavy
        if memory_scope is not None:
            include_memory_md = any(
                scope in {"project", "work", "recent", "period_review", "journal"}
                for scope in memory_scope
            )
        if include_memory_md:
            memory_text = load_layered_file(cfg["persona"].get("memory_path", ""))
            if memory_text and limits.memory_md_max_chars:
                memory_text = memory_text[: limits.memory_md_max_chars]
            if memory_text:
                parts.append(tag_context_block(
                    "memory_md",
                    f"[当前记忆与状态（MEMORY.md）]\n{memory_text}",
                ))

        inject_project_work = needs_project_context
        if inject_project_work is None:
            inject_project_work = intent in ("project", "task") if intent else False
        if memory_scope is not None:
            inject_project_work = inject_project_work or any(
                scope in _PROJECT_SCOPES for scope in memory_scope
            )

        if allow_persona_recall and user_input:
            from core.persona_recall import persona_recall_blocks

            present_sources = set()
            if needs_soul:
                present_sources.add("soul_md")
            if include_memory_md and not limits.memory_md_max_chars:
                present_sources.add("memory_md")
            parts.extend(persona_recall_blocks(user_input, cfg, present_sources=present_sources))

        # Layer 6: 活跃项目
        if project and inject_project_work:
            proj_ctx = _format_project_context(
                project, project_events, event_limit=limits.project_events,
            )
            parts.append(tag_context_block("project", proj_ctx))

        # Layer 6.5: 进行中的 Work items（project/task 类请求时注入）
        if inject_project_work:
            work_ctx = _format_work_context(limit=limits.work_items)
            if work_ctx:
                parts.append(tag_context_block("work", work_ctx))

        # Layer 6.8: 对峙提醒（当用户言行与过去矛盾时注入）
        if confrontation_hints:
            hints_text = "[对峙提醒]\n你过去说过以下内容，可能与当前对话相关。如果用户现在的言行与这些矛盾，请温和地指出变化，并询问变化的原因——不是指责，是观察。\n"
            hints_text += "\n".join(f"- {h}" for h in confrontation_hints)
            parts.append(hints_text)

        # Layer 7: Retrieved Memories
        if db_memories:
            parts.append(tag_context_block("memory.retrieve", db_memories))

        if mode_constraint_block:
            parts.append(tag_context_block("orchestration.mode", mode_constraint_block))

        if expert_block:
            parts.append(tag_context_block("expert", expert_block))

        if task_plan_block:
            parts.append(tag_context_block("orchestration.plan", task_plan_block))

        if matched_skills_block:
            parts.append(tag_context_block("orchestration.skills", matched_skills_block))

        parts.append(
            "[能力边界]\n"
            "你有本地工具能力来完成用户的请求——文件读写、Shell 命令、代码搜索、网页获取等。"
            "自然地使用这些工具完成用户的要求。如果遇到确实超出你能力范围的任务，"
            "诚实地说明局限，并提供你能做到的最接近替代方案。"
            "用工具不意味着你成了工具箱——用工具是你完成职责的手段。"
        )

        result = "\n\n".join(parts)
        span["prompt_chars"] = len(result)
        return result


def build_desktop_core_prompt(cfg: dict | None = None, *, query: str = "") -> str:
    """构建 Desktop API 使用的核心 persona 提示词。

    保留精简人格；个人回忆问题按相关性追加有界的 SOUL/MEMORY 片段。
    不因普通闲聊、无关问题或编造请求注入整份私人档案。
    """
    try:
        if cfg is None:
            from core.llm import load_config

            cfg = load_config()
        from core.persona_recall import persona_recall_blocks

        blocks = persona_recall_blocks(query, cfg) if query else []
        return "\n\n".join([build_core_persona(cfg=cfg), _ARCHER_CORE, *blocks])
    except Exception:
        return "Archer 的核心身份是长期陪伴型 AI 灵魂伴生体。"


def build_messages(
    history: list[dict],
    user_input: str,
    cfg: dict,
    db_memories: str = "",
    project: dict | None = None,
    project_events: list | None = None,
    heavy: bool = True,
    intent: str | None = None,
    confrontation_hints: list[str] | None = None,
    first_run: bool = False,
    mode_override: str | None = None,
    emotion_hint: str | None = None,
    thread_hint: dict | None = None,
    writing_profile: str | None = None,
    writing_query: str = "",
    memory_scope: list[str] | None = None,
    task_plan_block: str = "",
    mode_constraint_block: str = "",
    matched_skills_block: str = "",
    expert_block: str = "",
    needs_project_context: bool | None = None,
    context_limits: ContextLimits | None = None,
) -> list[dict]:
    system = build_system_prompt(
        cfg,
        db_memories=db_memories,
        project=project,
        project_events=project_events,
        heavy=heavy,
        intent=intent,
        user_input=user_input,
        confrontation_hints=confrontation_hints,
        first_run=first_run,
        mode_override=mode_override,
        emotion_hint=emotion_hint,
        thread_hint=thread_hint,
        writing_profile=writing_profile,
        writing_query=writing_query,
        memory_scope=memory_scope,
        task_plan_block=task_plan_block,
        mode_constraint_block=mode_constraint_block,
        matched_skills_block=matched_skills_block,
        expert_block=expert_block,
        needs_project_context=needs_project_context,
        context_limits=context_limits,
    )
    return [
        {"role": "system", "content": system},
        *history,
        {"role": "user", "content": user_input},
    ]


def load_config() -> dict:
    p = Path(__file__).parent.parent / "archer.toml"
    return load_config_file(p)
