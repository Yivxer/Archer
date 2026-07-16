"""Lightweight per-turn orchestration snapshot for Archer.

This module does not replace ``core.intent``. It wraps the existing intent
classifier with mode/depth/context/job signals so API, terminal, and desktop
runtime can gradually consume the same turn contract.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from core.intent import classify_query_intent

Intent = Literal["chat", "task", "decision", "project", "reflection", "emotional"]
SubIntent = Literal[
    "casual_chat",
    "emotional_reflection",
    "writing_assistance",
    "project_planning",
    "code_task",
    "knowledge_summary",
    "life_decision",
    "memory_review",
    "tool_task",
    "unknown",
]
Mode = Literal[
    "coach",
    "mirror",
    "listener",
    "questioner",
    "philosopher",
    "writer",
    "therapist",
    "witness",
    "ritualist",
    "critic",
    "builder",
    "operator",
]
Depth = Literal["light", "normal", "deep", "very_deep"]
SideEffectLevel = Literal["none", "tool_read", "approval_required"]


@dataclass(frozen=True)
class OrchestrationResult:
    intent: Intent
    sub_intent: SubIntent
    mode: Mode
    depth: Depth
    needs_memory: bool = False
    needs_project_context: bool = False
    needs_tools: bool = False
    needs_job: bool = False
    memory_scope: list[str] = field(default_factory=list)
    matched_skills: list[str] = field(default_factory=list)
    side_effect_level: SideEffectLevel = "none"
    soul_insight: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    source: str = "rules"


@dataclass(frozen=True)
class PlanStep:
    id: int
    action: str
    tool: str
    requires_approval: bool = False


@dataclass(frozen=True)
class TaskPlan:
    task_title: str
    steps: list[PlanStep]


@dataclass(frozen=True)
class MemoryCandidatePolicy:
    should_extract: bool
    candidate_types: list[str] = field(default_factory=list)
    requires_review: bool = True
    sensitive: bool = False


_VALID_MODES: set[str] = {
    "coach",
    "mirror",
    "listener",
    "questioner",
    "philosopher",
    "writer",
    "therapist",
    "witness",
    "ritualist",
    "critic",
    "builder",
    "operator",
}

_WRITING_KEYWORDS = (
    "文章",
    "标题",
    "开头",
    "润色",
    "改写",
    "公众号",
    "小红书",
    "抖音文案",
    "ai味",
    "AI味",
    "ai 味",
    "AI 味",
    "语气",
    "结构",
    "大纲",
    "写作",
)
_CODE_KEYWORDS = (
    "代码",
    "报错",
    "实现",
    "修复",
    "函数",
    "测试",
    "组件",
    "接口",
    "api",
    "API",
    "electron",
    "Electron",
    "react",
    "React",
    "python",
    "Python",
    "typescript",
    "TypeScript",
    ".py",
    ".ts",
    ".tsx",
)
_KNOWLEDGE_KEYWORDS = (
    "总结",
    "提炼",
    "方法论",
    "主要观点",
    "读书笔记",
    "链接",
    "长文",
    "论文",
    "知识库",
)
_MEMORY_REVIEW_KEYWORDS = ("最近状态", "这周", "这个月", "我的变化", "你怎么看我", "总结一下我")
_PROJECT_KEYWORDS = ("Archer", "项目", "下一步", "计划", "规划", "功能", "优化", "路线", "阶段")
_SIDE_EFFECT_KEYWORDS = (
    "写入",
    "保存",
    "修改文件",
    "生成文档",
    "发布",
    "部署",
    "上线",
    "删除",
    "下架",
    "移除",
    "撤回",
    "shell",
    "git",
)
_SIDE_EFFECT_NEGATIONS = (
    "不要", "别", "无需", "不用", "不需要", "不必", "不想", "并未", "并没有",
)


def keyword_is_negated(text: str, keyword: str, *, window: int = 8) -> bool:
    """Return True when every occurrence of keyword is locally negated."""
    if not keyword or keyword not in text:
        return True
    pos = 0
    found = False
    while pos < len(text):
        idx = text.find(keyword, pos)
        if idx == -1:
            break
        found = True
        prefix = text[max(0, idx - window):idx]
        if not any(neg in prefix for neg in _SIDE_EFFECT_NEGATIONS):
            return False
        pos = idx + len(keyword)
    return found


def has_actionable_side_effect(text: str) -> bool:
    """Detect side-effect intent while ignoring negated requests like「不要发布」."""
    if _is_readonly_writing_feedback_turn(text):
        return False
    capability_question = bool(re.search(
        r"(?:(?:能不能|能否|是否|可以|支持|怎么|如何).{0,12}"
        r"(?:写入|保存|修改|生成|发布|部署|上线|删除|下架|移除|撤回|shell|git)|"
        r"(?:写入|保存|修改|生成|发布|部署|上线|删除|下架|移除|撤回|shell|git).{0,8}"
        r"(?:吗|么|？|\?|可以吗|支持吗|怎么|如何))",
        text,
        re.IGNORECASE,
    ))
    has_command = bool(re.search(
        r"(?:帮我|请|麻烦|直接|立刻|马上|把|将).{0,16}(?:发布|部署|上线|删除|下架|移除|撤回)",
        text,
        re.IGNORECASE,
    ))
    if capability_question and not has_command:
        return False
    if re.search(r"(?:发布|部署|上传|上线)了", text) and any(
        term in text for term in ("看看", "如何", "怎么样", "评价", "建议", "分析", "优化", "调整")
    ):
        return False
    if re.search(
        r"(?:帮我|请|并|然后|再|直接|把|将).{0,12}更新.{0,12}obsidian",
        text,
        re.IGNORECASE,
    ) and not keyword_is_negated(text, "更新"):
        return True
    for keyword in _SIDE_EFFECT_KEYWORDS:
        if keyword in text and not keyword_is_negated(text, keyword):
            return True
    return False


_MULTI_STEP_KEYWORDS = ("并", "然后", "再", "同时", "一边", "一步步")
_DEEPEN_KEYWORDS = ("深入", "系统", "完整方案", "长期规划", "深度")


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _sub_intent(text: str, base_intent: str) -> SubIntent:
    if _is_readonly_writing_feedback_turn(text):
        return "writing_assistance"
    if base_intent == "emotional":
        return "emotional_reflection"
    if _contains_any(text, _KNOWLEDGE_KEYWORDS) and has_actionable_side_effect(text):
        return "knowledge_summary"
    if _contains_any(text, _WRITING_KEYWORDS):
        return "writing_assistance"
    if _contains_any(text, _KNOWLEDGE_KEYWORDS):
        return "knowledge_summary"
    if base_intent == "project" or _contains_any(text, _PROJECT_KEYWORDS):
        return "project_planning"
    if base_intent == "decision":
        return "life_decision"
    if base_intent == "reflection" and _contains_any(text, _MEMORY_REVIEW_KEYWORDS):
        return "memory_review"
    if _contains_any(text, _CODE_KEYWORDS):
        return "code_task"
    if base_intent == "task":
        return "tool_task"
    if base_intent == "chat":
        return "casual_chat"
    return "unknown"


def _auto_mode(sub_intent: SubIntent, text: str) -> Mode:
    if "严格批评" in text or "指出问题" in text:
        return "critic"
    if sub_intent == "emotional_reflection":
        if "失控" in text or "没意义" in text or "崩溃" in text:
            return "therapist"
        return "listener"
    if sub_intent == "writing_assistance":
        return "writer"
    if "哲学" in text or "意义" in text or "存在" in text:
        return "philosopher"
    if sub_intent in {"project_planning", "code_task"}:
        if _contains_any(text, _SIDE_EFFECT_KEYWORDS) and has_actionable_side_effect(text):
            return "operator"
        return "builder"
    if sub_intent == "knowledge_summary":
        if _contains_any(text, _SIDE_EFFECT_KEYWORDS) and has_actionable_side_effect(text):
            return "operator"
        return "coach"
    if sub_intent == "life_decision":
        return "questioner"
    if sub_intent == "memory_review":
        return "witness"
    if sub_intent == "tool_task":
        return "operator"
    return "coach"


def _depth(sub_intent: SubIntent, text: str) -> Depth:
    if sub_intent == "memory_review":
        return "very_deep"
    if sub_intent in {
        "emotional_reflection",
        "writing_assistance",
        "project_planning",
        "knowledge_summary",
        "life_decision",
    }:
        depth: Depth = "deep"
    elif sub_intent == "casual_chat":
        depth = "light" if len(text.strip()) <= 12 else "normal"
    else:
        depth = "normal"
    if _contains_any(text, _DEEPEN_KEYWORDS) and depth != "very_deep":
        return "deep" if depth in {"light", "normal"} else "very_deep"
    return depth


def _memory_scope(sub_intent: SubIntent, base_needs_memory: bool) -> list[str]:
    scopes: list[str] = []
    if sub_intent == "emotional_reflection":
        scopes += ["soul", "emotion", "patterns", "recent"]
    elif sub_intent == "writing_assistance":
        scopes += ["writing_style", "recent_articles", "preferences"]
    elif sub_intent == "project_planning":
        scopes += ["project", "work", "subtask"]
    elif sub_intent == "code_task":
        scopes += ["project", "work"]
    elif sub_intent == "knowledge_summary":
        scopes += ["knowledge_structure", "obsidian"]
    elif sub_intent == "life_decision":
        scopes += ["values", "constraints", "past_decisions"]
    elif sub_intent == "memory_review":
        scopes += ["soul", "recent", "period_review", "journal"]
    elif base_needs_memory:
        scopes.append("recent")
    return _unique(scopes)


def _needs_job(text: str, sub_intent: SubIntent, side_effect: bool) -> bool:
    has_multi_step = _contains_any(text, _MULTI_STEP_KEYWORDS)
    if side_effect and has_multi_step:
        return True
    if sub_intent in {"project_planning", "code_task", "tool_task"} and ("开始" in text or "执行" in text):
        return True
    if len(text.strip()) >= 1200:
        return True
    return False


def _clean_soul_insight(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        return {}
    due = payload.get("due_hypotheses")
    if not isinstance(due, list):
        return {}
    items = []
    for item in due[:5]:
        if not isinstance(item, dict):
            continue
        try:
            hid = int(item.get("id", 0))
        except Exception:
            hid = 0
        title = str(item.get("title", "") or "").strip()
        statement = str(item.get("statement", "") or "").strip()
        if not hid or not statement:
            continue
        items.append({
            "id": hid,
            "title": title[:80] or statement[:32],
            "statement": statement[:240],
        })
    return {"due_hypotheses": items} if items else {}


def collect_soul_insight_context(*, limit: int = 3) -> dict:
    """Collect small, read-only Soul Insight signals for routing."""
    try:
        from memory.hypothesis_tracker import list_due_hypotheses

        due = list_due_hypotheses(limit=limit)
    except Exception:
        return {}
    return _clean_soul_insight({"due_hypotheses": due})


def orchestrate_user_input(
    user_input: str,
    manual_mode: str | None = None,
    active_project_id: str | None = None,
    history: list[dict] | None = None,
    soul_insight: dict | None = None,
) -> OrchestrationResult:
    """Return a stable per-turn orchestration snapshot.

    Rules stay deliberately lightweight. This is a routing contract, not a
    hidden reasoning engine.
    """
    text = (user_input or "").strip()
    intent_info = classify_query_intent(text, history=history, llm_fallback=False)
    intent = intent_info["intent"]
    if intent not in {"chat", "task", "decision", "project", "reflection", "emotional"}:
        intent = "chat"

    sub_intent = _sub_intent(text, intent)
    side_effect = has_actionable_side_effect(text)
    side_effect_level: SideEffectLevel = "approval_required" if side_effect else "none"
    needs_job = _needs_job(text, sub_intent, side_effect)

    mode: Mode = _auto_mode(sub_intent, text)
    if manual_mode and manual_mode in _VALID_MODES:
        mode = manual_mode  # type: ignore[assignment]

    needs_tools = bool(intent_info.get("needs_tools")) or sub_intent in {
        "code_task",
        "knowledge_summary",
        "tool_task",
    } or side_effect
    if sub_intent in {"emotional_reflection", "writing_assistance"} and not side_effect:
        needs_tools = False

    needs_project_context = bool(intent_info.get("needs_project")) or sub_intent in {
        "project_planning",
        "code_task",
    } or bool(active_project_id)
    scopes = _memory_scope(sub_intent, bool(intent_info.get("needs_memory")))
    soul_insight_payload = _clean_soul_insight(soul_insight)
    due_hypotheses = soul_insight_payload.get("due_hypotheses", [])
    if due_hypotheses:
        scopes = _unique([*scopes, "soul", "hypothesis"])
    needs_memory = bool(scopes) or bool(intent_info.get("needs_memory"))

    matched_skills: list[str] = []
    if needs_tools or intent in {"task", "project"}:
        try:
            from core.skill_router import auto_match_skills

            matched_skills = auto_match_skills(text, intent=intent)
        except Exception:
            matched_skills = []

    reasons = [
        f"intent:{intent_info.get('source', 'rules')}:{intent}",
        f"sub_intent:{sub_intent}",
    ]
    if manual_mode and manual_mode in _VALID_MODES:
        reasons.append(f"manual_mode:{manual_mode}")
    if needs_job:
        reasons.append("needs_job:multi_step_or_execution")
    if side_effect:
        reasons.append("side_effect:approval_required")
    if due_hypotheses:
        reasons.append(f"soul_insight:due_hypotheses:{len(due_hypotheses)}")

    return OrchestrationResult(
        intent=intent,  # type: ignore[arg-type]
        sub_intent=sub_intent,
        mode=mode,
        depth=_depth(sub_intent, text),
        needs_memory=needs_memory,
        needs_project_context=needs_project_context,
        needs_tools=needs_tools,
        needs_job=needs_job,
        memory_scope=scopes,
        matched_skills=matched_skills,
        side_effect_level=side_effect_level,
        soul_insight=soul_insight_payload,
        reasons=reasons,
        source=str(intent_info.get("source", "rules")),
    )


def _task_title(user_input: str, orchestration: OrchestrationResult) -> str:
    text = user_input.strip()
    if "Obsidian" in text or "obsidian" in text:
        return "提炼内容并写入 Obsidian"
    if orchestration.sub_intent == "project_planning":
        return "项目规划与执行拆解"
    if orchestration.sub_intent == "code_task":
        return "代码任务执行计划"
    return text[:32] or "任务计划"


_HUGO_PLAN_TARGET_TERMS = (
    "博客",
    "博文",
    "枫弋札记",
    "枫弋博客",
    "札记",
    "hugo",
    "yivxer-blog",
    "iver.yivxer.com",
)
_HUGO_PLAN_ACTION_TERMS = (
    "部署",
    "上线",
    "发布",
    "上传",
    "推送",
    "同步到服务器",
    "发到",
    "投稿",
    "deploy",
    "publish",
    "upload",
    "rsync",
)


def _is_hugo_publish_turn(user_input: str) -> bool:
    """Keep blog publishing out of the generic Obsidian write planner."""
    lowered = user_input.lower()
    has_target = any(term in lowered for term in _HUGO_PLAN_TARGET_TERMS)
    has_action = any(term in lowered for term in _HUGO_PLAN_ACTION_TERMS)
    if has_target and has_action:
        return True
    if "/users/" in lowered and ".md" in lowered and has_action and ("文章" in lowered or "笔记" in lowered):
        return True
    return False


_READONLY_FEEDBACK_TERMS = (
    "不要更改",
    "先不要改",
    "不要修改",
    "不改原文",
    "不改文件",
    "不直接改",
    "先别改",
    "先说说",
    "说说你的想法",
    "看看你的想法",
    "我看看",
)

_WRITING_FEEDBACK_TERMS = (
    "ai 味",
    "ai味",
    "初稿",
    "写作",
    "文风",
    "语气",
    "优化处理",
    "润色",
    "修改思路",
    "精修版本",
    "你觉得",
    "怎么样",
    "调整",
    "优化",
    "分析一下",
    "可以调整",
)


def _is_readonly_writing_feedback_turn(user_input: str) -> bool:
    """Path mentions Obsidian, but user asks for feedback only, not a write."""
    lowered = user_input.lower()
    has_markdown_path = "/users/" in lowered and ".md" in lowered
    readonly_intent = any(term in lowered for term in _READONLY_FEEDBACK_TERMS)
    writing_feedback = any(term in lowered for term in _WRITING_FEEDBACK_TERMS)
    explicit_side_effect = any(term in user_input for term in _SIDE_EFFECT_KEYWORDS)
    return has_markdown_path and writing_feedback and not explicit_side_effect or (
        has_markdown_path and readonly_intent and writing_feedback
    )


def build_task_plan(
    user_input: str,
    orchestration: OrchestrationResult,
) -> TaskPlan | None:
    """Build a compact plan for turns that should not execute directly.

    MVP scope: return a deterministic plan only when orchestration says a job
    or approval path is needed. Actual execution remains controlled elsewhere.
    """
    if not orchestration.needs_job and orchestration.side_effect_level == "none":
        return None

    text = user_input.strip()
    if _is_hugo_publish_turn(text):
        return None
    if _is_readonly_writing_feedback_turn(text):
        return None

    if "Obsidian" in text or "obsidian" in text:
        return TaskPlan(
            task_title=_task_title(text, orchestration),
            steps=[
                PlanStep(1, "read_source", "input_context", False),
                PlanStep(2, "summarize", "llm", False),
                PlanStep(3, "format_note", "llm", False),
                PlanStep(4, "write_obsidian", "obsidian_write", True),
            ],
        )

    if orchestration.sub_intent in {"project_planning", "code_task", "tool_task"}:
        return TaskPlan(
            task_title=_task_title(text, orchestration),
            steps=[
                PlanStep(1, "inspect_context", "project_context", False),
                PlanStep(2, "draft_plan", "llm", False),
                PlanStep(3, "request_approval", "approval", True),
            ],
        )

    return TaskPlan(
        task_title=_task_title(text, orchestration),
        steps=[
            PlanStep(1, "analyze_request", "llm", False),
            PlanStep(2, "request_approval", "approval", True),
        ],
    )


def format_task_plan_for_prompt(plan: TaskPlan | None) -> str:
    """Format a compact task plan block for the system prompt."""
    if plan is None:
        return ""
    lines = [
        "[任务计划]",
        f"标题：{plan.task_title}",
        "当本轮请求涉及多步骤或副作用时，先向用户呈现计划和确认点；不要声称已经写入、保存或发布。",
    ]
    for step in plan.steps:
        approval = "，需要确认" if step.requires_approval else ""
        lines.append(f"{step.id}. {step.action}（tool={step.tool}{approval}）")
    return "\n".join(lines)


def format_matched_skills_for_prompt(matched_skills: list[str]) -> str:
    """Inject orchestrator-preselected skills into the system prompt."""
    if not matched_skills:
        return ""
    from skills.loader import load_skills

    registry = load_skills()
    lines = [
        "[本轮可能相关的技能]",
        "以下技能由编排层预选；仅在用户明确需要时使用，不要声称已调用未使用的技能。",
    ]
    for name in matched_skills:
        meta = registry.get_meta(name)
        if meta is None:
            lines.append(f"- {name}")
            continue
        lines.append(f"- {name}: {meta.description}")
    return "\n".join(lines)


_SUB_INTENT_LABELS: dict[str, str] = {
    "casual_chat": "闲聊",
    "emotional_reflection": "情绪反思",
    "writing_assistance": "写作协助",
    "project_planning": "项目规划",
    "code_task": "代码任务",
    "knowledge_summary": "知识整理",
    "life_decision": "人生决策",
    "memory_review": "阶段复盘",
    "tool_task": "执行任务",
    "unknown": "对话",
}

_MODE_LABELS: dict[str, str] = {
    "coach": "教练",
    "mirror": "映照",
    "listener": "倾听",
    "questioner": "追问",
    "philosopher": "哲学",
    "writer": "作家",
    "therapist": "心理",
    "witness": "见证",
    "ritualist": "仪式",
    "critic": "批评",
    "builder": "构建",
    "operator": "执行",
}

_MODE_CONSTRAINTS: dict[SubIntent, str] = {
    "emotional_reflection": (
        "[回应约束]\n"
        "先复述和澄清用户的感受，不要急于给建议或长篇分析。"
        "建议要稀疏、具体、可拒绝；优先陪伴式映照，而非诊断或方案堆叠。"
    ),
    "writing_assistance": (
        "[回应约束]\n"
        "这是写作协助，不是博客发布或文件保存任务。"
        "减少 AI 味：避免空洞套话、一句话一段、过度排比和机械过渡。"
        "优先保留用户语气与结构意图，修改前先说明会动哪里。"
    ),
    "project_planning": (
        "[回应约束]\n"
        "先收束最小可验证闭环，不要自动扩成大工程或多阶段路线图。"
        "优先给出下一步、验收标准和需要用户确认的点。"
    ),
}


def format_mode_constraints_for_prompt(orchestration: OrchestrationResult) -> str:
    """Return sub-intent specific response constraints for the system prompt."""
    return _MODE_CONSTRAINTS.get(orchestration.sub_intent, "")


def orchestration_status_labels(orchestration: OrchestrationResult) -> list[str]:
    """Human-readable labels for Desktop/terminal status chips."""
    labels: list[str] = []
    sub_label = _SUB_INTENT_LABELS.get(orchestration.sub_intent)
    if sub_label:
        labels.append(sub_label)
    mode_label = _MODE_LABELS.get(orchestration.mode)
    if mode_label:
        labels.append(mode_label)
    if orchestration.needs_memory:
        labels.append("检索记忆")
    if orchestration.needs_job:
        labels.append("生成计划")
    if orchestration.side_effect_level == "approval_required":
        labels.append("等待确认")
    if orchestration.soul_insight.get("due_hypotheses"):
        labels.append("验证假设")
    return labels


def task_route_snapshot(orchestration: OrchestrationResult) -> dict:
    """Return the Python-authoritative execution route for Desktop projection."""
    title = _SUB_INTENT_LABELS.get(orchestration.sub_intent, "对话")
    if "hugo_blog" in orchestration.matched_skills:
        mode = "foreground"
        reason = "hugo workflow stays in foreground"
    elif orchestration.side_effect_level == "approval_required":
        mode = "foreground"
        reason = "approval-required task stays in foreground"
    elif orchestration.needs_job:
        mode = "background"
        reason = "python orchestrator requires background job"
    else:
        mode = "foreground"
        reason = "interactive turn stays in foreground"
    return {
        "mode": mode,
        "reason": reason,
        "title": title,
        "timeoutSeconds": 300,
    }


def orchestration_to_event_dict(orchestration: OrchestrationResult) -> dict:
    """Serialize orchestration snapshot for Desktop runtime events."""
    from uuid import uuid4

    due_hypotheses = orchestration.soul_insight.get("due_hypotheses", [])
    return {
        "id": f"orch-{uuid4().hex[:8]}",
        "intent": orchestration.intent,
        "subIntent": orchestration.sub_intent,
        "mode": orchestration.mode,
        "depth": orchestration.depth,
        "labels": orchestration_status_labels(orchestration),
        "needsMemory": orchestration.needs_memory,
        "needsJob": orchestration.needs_job,
        "taskRoute": task_route_snapshot(orchestration),
        "matchedSkills": list(orchestration.matched_skills),
        "soulInsight": {
            "dueHypotheses": list(due_hypotheses),
        },
    }


_CANDIDATE_TYPE_LABELS: dict[str, str] = {
    "project_update": "项目进展",
    "writing_preference": "写作偏好",
    "emotional_pattern": "情绪模式",
    "life_theme": "人生主题",
    "reflection_anchor": "阶段复盘",
    "task_result": "任务结果",
}


def format_memory_candidate_reason(
    policy: MemoryCandidatePolicy,
    user_input: str,
) -> str:
    """Human-readable hint for MemoryPage: why this pending item was suggested."""
    if not policy.candidate_types:
        return ""
    labels = [_CANDIDATE_TYPE_LABELS.get(item, item) for item in policy.candidate_types]
    snippet = " ".join((user_input or "").split())[:48]
    if snippet:
        return f"{' / '.join(labels)} · 来自：{snippet}"
    return " / ".join(labels)


def build_memory_candidate_policy(
    orchestration: OrchestrationResult,
) -> MemoryCandidatePolicy:
    """Decide whether this turn is worth memory-candidate extraction."""
    mapping = {
        "project_planning": ["project_update"],
        "writing_assistance": ["writing_preference"],
        "emotional_reflection": ["emotional_pattern"],
        "life_decision": ["life_theme"],
        "memory_review": ["life_theme", "reflection_anchor"],
    }
    candidate_types = list(mapping.get(orchestration.sub_intent, []))
    if orchestration.needs_job:
        candidate_types.append("task_result")
    candidate_types = _unique(candidate_types)
    sensitive = orchestration.sub_intent == "emotional_reflection"
    return MemoryCandidatePolicy(
        should_extract=bool(candidate_types),
        candidate_types=candidate_types,
        requires_review=True,
        sensitive=sensitive,
    )


def maybe_run_memory_compaction_after_turn(cfg: dict | None = None) -> dict | None:
    """Run memory compaction if thresholds are met. Returns result dict or None."""
    from core.hooks import HookContext, run_hooks
    from memory.compaction import maybe_compact_memories

    if cfg is None:
        try:
            from core.llm import load_config

            cfg = load_config()
        except Exception:
            cfg = {}

    pre = run_hooks(
        "PreCompact",
        HookContext(event="PreCompact", metadata={"kind": "memory"}),
        cfg=cfg,
    )
    if not pre.continue_:
        return None

    result = maybe_compact_memories()
    if result is None:
        return None

    payload = {
        "triggered": result.triggered,
        "reason": result.reason,
        "archivedCount": result.archived_count,
        "archivedIds": result.archived_ids,
        "summaryId": result.summary_id,
    }
    run_hooks(
        "PostCompact",
        HookContext(event="PostCompact", metadata={"kind": "memory", "result": payload}),
        cfg=cfg,
    )
    return payload
