from pathlib import Path

from skills._vault import (
    resolve_note_path as _resolve_note_path,
    read_note as _read_note,
    parse_frontmatter as _parse_frontmatter,
    extract_wikilinks as _extract_wikilinks,
)

SKILL = {
    "name": "obsidian_read",
    "description": "按路径读取 Obsidian vault 中的笔记内容",
    "version": "1.2.0",
    "author": "archer-builtin",
}

__meta__ = {
    "name": "obsidian_read",
    "description": "读取 Obsidian vault 笔记正文",
    "keywords": ["obsidian", "笔记", "vault", "读笔记", "SOUL.md", "MEMORY.md"],
    "risk": "low",
    "auto_trigger": True,
}

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "obsidian_read",
            "description": (
                "读取 Obsidian vault 中的笔记文件内容。"
                "path 参数是相对于 vault 根目录的路径，例如 '20个人系统🚀/205AI记忆🦞/SOUL.md'。"
                "也可以传入绝对路径。"
                "大文件自动按字符数截断，通过 offset 可翻页。"
                "默认自动解析 frontmatter 并在开头展示属性。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "笔记路径（相对 vault 或绝对路径）",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "最多返回的字符数，默认 4000",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "从第几个字符开始读（用于翻大文件），默认 0",
                    },
                    "include_meta": {
                        "type": "boolean",
                        "description": "是否在结果开头包含 frontmatter 和 wikilinks 摘要，默认 true",
                    },
                },
                "required": ["path"],
            },
        },
    }

def run(args: dict) -> str:
    raw_path = args.get("path", "").strip()
    try:
        max_chars = int(args.get("max_chars", 4000))
    except (TypeError, ValueError):
        max_chars = 4000
    max_chars = max(200, min(max_chars, 50000))
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)
    include_meta = args.get("include_meta", True)
    if isinstance(include_meta, str):
        include_meta = include_meta.lower() not in ("false", "0", "no")

    try:
        p = _resolve_note_path(raw_path)
    except Exception as e:
        return f"路径被拒绝：{e}"

    if not p.exists():
        return f"笔记不存在：{p}"

    try:
        text = _read_note(p)
        total = len(text)

        props, body = _parse_frontmatter(text)
        wikilinks = _extract_wikilinks(text)[:20]

        header = ""
        if include_meta and (props or wikilinks):
            header_parts = []
            if props:
                header_parts.append("--- properties ---")
                for k, v in props.items():
                    if isinstance(v, list):
                        header_parts.append(f"{k}: {', '.join(str(x) for x in v)}")
                    else:
                        header_parts.append(f"{k}: {v}")
            if wikilinks:
                header_parts.append(f"--- wikilinks ({len(wikilinks)}) ---")
                header_parts.append(", ".join(wikilinks[:15]))
                if len(wikilinks) > 15:
                    header_parts[-1] += f" …+{len(wikilinks) - 15}"
            header = "\n".join(header_parts) + "\n\n--- content ---\n\n"

        # 正文截断（仅 body 部分算 max_chars，header 不计入）
        body_segment = body[offset:offset + max_chars]
        truncation_note = ""
        if offset > 0 or len(body) > offset + max_chars:
            end_pos = min(offset + max_chars, len(body))
            truncation_note = f"\n\n…（显示 {offset}-{end_pos}/{len(body)} 字符，用 offset 翻页）"

        result = header + body_segment + truncation_note
        return result
    except Exception as e:
        return f"读取失败：{e}"
