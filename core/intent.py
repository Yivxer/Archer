"""
intent.py — Archer 轻量意图分类

A2 目标：
- 关键词规则预筛选 + 置信度打分
- 低置信时可选一次极小 LLM 路由（llm_fallback=True）
- 为记忆检索、SOUL 注入、边界回应提供轻量信号
"""
from __future__ import annotations

import json
import re

_DECISION_KW  = frozenset([
    "该不该", "是否", "选择", "决策", "利弊", "怎么办", "要不要", "该", "应该",
    "值得吗", "建议", "方向", "怎么做", "怎么选", "会不会", "打算", "决定",
])
_PROJECT_KW   = frozenset([
    "项目", "进度", "计划", "下一步", "路线图", "实现", "功能", "版本", "发布",
    "规划", "目标",
])
_REFLECTION_KW = frozenset([
    "复盘", "反思", "我发现", "回顾", "分析", "如何", "为什么",
])
_EMOTIONAL_KW = frozenset([
    "难受", "焦虑", "迷茫", "害怕", "孤独", "烦", "累", "压力", "沮丧", "失落", "担心",
])
_TASK_KW      = frozenset([
    "帮我", "写", "生成", "修改", "创建", "执行", "搜索", "翻译",
    "可以吗", "能不能", "需要",
])

_CODE_BOUNDARY_KW = frozenset([
    "写代码", "改代码", "修 bug", "修bug", "实现功能", "开发", "重构", "跑测试",
    "pull request", "pr", "commit", "提交代码", "前端", "后端", "接口", "api",
])
_IMAGE_BOUNDARY_KW = frozenset(["画图", "生成图片", "做图", "海报", "logo", "图片", "配图"])
_VIDEO_BOUNDARY_KW = frozenset(["生成视频", "剪视频", "做视频", "视频", "动画", "短视频"])
_SEARCH_BOUNDARY_KW = frozenset(["全网搜索", "大量搜索", "深度调研", "查资料", "联网搜索"])

_MEMORY_RECALL_KW = frozenset([
    "记得", "回忆", "之前", "说过", "告诉", "上次", "聊过", "提到",
    "以前", "过去", "曾经", "刚才", "前面", "记不记得", "想不起来",
    "帮我回忆", "提醒我", "忘了", "忘记", "还记得",
])

# 强/中/弱关键词分层：弱词单独出现在短句里置信度低，避免「该」「为什么」误触发
_EMOTIONAL_STRONG = _EMOTIONAL_KW
_DECISION_STRONG = frozenset([
    "该不该", "是否", "选择", "决策", "利弊", "怎么办", "要不要",
    "值得吗", "怎么选", "决定",
])
_DECISION_MEDIUM = frozenset(["应该", "建议", "方向", "怎么做", "会不会", "打算"])
_DECISION_WEAK = frozenset(["该"])
_REFLECTION_STRONG = frozenset(["复盘", "反思", "我发现", "回顾"])
_REFLECTION_MEDIUM = frozenset(["分析"])
_REFLECTION_WEAK = frozenset(["为什么", "如何"])
_PROJECT_STRONG = _PROJECT_KW
_TASK_STRONG = frozenset(["帮我", "生成", "修改", "创建", "执行", "搜索", "翻译", "可以吗", "能不能"])
_TASK_MEDIUM = frozenset(["写", "需要"])

_INTENT_PRIORITY = ("emotional", "decision", "reflection", "project", "task")
_CONFIDENCE_LLM_THRESHOLD = 0.65


def classify_boundary_request(user_input: str) -> str | None:
    """识别明显不适合 Archer 直接承担的执行型任务类型。"""
    text = user_input.strip().lower()
    if any(kw in text for kw in _CODE_BOUNDARY_KW):
        return "code"
    if any(kw in text for kw in _IMAGE_BOUNDARY_KW):
        return "image"
    if any(kw in text for kw in _VIDEO_BOUNDARY_KW):
        return "video"
    if any(kw in text for kw in _SEARCH_BOUNDARY_KW):
        return "search"
    return None


# 跟随式 / 回指信号：用于判断当前输入是否依赖上文（继承意图、改写检索词）
_CONTINUATION_KW = frozenset([
    "继续", "然后呢", "然后", "嗯嗯", "还有呢", "接着说", "再说说", "说下去",
    "go on", "那这个呢", "这个呢", "那呢",
])
_BACKREF_KW = frozenset([
    "那个", "这个", "那件", "这件", "那种", "这种", "上面", "刚才", "前面",
    "刚说", "你说的", "它", "他", "她", "这事", "那事", "这点", "那点",
])
_GREETINGS = frozenset([
    "在吗", "在么", "在不在", "你好", "您好", "hi", "hello", "早", "早安",
    "晚安", "嗨", "哈喽",
])
_ELLIPSIS_MARKERS = ("...", "……", "…")


def _score_category(
    text: str,
    strong: frozenset[str],
    medium: frozenset[str] = frozenset(),
    weak: frozenset[str] = frozenset(),
) -> tuple[float, list[str]]:
    """对单类意图打分，返回 (score, signals)。"""
    t = text.strip()
    score = 0.0
    signals: list[str] = []
    for kw in strong:
        if kw in t:
            signals.append(f"strong:{kw}")
            score = max(score, 0.84)
    for kw in medium:
        if kw in t:
            signals.append(f"medium:{kw}")
            score = max(score, 0.70)
    for kw in weak:
        if kw in t:
            signals.append(f"weak:{kw}")
            if len(t) > 18 or score >= 0.68:
                score = max(score, 0.58)
            elif len(t) <= 10:
                score = max(score, 0.34)
            else:
                score = max(score, 0.48)
    return score, signals


def _pick_intent_from_scores(text: str, scores: dict[str, float]) -> tuple[str, float]:
    best_intent = "chat"
    best_score = 0.0
    for cat in _INTENT_PRIORITY:
        if scores.get(cat, 0.0) > best_score:
            best_score = scores[cat]
            best_intent = cat

    if best_score < 0.30:
        if len(text.strip()) >= 40:
            return "task", 0.72
        return "chat", 0.88

    ranked = sorted((scores.get(c, 0.0) for c in _INTENT_PRIORITY), reverse=True)
    if len(ranked) >= 2 and ranked[0] - ranked[1] < 0.12:
        best_score *= 0.75
    return best_intent, min(best_score, 0.95)


def _needs_from_intent(intent: str, text: str, has_recall: bool) -> dict:
    text_len = len(text.strip())
    needs_soul = intent in ("decision", "emotional", "reflection")
    needs_memory = intent in ("decision", "reflection", "project", "task") or text_len >= 40 or has_recall
    needs_project = intent in ("project", "task")
    needs_tools = intent in ("task", "project")
    if has_recall:
        needs_memory = True
    return {
        "needs_memory": needs_memory,
        "needs_project": needs_project,
        "needs_soul": needs_soul,
        "needs_tools": needs_tools,
    }


def _classify_single(user_input: str) -> dict:
    """对单句做意图分类（不看历史），带置信度。"""
    text = user_input.strip()
    has_recall = any(kw in text for kw in _MEMORY_RECALL_KW)

    scores = {
        "emotional": _score_category(text, _EMOTIONAL_STRONG)[0],
        "decision": _score_category(text, _DECISION_STRONG, _DECISION_MEDIUM, _DECISION_WEAK)[0],
        "reflection": _score_category(text, _REFLECTION_STRONG, _REFLECTION_MEDIUM, _REFLECTION_WEAK)[0],
        "project": _score_category(text, _PROJECT_STRONG)[0],
        "task": _score_category(text, _TASK_STRONG, _TASK_MEDIUM)[0],
    }
    intent, confidence = _pick_intent_from_scores(text, scores)
    flags = _needs_from_intent(intent, text, has_recall)
    return {
        "intent": intent,
        "confidence": round(confidence, 2),
        **flags,
    }


def _parse_intent_json(text: str) -> dict | None:
    try:
        return json.loads(text.strip())
    except Exception:
        pass
    m = re.search(r"\{[^{}]+\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except Exception:
        return None


def _llm_classify_intent(user_input: str, history: list[dict] | None) -> dict | None:
    """低置信时的一次极小 LLM 意图路由。失败返回 None，不阻塞主流程。"""
    try:
        from core.llm import stream_chat

        recent = list(reversed(_recent_user_texts(history)[:2]))
        ctx = "\n".join(f"- {t}" for t in recent) if recent else "（无）"
        prompt = (
            "你是意图路由器。根据用户最新消息（可参考上文）输出 JSON，不要解释。\n"
            '格式：{"intent":"chat|task|decision|project|reflection|emotional","confidence":0.0-1.0}\n'
            f"上文用户消息：\n{ctx}\n"
            f"最新消息：{user_input.strip()}\n"
            "JSON："
        )
        full = "".join(stream_chat([{"role": "user", "content": prompt}], track_usage=False))
        parsed = _parse_intent_json(full)
        if not parsed:
            return None
        intent = str(parsed.get("intent", "chat")).strip()
        if intent not in _INTENT_PRIORITY + ("chat",):
            return None
        confidence = float(parsed.get("confidence", 0.75))
        confidence = max(0.0, min(1.0, confidence))
        text = user_input.strip()
        has_recall = any(kw in text for kw in _MEMORY_RECALL_KW)
        return {
            "intent": intent,
            "confidence": round(confidence, 2),
            "source": "llm",
            **_needs_from_intent(intent, text, has_recall),
        }
    except Exception:
        return None


def _text_of(content) -> str:
    """从历史消息 content（可能是 str 或多模态 list）中提取纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(item)
        return " ".join(parts)
    return ""


def _recent_user_texts(history: list[dict] | None) -> list[str]:
    """返回历史中的用户消息文本，最新在前。"""
    if not history:
        return []
    out: list[str] = []
    for msg in reversed(history):
        if isinstance(msg, dict) and msg.get("role") == "user":
            t = _text_of(msg.get("content", "")).strip()
            if t:
                out.append(t)
    return out


def _is_substantive_user_turn(text: str) -> bool:
    """该条用户消息是否足以作为意图/线程锚点（非短追问）。"""
    t = (text or "").strip()
    if not t:
        return False
    base = _classify_single(t)
    if base["intent"] == "chat":
        return len(t) >= 12 and base.get("confidence", 0) >= 0.72
    return base.get("confidence", 0) >= 0.55 or len(t) >= 10


def _is_followup(text: str, base: dict, history: list[dict] | None = None) -> bool:
    """当前输入是否是依赖上文的低信号跟随/回指（需要继承意图、改写检索）。"""
    t = text.strip()
    if not t:
        return False
    lowered = t.lower()
    if lowered in _GREETINGS:
        return False
    # 弱关键词导致的假阳性：短句 + 低置信 + 有历史 → 当下跟随
    if base["intent"] != "chat":
        if history and base.get("confidence", 1.0) < _CONFIDENCE_LLM_THRESHOLD:
            return True
        return False
    if any(kw in lowered for kw in _CONTINUATION_KW):
        return True
    if any(kw in t for kw in _BACKREF_KW):
        return True
    if len(t) <= 10 and t.rstrip().endswith(("吗", "呢", "?", "？")):
        return True
    return False


def classify_query_intent(
    user_input: str,
    history: list[dict] | None = None,
    *,
    llm_fallback: bool = False,
) -> dict:
    """
    分析用户输入，返回查询意图分类结果。

    返回格式：
    {
        "intent": "chat | task | decision | project | reflection | emotional",
        "confidence": float,          # 0.0~1.0
        "source": "rules|inherit|llm",
        "needs_memory": bool,
        "needs_project": bool,
        "needs_soul": bool,
        "needs_tools": bool,
    }

    history-aware：低信号跟随/回指继承上文意图。
    llm_fallback=True 且规则置信 < 0.65 时，尝试一次极小 LLM 路由。
    """
    base = _classify_single(user_input)
    if history and _is_followup(user_input, base, history):
        for prev in _recent_user_texts(history):
            if not _is_substantive_user_turn(prev):
                continue
            inherited = _classify_single(prev)
            if inherited["intent"] != "chat":
                    return {
                        "intent": inherited["intent"],
                        "confidence": max(inherited.get("confidence", 0.8), 0.75),
                        "source": "inherit",
                        "needs_memory": True,
                        "needs_project": inherited["needs_project"] or base["needs_project"],
                        "needs_soul": inherited["needs_soul"],
                        "needs_tools": inherited["needs_tools"] or base["needs_tools"],
                    }
    if llm_fallback and base.get("confidence", 1.0) < _CONFIDENCE_LLM_THRESHOLD:
        llm_result = _llm_classify_intent(user_input, history)
        if llm_result:
            return llm_result
    return {**base, "source": "rules"}


def _anchor_user_text(history: list[dict]) -> str | None:
    """最近一条实质用户消息（非跟随/回指），用作检索与线程锚点。"""
    for prev in _recent_user_texts(history):
        if _is_substantive_user_turn(prev):
            return prev
    return None


def _needs_retrieval_context(text: str, base: dict, history: list[dict] | None) -> bool:
    """当前输入是否需要拼接上文再做检索（比 _is_followup 覆盖更多省略场景）。"""
    if not history:
        return False
    t = text.strip()
    if not t:
        return False
    if _is_followup(t, base, history):
        return True
    if any(kw in t for kw in _BACKREF_KW) and len(t) <= 40:
        return True
    if any(kw in t for kw in _MEMORY_RECALL_KW) and len(t) <= 25:
        return True
    if any(mark in t for mark in _ELLIPSIS_MARKERS) and len(t) <= 30:
        return True
    lowered = t.lower()
    if len(t) <= 6 and lowered not in _GREETINGS and base["intent"] == "chat":
        return True
    return False


def augment_retrieval_query(user_input: str, history: list[dict] | None = None) -> str:
    """为依赖上文的输入改写检索词：拼接最近一条实质用户消息，提升命中率。

    覆盖：低信号跟随/回指、短回指句、回忆类短问、省略号、极短续聊。
    非依赖上文的输入原样返回，长度上限 200 字。
    """
    text = (user_input or "").strip()
    if not history:
        return text
    base = _classify_single(text)
    if not _needs_retrieval_context(text, base, history):
        return text
    anchor = _anchor_user_text(history)
    if anchor:
        return f"{anchor} {text}".strip()[:200]
    recent = _recent_user_texts(history)
    if recent:
        return f"{recent[0]} {text}".strip()[:200]
    return text


def should_clarify(user_input: str, history: list[dict] | None = None) -> str | None:
    """关键词反问直出已关闭：歧义输入也交给 LLM 自然追问。"""
    return None


def is_heavy_query(user_input: str) -> bool:
    """向后兼容接口：返回是否需要注入完整工作上下文。"""
    result = classify_query_intent(user_input)
    return result["needs_memory"]
