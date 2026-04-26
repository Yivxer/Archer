from pathlib import Path

SKILL = {
    "name": "file_ops",
    "description": "读取、写入、追加或列出本地文件",
    "version": "1.2.0",
    "author": "archer-builtin",
    "risk": "medium",
    "default_timeout": 10,
}

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "file_ops",
            "description": (
                "读写本地文件。当用户说「读取文件」「帮我看看这个文件」「打开/查看/读一下」某个路径时，"
                "调用此技能（action=read）。支持任意文本文件：.txt .md .py .json .toml .yaml .log 等。"
                "写入用 action=write，追加用 action=append，列出目录内容用 action=list。"
                "路径支持绝对路径和 ~ 开头的路径，自动展开 ~。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["read", "write", "append", "list"],
                        "description": "read=读取内容，write=覆盖写入，append=追加内容，list=列出目录文件",
                    },
                    "path": {
                        "type": "string",
                        "description": "文件或目录的路径，支持 ~ 开头（如 ~/Desktop/notes.txt）或绝对路径",
                    },
                    "content": {
                        "type": "string",
                        "description": "写入或追加的内容（action=write/append 时必填）",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "读取时最大字符数，默认 6000",
                    },
                },
                "required": ["action", "path"],
            },
        },
    }

def run(args: dict) -> str:
    action   = args.get("action", "read")
    raw_path = args.get("path", "").strip()
    path     = Path(raw_path).expanduser()
    enc      = "utf-8"
    max_ch   = int(args.get("max_chars", 6000))

    if action == "read":
        if not path.exists():
            return f"文件不存在：{path}\n提示：如果路径包含空格，请用引号包裹，或使用 @\"路径\" 语法。"
        if path.is_dir():
            return f"{path} 是目录，请改用 action=list 列出内容。"
        try:
            text = path.read_text(encoding=enc, errors="ignore")
            if len(text) > max_ch:
                return text[:max_ch] + f"\n\n…（已截断，原文共 {len(text)} 字符，可用 max_chars 调整限制）"
            return text
        except Exception as e:
            return f"读取失败：{e}"

    if action == "write":
        content = args.get("content", "")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding=enc)
            return f"已写入：{path}（{len(content)} 字符）"
        except Exception as e:
            return f"写入失败：{e}"

    if action == "append":
        content = args.get("content", "")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding=enc) as f:
                f.write(content)
            return f"已追加到：{path}（+{len(content)} 字符）"
        except Exception as e:
            return f"追加失败：{e}"

    if action == "list":
        if not path.exists():
            return f"路径不存在：{path}"
        if not path.is_dir():
            return f"{path} 不是目录"
        try:
            items = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
            lines = []
            for item in items[:50]:
                prefix = "📄 " if item.is_file() else "📁 "
                lines.append(prefix + item.name)
            if len(list(path.iterdir())) > 50:
                lines.append("…（仅显示前 50 项）")
            return "\n".join(lines)
        except Exception as e:
            return f"列出失败：{e}"

    return f"未知操作：{action}，可用：read / write / append / list"
