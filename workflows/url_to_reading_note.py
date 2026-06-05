"""
url_to_reading_note: URL → 抓取内容 → LLM 整理为阅读笔记 → 写入 Obsidian
"""
import re
import sys
from datetime import datetime
from pathlib import Path

WORKFLOW = {
    "name": "url",
    "description": "URL → 抓取内容 → 阅读笔记 → 写入 Obsidian",
    "usage": "/workflow url <URL> [关键词]",
}

_NOTE_PROMPT = """\
将以下网页内容整理为结构化阅读笔记。格式如下，严格按格式输出：

**核心主张**：（1-2句，最重要的判断）
**关键要点**：（3-5条，不复述原文，提炼判断）
**和我的关系**：（与个人处境/思考的具体连接，没有就写"暂时不明确"）
**可转化为**：（文章角度 / 结构化思考 / 行动，选一个最可能的）

简洁直接，不废话。"""


def run(args: list[str], console, cfg: dict) -> None:
    from skills.web_fetch import run as fetch
    from core.llm import stream_chat

    if not args:
        console.print("[yellow]用法：/workflow url <URL> [关键词][/yellow]")
        return

    url = args[0].strip()
    keyword = " ".join(args[1:]) if len(args) > 1 else ""

    # Step 1: 抓取
    console.print(f"[dim]▶ 抓取：{url}…[/dim]")
    content = fetch({"url": url, "max_chars": 8000})

    if any(content.startswith(p) for p in ("无效 URL", "HTTP 错误", "网络错误", "抓取失败", "抓取被拒绝")):
        console.print(f"[red]{content}[/red]")
        return

    console.print(f"[dim]抓取完成，{len(content)} 字符。[/dim]")

    # Step 2: LLM 整理
    console.print("[dim]▶ 整理为阅读笔记…[/dim]\n")
    user_content = f"URL：{url}"
    if keyword:
        user_content += f"\n关注角度：{keyword}"
    user_content += f"\n\n内容：\n{content[:6000]}"

    messages = [
        {"role": "system", "content": _NOTE_PROMPT},
        {"role": "user", "content": user_content},
    ]
    formatted = ""
    for chunk in stream_chat(messages):
        sys.stdout.write(chunk)
        sys.stdout.flush()
        formatted += chunk
    sys.stdout.write("\n\n")
    sys.stdout.flush()

    if not formatted.strip():
        console.print("[red]LLM 整理失败，内容为空。[/red]")
        return

    # Step 3: 写入 Obsidian
    vault = Path(cfg["obsidian"]["vault_path"]).expanduser().resolve()
    today = datetime.now().strftime("%Y-%m-%d")
    # 取域名部分作为 slug
    domain = re.sub(r"https?://([^/]+).*", r"\1", url)
    slug = re.sub(r"[^\w一-鿿]+", "-", domain[:30]).strip("-")
    note_rel = f"30笔记归纳✍️/阅读笔记/{today}-{slug}.md"
    note_abs = vault / note_rel

    try:
        note_abs.resolve().relative_to(vault)
    except ValueError:
        console.print("[red]路径验证失败，拒绝写入。[/red]")
        return

    note_abs.parent.mkdir(parents=True, exist_ok=True)
    note_content = (
        f"# 阅读笔记 {today}\n\n"
        f"来源：{url}\n\n"
        f"---\n\n"
        f"{formatted.strip()}\n"
    )
    note_abs.write_text(note_content, encoding="utf-8")
    console.print(f"[green]✓ 已写入：{note_rel}[/green]")
