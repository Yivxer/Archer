import urllib.request
import urllib.error
import re

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
    max_chars = args.get("max_chars", 4000)

    if not url.startswith("http"):
        return f"无效 URL：{url}"

    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        text = _strip_html(raw)
        if len(text) > max_chars:
            return text[:max_chars] + f"\n\n…（已截断，共 {len(text)} 字符）"
        return text
    except urllib.error.HTTPError as e:
        return f"HTTP 错误 {e.code}：{url}"
    except urllib.error.URLError as e:
        return f"网络错误：{e.reason}"
    except Exception as e:
        return f"抓取失败：{e}"
