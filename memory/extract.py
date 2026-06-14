import json
from core.llm import stream_chat

_PROMPT = """\
你是严格的长期记忆提炼助手。分析最近几轮对话，只提炼真正新的、重要的内容。

只记录：
- 用户明确说出的新偏好、新决策、新项目信息（而非已记录过的信息换一种说法）
- 用户明确说「记住」「以后按这个来」的内容
- 真正首次出现的、对理解用户有长远价值的信息

不记录：
- 闲聊、临时调试、一次性任务细节
- 已有记忆的同义反复（即使措辞不同）
- 文章内容的摘要或读后感（文章本身已存在，不需要记忆来存摘要）
- UI 细节、代码改动过程、排查中的临时猜测
- 仅靠推理而非用户明确表达的内容

type 从以下分类中选一个:
- fact:稳定事实(用户身份、家庭、长期环境等)
- preference:偏好(做事方式、沟通风格、喜好)
- emotion_pattern:反复出现的情绪模式
- value:价值判断、长期原则
- value_conflict:价值冲突、内在拉扯
- life_theme:人生主题、长期母题
- self_narrative:自我叙事方式
- project_mythology:项目神话、项目在用户生命叙事中的意义
- relationship_pattern:关系模式
- creative_identity:创作身份、自我表达身份
- growth_marker:成长标记、阶段性变化
- reflection_anchor:有分量、值得下次复盘优先提取的一句话

兼容旧类型:identity / project / decision / todo / insight / risk / context / reflection 仍可使用,但新提炼优先使用上面的 A4 类型。

depth 字段必须给出:1=事实,2=偏好/习惯,3=模式,4=价值/叙事,5=精神母题。

block_type 从以下枚举选一个: human / persona / preference / decision / event / insight
label 可选，80 字内标签，如 writing_style、core_values；拿不准留空。

如果提炼内容涉及以下情况,在 obsidian_hint 字段给出写回建议:
- 用户价值观/防御模式/核心特征变化 → "SOUL.md"
- 新项目/人生方向/当前目标变化 → "MEMORY.md"
- 否则留空字符串

以 JSON 格式返回:
{
  "memories": [
    {"content": "一句话中文记忆", "tags": "标签1,标签2", "type": "value", "importance": 3, "depth": 4, "block_type": "human", "label": "core_values", "obsidian_hint": ""}
  ]
}

importance: 1=低 3=中等 5=核心。value / life_theme / project_mythology / reflection_anchor 类型至少给 4 分。
depth: 1=事实,5=精神母题。拿不准时用 3。
每次最多返回 3 条。拿不准就不要写入。
没有值得记住的内容返回 {"memories": []}。\
"""

_CANDIDATE_FOCUS: dict[str, str] = {
    "project_update": (
        "项目进展、下一步决策、路线图或优先级变化"
        "；允许把已完成里程碑和明确下一步整理成项目记忆草稿，待用户确认后再保存"
        "（type 优先 project / decision / insight / project_mythology）"
    ),
    "writing_preference": (
        "写作与改稿偏好、语气、结构习惯"
        "（type 优先 preference / creative_identity）"
    ),
    "emotional_pattern": (
        "反复出现的情绪模式或内在拉扯，仅限用户明确表达"
        "（type 优先 emotion_pattern / value / self_narrative）"
    ),
    "life_theme": (
        "人生主题、长期方向、价值原则变化"
        "（type 优先 life_theme / value / reflection_anchor）"
    ),
    "reflection_anchor": (
        "值得下次复盘的一句话或阶段标记"
        "（type 优先 reflection_anchor / growth_marker）"
    ),
    "task_result": (
        "本轮任务的关键结论或待跟进事项"
        "（type 优先 decision / todo / insight，importance 至少 3）"
    ),
}


def build_extract_focus_block(
    candidate_types: list[str] | None,
    *,
    sensitive: bool = False,
) -> str:
    """Narrow the extract prompt when orchestrator already picked candidate types."""
    if not candidate_types:
        return ""
    lines = [
        "【本轮提炼范围】只提炼以下类别；无关内容必须返回 {\"memories\": []}：",
    ]
    for item in candidate_types:
        hint = _CANDIDATE_FOCUS.get(item)
        if hint:
            lines.append(f"- {item}：{hint}")
    if sensitive:
        lines.append(
            "- 敏感内容：不要诊断或夸大；仅记录用户原话支持的长期模式。"
        )
    return "\n".join(lines)

_VALID_TYPES = {
    "identity", "preference", "project", "decision",
    "todo", "insight", "risk", "context", "reflection",
    "fact", "emotion_pattern", "value", "value_conflict",
    "life_theme", "self_narrative", "project_mythology",
    "relationship_pattern", "creative_identity", "growth_marker",
    "reflection_anchor",
}

def _clean_memory(m: dict) -> dict | None:
    content = str(m.get("content", "")).strip()
    if len(content) < 8:
        return None

    mtype = str(m.get("type", "insight")).strip()
    if mtype not in _VALID_TYPES:
        mtype = "insight"

    try:
        importance = int(m.get("importance", 3))
    except Exception:
        importance = 3
    importance = max(1, min(5, importance))

    # 临时上下文低价值时不写库,避免把一次性任务污染长期记忆。
    if mtype == "context" and importance < 4:
        return None

    if mtype in {"identity", "decision"}:
        importance = max(4, importance)

    try:
        from memory.a4 import normalize_memory_candidate
        normalized = normalize_memory_candidate({
            "content": content,
            "tags": str(m.get("tags", "")).strip(),
            "type": mtype,
            "importance": importance,
            "depth": m.get("depth", 3),
        })
        depth = normalized["depth"]
    except Exception:
        depth = 3

    if mtype in {"value", "life_theme", "project_mythology", "reflection_anchor"}:
        importance = max(4, importance)

    from memory.store import infer_block_type, normalize_label
    resolved_block = infer_block_type(mtype, str(m.get("block_type", "")).strip() or None)
    resolved_label = normalize_label(m.get("label"))

    return {
        "content": content,
        "tags": str(m.get("tags", "")).strip(),
        "type": mtype,
        "importance": importance,
        "depth": depth,
        "confidence": 0.7,
        "block_type": resolved_block,
        "label": resolved_label,
        "obsidian_hint": str(m.get("obsidian_hint", "")).strip(),
    }

def extract(
    history: list[dict],
    *,
    candidate_types: list[str] | None = None,
    sensitive: bool = False,
) -> tuple[list[dict], list[dict]]:
    """
    返回 (memories, obsidian_suggestions)
    obsidian_suggestions: [{"file": "SOUL.md|MEMORY.md", "content": "..."}]
    """
    if not history:
        return [], []

    # 只取最近 6 轮对话(12 条消息),避免对全量历史反复提取
    recent = history[-12:] if len(history) > 12 else list(history)

    turns = "\n".join(
        f"{'用户' if m['role'] == 'user' else 'Archer'}: {m['content']}"
        for m in recent if m["role"] in ("user", "assistant")
    )

    focus = build_extract_focus_block(candidate_types, sensitive=sensitive)
    system_prompt = _PROMPT if not focus else f"{_PROMPT}\n\n{focus}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"对话内容:\n\n{turns}"},
    ]

    raw = ""
    for chunk in stream_chat(messages, track_usage=False):
        raw += chunk

    try:
        from memory.store import _topic_keywords
        s = raw.find("{")
        e = raw.rfind("}") + 1
        if s >= 0 and e > s:
            data = json.loads(raw[s:e])
            raw_memories = data.get("memories", [])
            memories = []
            seen_text = set()
            seen_keywords: list[set[str]] = []  # 批内已收集的关键词集
            for item in raw_memories:
                if not isinstance(item, dict):
                    continue
                cleaned = _clean_memory(item)
                if not cleaned:
                    continue
                content = cleaned["content"]
                # 精确重复
                if content in seen_text:
                    continue
                # 批内关键词去重:与已保留的记忆关键词重叠 ≥4 则跳过
                kw = _topic_keywords(content)
                if any(len(kw & existing) >= 4 for existing in seen_keywords):
                    continue
                seen_text.add(content)
                seen_keywords.append(kw)
                memories.append(cleaned)
                if len(memories) >= 3:
                    break
            obsidian = [
                {"file": m["obsidian_hint"], "content": m["content"]}
                for m in memories if m.get("obsidian_hint")
            ]
            return memories, obsidian
    except Exception:
        pass

    return [], []
