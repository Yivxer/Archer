"""
soul_profile.py — Soul Profile 结构化档案骨架

A5 目标：
- 不替代 SOUL.md，不自动改写长期档案
- 提供一层更紧凑、可控的结构化摘要
- 注入时优先当前人生阶段，再按意图选择少量长期特质
- 单次最多 7 条，避免把完整档案每轮塞进 prompt
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from core.rhythm import HOURS_PER_DAY, HOURS_PER_WEEK, RhythmProfile


_PROFILE_FIELDS = (
    "core_values",
    "recurring_fears",
    "creative_identity",
    "life_themes",
    "emotional_patterns",
    "relationship_patterns",
    "aesthetic_preferences",
    "project_mythology",
    "language_style",
    "important_questions",
    "current_life_stage",
    "rhythm",
    "narrative",
    "tensions",
    "patterns",
)

_FIELD_LABELS = {
    "core_values": "核心价值",
    "recurring_fears": "反复恐惧",
    "creative_identity": "创作身份",
    "life_themes": "人生主题",
    "emotional_patterns": "情绪模式",
    "relationship_patterns": "关系模式",
    "aesthetic_preferences": "审美偏好",
    "project_mythology": "项目神话",
    "language_style": "语言风格",
    "important_questions": "重要问题",
    "current_life_stage": "当前阶段",
    "rhythm": "时间节律",
    "narrative": "自我叙事",
    "tensions": "张力",
    "patterns": "行为模式",
}

_INTENT_PRIORITY = {
    "emotional": (
        "emotional_patterns",
        "recurring_fears",
        "current_life_stage",
        "life_themes",
        "relationship_patterns",
        "core_values",
        "important_questions",
        "rhythm",
        "narrative",
        "tensions",
        "patterns",
    ),
    "decision": (
        "core_values",
        "current_life_stage",
        "tensions",
        "recurring_fears",
        "life_themes",
        "important_questions",
        "creative_identity",
        "project_mythology",
    ),
    "reflection": (
        "life_themes",
        "narrative",
        "tensions",
        "patterns",
        "rhythm",
        "emotional_patterns",
        "relationship_patterns",
        "core_values",
        "important_questions",
        "creative_identity",
        "project_mythology",
    ),
    "project": (
        "project_mythology",
        "creative_identity",
        "patterns",
        "narrative",
        "core_values",
        "current_life_stage",
        "life_themes",
        "language_style",
        "important_questions",
    ),
    "task": (
        "project_mythology",
        "patterns",
        "language_style",
        "aesthetic_preferences",
        "core_values",
        "current_life_stage",
    ),
    "chat": (
        "current_life_stage",
        "rhythm",
        "language_style",
    ),
}


@dataclass
class SoulProfile:
    """枫弋的结构化灵魂档案摘要。"""

    core_values: list[str] = field(default_factory=list)
    recurring_fears: list[str] = field(default_factory=list)
    creative_identity: list[str] = field(default_factory=list)
    life_themes: list[str] = field(default_factory=list)
    emotional_patterns: list[str] = field(default_factory=list)
    relationship_patterns: list[str] = field(default_factory=list)
    aesthetic_preferences: list[str] = field(default_factory=list)
    project_mythology: list[str] = field(default_factory=list)
    language_style: list[str] = field(default_factory=list)
    important_questions: list[str] = field(default_factory=list)
    current_life_stage: list[str] = field(default_factory=list)
    rhythm: list[str] = field(default_factory=list)
    narrative: list[str] = field(default_factory=list)
    tensions: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SoulProfile":
        """从 dict 构建 SoulProfile，忽略未知字段，标量自动转为单项列表。"""
        data = data or {}
        kwargs: dict[str, list[str]] = {}
        for field_name in _PROFILE_FIELDS:
            value = data.get(field_name, [])
            if isinstance(value, str):
                items = [value]
            elif isinstance(value, list):
                items = [str(item).strip() for item in value if str(item).strip()]
            else:
                items = []
            kwargs[field_name] = items
        return cls(**kwargs)

    def is_empty(self) -> bool:
        return not any(getattr(self, field_name) for field_name in _PROFILE_FIELDS)


def backfill_rhythm(
    profile: SoulProfile,
    rhythm: RhythmProfile,
    *,
    max_peaks: int = 3,
) -> SoulProfile:
    """Return a profile with a derived rhythm summary when enough history exists."""
    if rhythm.status != "modeled" or len(rhythm.hourly_weights) != HOURS_PER_WEEK:
        return profile
    manual_items = [item for item in profile.rhythm if not item.startswith("[模型]")]
    peaks = _format_rhythm_peaks(rhythm.hourly_weights, max_peaks=max_peaks)
    summary = f"[模型] 置信度 {rhythm.confidence:.2f}；活动高峰：{peaks}"
    return replace(profile, rhythm=[*manual_items, summary])


def backfill_narrative(
    profile: SoulProfile,
    memories: list[dict[str, Any]],
    *,
    limit: int = 3,
) -> SoulProfile:
    """Return a profile enriched from explicit, high-importance narrative memories."""
    allowed_types = {"life_theme", "self_narrative", "project_mythology", "reflection_anchor"}
    manual_items = [item for item in profile.narrative if not item.startswith("[模型]")]
    model_items: list[str] = []
    seen: set[str] = set()
    for memory in memories:
        if not isinstance(memory, dict) or str(memory.get("type") or "") not in allowed_types:
            continue
        if _memory_importance(memory) < 4:
            continue
        content = str(memory.get("content") or "").strip()
        if content and content not in seen:
            seen.add(content)
            model_items.append(f"[模型] {content}")
        if len(model_items) >= max(1, int(limit)):
            break
    return replace(profile, narrative=[*manual_items, *model_items])


def backfill_tensions(
    profile: SoulProfile,
    memories: list[dict[str, Any]],
    *,
    limit: int = 3,
) -> SoulProfile:
    """Return explicit, high-confidence tension statements from deep memories."""
    allowed_types = {"life_theme", "self_narrative", "emotion_pattern", "relationship_pattern", "value", "reflection_anchor"}
    manual_items = [item for item in profile.tensions if not item.startswith("[模型]")]
    model_items: list[str] = []
    seen: set[str] = set()
    for memory in memories:
        if not isinstance(memory, dict) or str(memory.get("type") or "") not in allowed_types:
            continue
        if _memory_importance(memory) < 4:
            continue
        content = str(memory.get("content") or "").strip()
        if content and _has_explicit_tension(content) and content not in seen:
            seen.add(content)
            model_items.append(f"[模型] {content}")
        if len(model_items) >= max(1, int(limit)):
            break
    return replace(profile, tensions=[*manual_items, *model_items])


def backfill_patterns(
    profile: SoulProfile,
    themes: list[dict[str, Any]],
    *,
    limit: int = 3,
) -> SoulProfile:
    """Return behavior-oriented Soul Profile items from evidence-gated themes."""
    allowed_categories = {"behavior", "struggle", "growth"}
    manual_items = [item for item in profile.patterns if not item.startswith("[模型]")]
    model_items: list[str] = []
    seen: set[str] = set()
    for theme in themes:
        if not isinstance(theme, dict) or str(theme.get("category") or "") not in allowed_categories:
            continue
        item = str(theme.get("description") or theme.get("name") or "").strip()
        if item and item not in seen:
            seen.add(item)
            model_items.append(f"[模型] {item}")
        if len(model_items) >= max(1, int(limit)):
            break
    return replace(profile, patterns=[*manual_items, *model_items])


def _format_rhythm_peaks(weights: list[float], *, max_peaks: int) -> str:
    day_names = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
    count = max(1, min(int(max_peaks), HOURS_PER_WEEK))
    slots = sorted(range(HOURS_PER_WEEK), key=lambda slot: (-weights[slot], slot))[:count]
    return "、".join(f"{day_names[slot // HOURS_PER_DAY]} {slot % HOURS_PER_DAY:02d}:00" for slot in slots)


def _memory_importance(memory: dict[str, Any]) -> int:
    try:
        return int(memory.get("importance", 3))
    except (TypeError, ValueError):
        return 3


def _has_explicit_tension(content: str) -> bool:
    return any(marker in content for marker in ("但", "却", "一方面", "另一方面"))


def load_soul_profile(path_str: str | None) -> SoulProfile:
    """读取 JSON Soul Profile；文件不存在或解析失败时返回空档案。"""
    if not path_str:
        return SoulProfile()
    path = Path(path_str).expanduser()
    if not path.is_file():
        return SoulProfile()
    try:
        return SoulProfile.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return SoulProfile()


def _append_items(lines: list[str], profile: SoulProfile, field_name: str, per_field: int = 2) -> None:
    label = _FIELD_LABELS[field_name]
    for item in getattr(profile, field_name)[:per_field]:
        line = f"{label}：{item}"
        if line not in lines:
            lines.append(line)


def select_soul_profile_items(
    profile: SoulProfile,
    intent: str | None = None,
    user_input: str = "",
    limit: int = 7,
) -> list[str]:
    """
    选择本轮应注入的 Soul Profile 条目。

    策略：
    1. current_life_stage 永远优先，但最多 1 条；
    2. 按 intent 选择相关长期特质，每类最多 2 条；
    3. 如果用户文本命中字段标签关键词，则补充该字段；
    4. 总量不超过 limit，默认 7 条。
    """
    if profile.is_empty() or limit <= 0:
        return []

    selected: list[str] = []
    _append_items(selected, profile, "current_life_stage", per_field=1)

    priority = _INTENT_PRIORITY.get(intent or "chat", _INTENT_PRIORITY["chat"])
    for field_name in priority:
        if len(selected) >= limit:
            return selected[:limit]
        if field_name == "current_life_stage":
            continue
        _append_items(selected, profile, field_name, per_field=2)

    text = user_input.strip()
    if text:
        for field_name, label in _FIELD_LABELS.items():
            if len(selected) >= limit:
                break
            if label[:2] in text or field_name in text:
                _append_items(selected, profile, field_name, per_field=2)

    return selected[:limit]


def format_soul_profile_for_prompt(
    profile: SoulProfile,
    intent: str | None = None,
    user_input: str = "",
    limit: int = 7,
) -> str:
    """将 Soul Profile 格式化为紧凑 prompt section。"""
    items = select_soul_profile_items(profile, intent=intent, user_input=user_input, limit=limit)
    if not items:
        return ""
    return "[Soul Profile 摘要]\n" + "\n".join(f"- {item}" for item in items)


# ── 阶段更新触发 & 自我进化闭环 ──────────────────────────────────────────────

def format_full_profile(profile: SoulProfile) -> str:
    """将完整 SoulProfile 格式化为可读文本，供进化检查使用。"""
    if profile.is_empty():
        return "[Soul Profile 为空，尚未建立]"
    lines = ["## 当前 Soul Profile"]
    for field_name in _PROFILE_FIELDS:
        items = getattr(profile, field_name, [])
        if items:
            label = _FIELD_LABELS.get(field_name, field_name)
            for item in items:
                lines.append(f"- {label}：{item}")
    return "\n".join(lines)


def build_stage_check_prompt(profile: SoulProfile, recent_text: str = "") -> str:
    """
    生成阶段检测提示词。
    在周复盘或日记回顾后调用，检查 current_life_stage 是否需要更新。
    """
    current_stage = ", ".join(profile.current_life_stage) if profile.current_life_stage else "（未设置）"
    parts = [
        "[阶段检测]\n",
        f"当前记录的「当前阶段」：{current_stage}\n",
    ]
    if recent_text:
        parts.append(f"近期动态：\n{recent_text[:1500]}\n")
    parts.append(
        "请判断：基于以上信息，用户当前所处的人生阶段是否发生了明显变化？\n"
        "如果阶段已变化，请给出新的 current_life_stage 描述（1-2 条，每条一句话）。\n"
        "如果阶段未变，直接说「阶段未变」。\n"
        "判断标准：不是每天的波动，而是持续数周以上的结构性的生活方式/重心/身份变化。"
    )
    return "\n".join(parts)


def build_evolution_check_prompt(
    profile: SoulProfile,
    recent_insights: str = "",
) -> str:
    """
    生成自我进化检测提示词。
    从近期高重要度洞察中检测 SoulProfile 哪些维度需要更新。
    """
    parts = [
        "[Soul Profile 进化检测]\n",
        "你正在帮用户维护一个 15 维度的结构化 Soul Profile。\n",
    ]

    full = format_full_profile(profile)
    parts.append(f"{full}\n")

    if recent_insights:
        parts.append(f"## 近期洞察\n{recent_insights[:2000]}\n")
    else:
        parts.append("（近期无高重要度洞察）\n")

    parts.append(
        "请逐维度检查：\n"
        "1. 哪些维度应该新增条目（近期出现了新的模式/特质）\n"
        "2. 哪些维度应该删除条目（旧的描述已经不再准确）\n"
        "3. 哪些维度应该修改条目（描述需要更新但核心还在）\n"
        "4. current_life_stage 是否需要更新\n\n"
        "输出格式：\n"
        "- 无需更新：「所有维度均无需更新」\n"
        "- 需要更新：逐项列出建议，格式为「[维度名] 建议：新增/删除/修改 XXX」\n\n"
        "原则：\n"
        "- 只改真正需要改的，不要为了显得有产出而改\n"
        "- 新增要有足够证据（至少在两次对话中出现过）\n"
        "- 删除要有明确理由（不再准确，而非暂时没出现）\n"
        "- 最多建议 3 处改动"
    )

    return "\n".join(parts)
