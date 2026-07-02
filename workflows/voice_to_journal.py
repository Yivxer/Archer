"""
voice_to_journal: 音频 → Whisper 转录 → LLM 整理 → 写入 Obsidian 日记
"""
import sys
from datetime import datetime
from pathlib import Path

WORKFLOW = {
    "name": "voice",
    "description": "音频文件 → 转录 → 日记条目 → 写入 Obsidian",
    "usage": "/workflow voice <音频路径>",
}


def run(args: list[str], console, cfg: dict) -> None:
    from skills.whisper_transcribe import run as transcribe
    from core.llm import stream_chat

    if not args:
        console.print("[yellow]用法：/workflow voice <音频路径>[/yellow]")
        return

    path = Path(" ".join(args)).expanduser().resolve()
    if not path.exists():
        console.print(f"[red]文件不存在：{path}[/red]")
        return

    # Step 1: 转录
    console.print(f"[dim]▶ 转录：{path.name}…[/dim]")
    raw = transcribe({"path": str(path), "model": "base"})

    # whisper_transcribe 出错时以错误前缀开头
    if any(raw.startswith(p) for p in ("错误：", "文件不存在", "不支持", "不是文件", "文件过大")):
        console.print(f"[red]{raw}[/red]")
        return

    # 去掉 whisper 输出的首行 header（格式：🎙 xxx\n\n内容）
    transcript = raw.split("\n\n", 1)[-1].strip()
    if not transcript:
        console.print("[red]转录内容为空。[/red]")
        return

    console.print(f"[dim]转录完成，{len(transcript)} 字符。[/dim]")

    # Step 2: LLM 整理为日记格式
    console.print("[dim]▶ 整理为日记格式…[/dim]\n")
    messages = [
        {
            "role": "system",
            "content": (
                "整理以下语音转写内容为日记条目。"
                "保持口语原意，修正标点和段落，不添加内容，不删除关键信息。"
                "只输出整理好的正文，无需标题。"
            ),
        },
        {"role": "user", "content": transcript},
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
    from skills._vault import resolve_vault
    vault = resolve_vault()
    if vault is None:
        console.print("[red]Obsidian vault 未配置：请在 archer.toml 设置 [obsidian].vault_path[/red]")
        return
    today = datetime.now().strftime("%Y-%m-%d")
    hour_min = datetime.now().strftime("%H%M")
    note_rel = f"00碎片记录💭/语音日记/{today}-{hour_min}.md"
    note_abs = vault / note_rel

    try:
        note_abs.resolve().relative_to(vault)
    except ValueError:
        console.print("[red]路径验证失败，拒绝写入。[/red]")
        return

    note_abs.parent.mkdir(parents=True, exist_ok=True)
    content = f"# {today} 语音日记\n\n{formatted.strip()}\n\n---\n*来源：{path.name}*\n"
    note_abs.write_text(content, encoding="utf-8")
    console.print(f"[green]✓ 已写入：{note_rel}[/green]")
