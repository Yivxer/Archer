import re
import urllib.request
import urllib.error

SKILL = {
    "name": "summarize",
    "description": "总结网页、文章或长文内容，提取核心要点",
    "version": "1.0.0",
    "author": "archer-builtin",
}

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "summarize",
            "description": (
                "总结提供的文本或网页内容。可以传入 URL 自动抓取，也可以直接传入文本。"
                "输出结构化要点、摘要或大纲，适合快速消化长内容。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "要总结的文本内容（与 url 二选一）",
                    },
                    "url": {
                        "type": "string",
                        "description": "要总结的网页 URL（与 content 二选一）",
                    },
                    "style": {
                        "type": "string",
                        "enum": ["bullet", "paragraph", "outline"],
                        "description": "输出风格：bullet=要点列表（默认）、paragraph=段落摘要、outline=大纲结构",
                    },
                    "focus": {
                        "type": "string",
                        "description": "总结侧重点，例如「行动项」「核心论点」「数据结论」",
                    },
                },
            },
        },
    }

def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    raw = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r"<style[^>]*>.*?</style>",  "", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = re.sub(r"\s{3,}", "\n\n", raw)
    return raw.strip()[:6000]

def run(args: dict) -> str:
    content = args.get("content", "").strip()
    url     = args.get("url", "").strip()
    style   = args.get("style", "bullet")
    focus   = args.get("focus", "")

    if url and not content:
        try:
            content = _fetch(url)
        except Exception as e:
            return f"抓取失败：{e}"

    if not content:
        return "错误：请提供 content 文本或 url 网址"

    style_hint = {
        "bullet":    "用要点列表（- ）格式输出",
        "paragraph": "用段落摘要形式输出，不超过 200 字",
        "outline":   "用大纲（## / ###）结构输出",
    }.get(style, "用要点列表格式输出")

    focus_hint = f"，重点关注：{focus}" if focus else ""

    return f"请总结以下内容，{style_hint}{focus_hint}：\n\n{content}"
