"""
网站健康检查技能：部署后验证 HTTP 状态、页面内容、RSS 更新。
为 deploy.sh 提供闭环验证，替代"扔上去就完了"的部署模式。
"""
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

SKILL = {
    "name": "site_check",
    "description": "部署后验证网站状态：HTTP 状态检查、页面内容验证、RSS 更新检查",
    "version": "1.0.0",
    "author": "archer-builtin",
}

SITE_URL = "https://iver.yivxer.com"
_UA = "Archer-SiteCheck/1.0"
_TIMEOUT = 12


def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "site_check",
            "description": (
                "验证网站部署状态。"
                "action=status 检查 URL 列表的 HTTP 状态码；"
                "action=content 验证页面包含指定关键词；"
                "action=rss 检查 RSS feed 最新条目及发布时间。"
                "无参数时默认检查首页和 RSS。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "content", "rss"],
                        "description": "检查类型",
                    },
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "（status/content）要检查的 URL 列表，留空则检查默认关键页面",
                    },
                    "keyword": {
                        "type": "string",
                        "description": "（content）页面中必须出现的关键词",
                    },
                    "rss_url": {
                        "type": "string",
                        "description": "（rss）RSS URL，留空则用 https://iver.yivxer.com/index.xml",
                    },
                },
                "required": ["action"],
            },
        },
    }


def _fetch(url: str) -> tuple[int, str]:
    """返回 (status_code, body)，失败返回 (-1, error_msg)。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.status, resp.read(80000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, str(e)
    except urllib.error.URLError as e:
        return -1, str(e.reason)
    except Exception as e:
        return -1, str(e)


def _check_status(urls: list[str]) -> str:
    if not urls:
        urls = [SITE_URL, f"{SITE_URL}/posts/", f"{SITE_URL}/about/"]
    lines = ["HTTP 状态检查："]
    all_ok = True
    for url in urls:
        code, _ = _fetch(url)
        if 200 <= code < 300:
            icon = "✅"
        elif code == -1:
            icon, all_ok = "⚠️ ", False
        else:
            icon, all_ok = "❌", False
        lines.append(f"  {icon} {code if code != -1 else 'ERR'}  {url}")
    lines.append("" if all_ok else "\n  有页面无法访问，请检查服务器状态。")
    return "\n".join(lines)


def _check_content(urls: list[str], keyword: str) -> str:
    if not keyword:
        return "错误：content 检查需要指定 keyword"
    if not urls:
        urls = [SITE_URL]
    lines = [f"内容验证（关键词：「{keyword}」）："]
    for url in urls:
        code, body = _fetch(url)
        if code == -1:
            lines.append(f"  ⚠️  无法访问 {url}：{body}")
        elif keyword in body:
            lines.append(f"  ✅ [{code}] 找到 → {url}")
        else:
            lines.append(f"  ❌ [{code}] 未找到 → {url}")
    return "\n".join(lines)


def _check_rss(rss_url: str) -> str:
    if not rss_url:
        rss_url = f"{SITE_URL}/index.xml"
    code, body = _fetch(rss_url)
    if code == -1:
        return f"RSS 检查失败：无法访问\n  {rss_url}\n  原因：{body}"
    if code != 200:
        return f"RSS 检查失败：HTTP {code} → {rss_url}"

    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        return f"RSS 解析失败（非合法 XML）：{e}\n前 300 字：{body[:300]}"

    # RSS 2.0
    items = root.findall(".//item")
    if items:
        item = items[0]
        title    = (item.findtext("title") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        link     = (item.findtext("link") or "").strip()
        age_str  = ""
        try:
            dt = parsedate_to_datetime(pub_date)
            age = datetime.now(timezone.utc) - dt
            age_str = f"（{age.days} 天前）"
        except Exception:
            pass
        return (
            f"RSS 最新条目：\n"
            f"  标题：{title}\n"
            f"  发布：{pub_date} {age_str}\n"
            f"  链接：{link}\n"
            f"  共 {len(items)} 篇文章"
        )

    # Atom
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", ns)
    if entries:
        e = entries[0]
        title   = (e.findtext("atom:title", namespaces=ns) or "").strip()
        updated = (e.findtext("atom:updated", namespaces=ns) or "").strip()
        return (
            f"Atom feed 最新条目：\n"
            f"  标题：{title}\n"
            f"  更新：{updated}\n"
            f"  共 {len(entries)} 篇"
        )

    return f"RSS 解析完成，未找到条目。\nFeed 前 300 字：{body[:300]}"


def run(args: dict) -> str:
    action  = args.get("action", "").strip()
    urls    = args.get("urls", [])
    keyword = args.get("keyword", "").strip()
    rss_url = args.get("rss_url", "").strip()

    match action:
        case "status":  return _check_status(urls)
        case "content": return _check_content(urls, keyword)
        case "rss":     return _check_rss(rss_url)
        case _:         return f"未知 action：{action}。可选：status / content / rss"
