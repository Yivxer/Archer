import feedparser
import re
from datetime import datetime

SKILL = {
    "name": "rss_reader",
    "description": "读取 RSS/Atom 订阅源，获取最新文章列表或全文摘要",
    "version": "1.0.0",
    "author": "archer-builtin",
}

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "rss_reader",
            "description": (
                "读取 RSS 或 Atom 订阅源，返回最新文章列表（标题、日期、摘要、链接）。"
                "action=list 返回文章列表；action=read 返回指定文章全文。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "RSS/Atom 订阅链接",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["list", "read"],
                        "description": "list=文章列表（默认），read=第 N 篇全文",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "（action=list）返回条数，默认 10",
                    },
                    "index": {
                        "type": "integer",
                        "description": "（action=read）第几篇，从 1 开始",
                    },
                },
                "required": ["url"],
            },
        },
    }

def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def _fmt_date(entry) -> str:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6]).strftime("%Y-%m-%d")
            except Exception:
                pass
    return ""

def run(args: dict) -> str:
    url = args.get("url", "").strip()
    if not url:
        return "错误：url 不能为空"

    action = args.get("action", "list")
    limit  = int(args.get("limit", 10))
    index  = int(args.get("index", 1))

    try:
        feed = feedparser.parse(url)
    except Exception as e:
        return f"解析失败：{e}"

    if feed.bozo and not feed.entries:
        return f"无法解析此 RSS 源：{url}"

    feed_title = getattr(feed.feed, "title", url)
    entries    = feed.entries

    if not entries:
        return f"「{feed_title}」暂无文章。"

    if action == "list":
        lines = [f"📡 {feed_title}  共 {len(entries)} 篇，显示最新 {min(limit, len(entries))} 篇\n"]
        for i, e in enumerate(entries[:limit], 1):
            dt    = _fmt_date(e)
            title = getattr(e, "title", "（无标题）")
            link  = getattr(e, "link", "")
            summary_raw = getattr(e, "summary", "")
            summary = _strip_html(summary_raw)[:80].replace("\n", " ")
            lines.append(f"  {i}. [{dt}] {title}")
            if summary:
                lines.append(f"      {summary}…")
            if link:
                lines.append(f"      {link}")
        return "\n".join(lines)

    elif action == "read":
        if index < 1 or index > len(entries):
            return f"索引超范围：共 {len(entries)} 篇，请输入 1–{len(entries)}"
        e     = entries[index - 1]
        title = getattr(e, "title", "（无标题）")
        dt    = _fmt_date(e)
        link  = getattr(e, "link", "")
        content_raw = ""
        if hasattr(e, "content"):
            content_raw = e.content[0].get("value", "")
        if not content_raw:
            content_raw = getattr(e, "summary", "")
        text = _strip_html(content_raw)
        if len(text) > 5000:
            text = text[:5000] + "\n\n…（已截断）"
        return f"📄 {title}\n{dt}  {link}\n\n{text}"

    return f"未知 action：{action}"
