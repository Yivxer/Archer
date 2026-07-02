"""
web_search — 网页搜索技能

通过 DuckDuckGo HTML 接口搜索互联网，不需要 API Key。
返回结果标题 + 摘要 + URL，配合 web_fetch 深入阅读。

用途：
- 查技术文档（"TypeScript interface extends 怎么写"）
- 查错误信息（"Error: ENOENT no such file or directory"）
- 查时效信息（"DeepSeek v4 API 最新定价"）
- 查框架 API（"tailwind CSS grid responsive"）

注意：搜索结果为公开互联网内容，时效性和准确性以原始来源为准。
"""
import urllib.request
import urllib.parse
import re
import time
from core.url_safety import open_public_http_url, validate_public_http_url

SKILL = {
    "name": "web_search",
    "description": "用 DuckDuckGo 搜索互联网，查技术文档、错误信息、时效资讯，不需要 API Key",
    "version": "1.0.0",
    "author": "archer-builtin",
    "risk": "low",
    "default_timeout": 15,
}

__meta__ = {
    "name": "web_search",
    "description": "搜索互联网文档、报错与时效信息",
    "keywords": ["搜索", "搜一下", "查一下", "怎么写", "报错", "官方文档", "how to"],
    "risk": "low",
    "auto_trigger": True,
}


def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "搜索互联网，返回相关网页的标题、摘要和链接。"
                "适合查技术文档、错误信息、API 用法、时效资讯等。"
                "拿到链接后可用 web_fetch 阅读完整内容。"
                "不需要 API Key，通过 DuckDuckGo 搜索。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索词，支持中英文，可包含技术关键词和错误信息",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最多返回几条结果，默认 6，最多 10",
                    },
                },
                "required": ["query"],
            },
        },
    }


def _ddg_search(query: str, max_results: int = 6) -> list[dict]:
    """通过 DuckDuckGo HTML 接口搜索，解析结果。"""
    encoded = urllib.parse.quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded}"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    safe_url = validate_public_http_url(url)
    with open_public_http_url(safe_url, headers=headers, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="ignore")

    results = []

    # 解析结果块：DuckDuckGo HTML 结构相对稳定
    # 结果 div 包含 result__title + result__snippet + result__url
    blocks = re.findall(
        r'class="result__body".*?(?=class="result__body"|$)',
        html, re.DOTALL
    )
    if not blocks:
        # 备用解析方式
        blocks = re.findall(
            r'<div class="result[^"]*"[^>]*>(.*?)</div>\s*</div>',
            html, re.DOTALL
        )

    # 直接用正则提取标题、链接、摘要
    title_pattern = re.compile(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
    snippet_pattern = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)
    url_pattern = re.compile(r'class="result__url"[^>]*>(.*?)</span>', re.DOTALL)

    title_matches = title_pattern.findall(html)
    snippet_matches = snippet_pattern.findall(html)

    def strip_tags(s: str) -> str:
        s = re.sub(r'<[^>]+>', '', s)
        s = re.sub(r'&amp;', '&', s)
        s = re.sub(r'&lt;', '<', s)
        s = re.sub(r'&gt;', '>', s)
        s = re.sub(r'&quot;', '"', s)
        s = re.sub(r'&#x27;', "'", s)
        s = re.sub(r'&nbsp;', ' ', s)
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    for i, (href, title_html) in enumerate(title_matches[:max_results]):
        title = strip_tags(title_html)
        snippet = strip_tags(snippet_matches[i]) if i < len(snippet_matches) else ""

        # DuckDuckGo href 可能是 //duckduckgo.com/l/?uddg=... 重定向
        if href.startswith("//duckduckgo.com/l/"):
            match = re.search(r'uddg=([^&]+)', href)
            if match:
                href = urllib.parse.unquote(match.group(1))
        elif href.startswith("/"):
            href = "https://duckduckgo.com" + href

        if title and href:
            results.append({
                "title": title,
                "url": href,
                "snippet": snippet,
            })

    return results[:max_results]


def run(args: dict) -> str:
    query = args.get("query", "").strip()
    max_results = min(int(args.get("max_results", 6)), 10)

    if not query:
        return "错误：query 不能为空"

    try:
        results = _ddg_search(query, max_results)
    except Exception as e:
        return f"搜索失败：{e}\n提示：检查网络连接，或直接用 web_fetch 访问已知 URL"

    if not results:
        return f"未找到「{query}」的相关结果\n提示：尝试换用英文关键词或更具体的搜索词"

    lines = [f"搜索「{query}」，共 {len(results)} 条结果：\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. **{r['title']}**")
        if r["snippet"]:
            lines.append(f"   {r['snippet']}")
        lines.append(f"   {r['url']}")
        lines.append("")

    lines.append("提示：用 web_fetch url=<链接> 阅读完整内容")
    return "\n".join(lines)
