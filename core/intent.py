"""
intent.py — Archer 轻量意图分类

A2 目标：
- 关键词规则预筛选
- 不硬拦截，最终判断仍交给 LLM
- 为记忆检索、SOUL 注入、边界回应提供轻量信号
"""
from __future__ import annotations

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


def classify_query_intent(user_input: str) -> dict:
    """
    分析用户输入，返回查询意图分类结果。

    返回格式：
    {
        "intent": "chat | task | decision | project | reflection | emotional",
        "needs_memory": bool,
        "needs_project": bool,
        "needs_soul": bool,
        "needs_tools": bool,
    }
    """
    text = user_input.strip()
    text_len = len(text)

    has_decision   = any(kw in text for kw in _DECISION_KW)
    has_project    = any(kw in text for kw in _PROJECT_KW)
    has_reflection = any(kw in text for kw in _REFLECTION_KW)
    has_emotional  = any(kw in text for kw in _EMOTIONAL_KW)
    has_task       = any(kw in text for kw in _TASK_KW)
    has_recall     = any(kw in text for kw in _MEMORY_RECALL_KW)

    if has_emotional:
        intent = "emotional"
    elif has_decision:
        intent = "decision"
    elif has_reflection:
        intent = "reflection"
    elif has_project:
        intent = "project"
    elif has_task or text_len >= 40:
        intent = "task"
    else:
        intent = "chat"

    needs_soul    = intent in ("decision", "emotional", "reflection")
    needs_memory  = intent in ("decision", "reflection", "project", "task") or text_len >= 40 or has_recall
    needs_project = intent in ("project", "task")
    needs_tools   = intent in ("task", "project")

    # 记忆召回查询：强制提升检索量级
    if has_recall:
        needs_memory = True

    return {
        "intent": intent,
        "needs_memory": needs_memory,
        "needs_project": needs_project,
        "needs_soul": needs_soul,
        "needs_tools": needs_tools,
    }


def is_heavy_query(user_input: str) -> bool:
    """向后兼容接口：返回是否需要注入完整工作上下文。"""
    result = classify_query_intent(user_input)
    return result["needs_memory"]
