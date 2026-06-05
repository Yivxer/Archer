"""
market_research — 市场调研

综合运用 web_search + web_fetch 技能，对指定主题做结构化调研，
输出结构化的调研报告（市场概况 / 主要玩家 / 趋势 / 机会点）。

Archer 内部调用方式：
1. 用 web_search 搜索多个关键词
2. 用 web_fetch 读取高质量结果页面
3. 用 LLM 汇总成报告
"""
from pathlib import Path
import importlib

SKILL = {
    "name": "market_research",
    "description": "市场调研：综合搜索+抓取+LLM 汇总，输出结构化报告",
    "version": "1.0.0",
    "author": "archer-builtin",
    "risk": "low",
    "default_timeout": 90,
}

# 懒调用 LLM
def _llm_stream(prompt: str) -> str:
    from core.llm import stream_chat
    parts = []
    for chunk in stream_chat([{"role": "user", "content": prompt}]):
        if isinstance(chunk, str):
            parts.append(chunk)
    return "".join(parts)


def _call_skill(skill_name: str, args: dict) -> str:
    """调用 Archer 内部技能（避免子进程开销）。"""
    from importlib import import_module
    mod = import_module(f"skills.{skill_name}")
    return mod.run(args)


# ── Schema ────────────────────────────────────────────────────────

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "market_research",
            "description": (
                "市场调研：自动搜索、抓取、汇总，生成结构化报告。\n"
                "支持竞争分析、行业趋势、用户画像等调研场景。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "调研主题，如「AI 写作工具市场」「低代码平台趋势」",
                    },
                    "depth": {
                        "type": "string",
                        "enum": ["quick", "standard", "deep"],
                        "description": "调研深度：quick=3个搜索词；standard=5个；deep=8个+竞品深挖",
                    },
                    "target_market": {
                        "type": "string",
                        "description": "目标市场/地区，如「中国」「全球」「北美」",
                    },
                    "save_path": {
                        "type": "string",
                        "description": "报告保存路径（.md/.txt），填写后自动保存",
                    },
                },
                "required": ["topic"],
            },
        },
    }


# ── 搜索关键词模板 ────────────────────────────────────────────────

_SEARCH_TEMPLATES = {
    "quick": [
        "{topic} 市场分析",
        "{topic} 主要玩家",
        "{topic} 趋势",
    ],
    "standard": [
        "{topic} 市场分析",
        "{topic} 主要玩家 竞争格局",
        "{topic} 趋势 2025 2026",
        "{topic} 用户画像",
        "{topic} 商业模式",
    ],
    "deep": [
        "{topic} 市场规模 增长率",
        "{topic} 竞争格局 主要玩家",
        "{topic} 技术趋势 未来方向",
        "{topic} 用户需求 痛点",
        "{topic} 商业模式 收入来源",
        "{topic} 进入壁垒 成功案例",
        "{topic} 监管政策",
        "{topic} SWOT 分析",
    ],
}

# ── Run ────────────────────────────────────────────────────────────


def run(args: dict) -> str:
    topic    = args.get("topic", "").strip()
    depth    = args.get("depth", "standard").strip()
    market   = args.get("target_market", "").strip()
    save_path = args.get("save_path", "").strip() or None

    if not topic:
        return "错误：topic 参数不能为空"

    # 1. 生成搜索词
    templates = _SEARCH_TEMPLATES.get(depth, _SEARCH_TEMPLATES["standard"])
    queries = [q.format(topic=topic, market=market or "") for q in templates]

    # 2. 搜索 + 抓取
    all_results = []
    seen_urls = set()

    for q in queries:
        try:
            search_result = _call_skill("web_search", {"query": q, "max_results": 5})
            # 解析搜索结果中的 URL
            urls = _parse_urls(search_result)
            for url in urls[:3]:  # 每个查询取前3条
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                try:
                    fetch_result = _call_skill("web_fetch", {"url": url, "max_chars": 3000})
                    all_results.append({"url": url, "query": q, "content": fetch_result[:2000]})
                except Exception:
                    pass
        except Exception:
            pass

    if not all_results:
        return f"⚠️ 未获取到有效调研数据（topic={topic}），请尝试更换搜索词或检查网络"

    # 3. 汇总成报告
    report = _compile_report(topic, market, all_results, depth)
    if save_path:
        p = Path(save_path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(report, encoding="utf-8")
        return f"✅ 调研报告已保存：{p}\n\n{report[:1000]}...\n\n（完整内容已保存）"

    return report


def _parse_urls(search_output: str) -> list[str]:
    """从 web_search 输出中提取 URL。"""
    import re
    urls = re.findall(r"https?://[^\s\)]+", search_output)
    return list(dict.fromkeys(urls))  # 保序去重


def _compile_report(topic: str, market: str, results: list[dict], depth: str) -> str:
    """用 LLM 汇总搜索结果，生成结构化报告。"""
    # 截断输入，防止超长
    evidence = ""
    for r in results[:15]:  # 最多用 15 条
        evidence += f"\n\n## 来源：{r['url']}\n查询：{r['query']}\n{r['content'][:1500]}"
    if len(evidence) > 12000:
        evidence = evidence[:12000] + "\n\n（后续内容已截断）"

    prompt = (
        "你是一位资深市场分析师。请根据以下调研数据，"
        "输出一份结构化市场调研报告。\n\n"
        f"调研主题：{topic}\n"
        f"目标市场：{market or '未指定'}\n"
        f"调研深度：{depth}\n\n"
        "报告结构（Markdown 格式）：\n"
        "1. 摘要（3-5 句话）\n"
        "2. 市场概况（规模/增长率/阶段）\n"
        "3. 主要玩家 & 竞争格局\n"
        "4. 关键趋势 & 技术方向\n"
        "5. 用户需求 & 痛点\n"
        "6. 机会点 & 建议\n"
        "7. 信息来源列表\n\n"
        "要求：客观、有数据支撑、不编造数字。"
        "如果数据不足，明确标注「数据不足」"
        f"\n\n=== 调研数据 ==={evidence}"
    )

    return _llm_stream(prompt)
