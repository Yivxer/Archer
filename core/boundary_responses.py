"""
boundary_responses.py — Archer 边界回应模板

A2 目标：
- 边界回应与意图分类分离
- 工具名称从 archer.toml 的 external_tools 读取
- relationship_depth 分层：刚认识 / 熟悉 / 深度信任
"""
from __future__ import annotations

_OPENINGS = {
    "new": "这件事不太适合由我直接完成。",
    "familiar": "这件事不该由我直接硬上。",
    "deep": "这事别让我硬上。",
}

_OFFERS = {
    "code": {
        "new": "我可以帮你理清需求、拆架构、写任务书或检查方向；具体实现更适合交给 {tool}。",
        "familiar": "我可以帮你理清需求、拆架构、写任务书或检查方向，但具体实现更适合交给 {tool}。",
        "deep": "我负责把问题拆准、边界画清、任务书写明；代码执行交给 {tool}，别把我用成螺丝刀。",
    },
    "image": {
        "new": "我可以帮你判断风格、写提示词、做审美取舍；直接出图更适合交给 {tool}。",
        "familiar": "我可以帮你判断风格、写提示词、做审美取舍，但直接出图更适合交给 {tool}。",
        "deep": "我帮你定审美、控方向、写提示词；出图交给 {tool}，别让我假装画师。",
    },
    "video": {
        "new": "我可以帮你搭脚本、节奏、分镜和表达重点；生成或剪辑更适合交给 {tool}。",
        "familiar": "我可以帮你搭脚本、节奏、分镜和表达重点，但生成或剪辑更适合交给 {tool}。",
        "deep": "我帮你抓叙事、节奏和分镜；生成剪辑交给 {tool}，别让我装剪辑台。",
    },
    "search": {
        "new": "我可以帮你明确问题、设计检索框架和判断结论质量；大规模联网搜索更适合交给 {tool}。",
        "familiar": "我可以帮你明确问题、设计检索框架和判断结论质量，但大规模联网搜索更适合交给 {tool}。",
        "deep": "我帮你把问题问锋利、判断结论靠不靠谱；大规模搜索交给 {tool}，别让我当爬虫。",
    },
}


def _normalize_depth(relationship_depth: str | None) -> str:
    if relationship_depth in _OPENINGS:
        return relationship_depth
    return "familiar"


def boundary_response(
    user_input: str,
    cfg: dict,
    relationship_depth: str | None = None,
) -> str | None:
    """边界模板直出已关闭：一律交 LLM 按 system prompt 自然回应。"""
    return None
