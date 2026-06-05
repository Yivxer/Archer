import urllib.request
import urllib.error
import re
from core.url_safety import open_public_http_url, validate_public_http_url

SKILL = {
    "name": "web_fetch",
    "description": "抓取网页内容并返回纯文本，用于读取文章、文档、搜索结果",
    "version": "1.0.0",
    "author": "archer-builtin",
}

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": (
                "抓取指定 URL 的网页内容，去除 HTML 标签后返回纯文本。"
                "适合读取文章、技术文档、GitHub README 等。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "要抓取的网页 URL",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "最多返回的字符数，默认 4000",
                    },
                },
                "required": ["url"],
            },
        },
    }

def _strip_html(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>",  "", text,  flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&[a-z]+;", "", text)
    text = re.sub(r"\s{3,}", "\n\n", text)
    return text.strip()

def run(args: dict) -> str:
    url = args.get("url", "").strip()
    try:
        max_chars = int(args.get("max_chars", 4000))
    except (TypeError, ValueError):
        max_chars = 4000
    max_chars = max(200, min(max_chars, 12000))

    try:
        url = validate_public_http_url(url)
    except ValueError as e:
        return f"无效 URL：{e}"

    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    try:
        with open_public_http_url(url, headers=headers, timeout=15) as resp:
            raw = resp.read(1_000_000).decode("utf-8", errors="ignore")
        text = _strip_html(raw)
        if len(text) > max_chars:
            return text[:max_chars] + f"\n\n…（已截断，共 {len(text)} 字符）"
        return text
    except urllib.error.HTTPError as e:
        return f"HTTP 错误 {e.code}：{url}"
    except urllib.error.URLError as e:
        return f"网络错误：{e.reason}"
    except ValueError as e:
        return f"抓取被拒绝：{e}"
    except Exception as e:
        return f"抓取失败：{e}"
