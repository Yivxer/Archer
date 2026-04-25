from pathlib import Path

SKILL = {
    "name": "file_ops",
    "description": "读取或写入本地文件",
    "version": "1.0.0",
    "author": "archer-builtin",
}

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "file_ops",
            "description": "读取或写入本地文件内容。action=read 读取，action=write 写入。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["read", "write"],
                        "description": "操作类型",
                    },
                    "path": {
                        "type": "string",
                        "description": "文件的绝对路径",
                    },
                    "content": {
                        "type": "string",
                        "description": "写入时的内容（action=write 时必填）",
                    },
                },
                "required": ["action", "path"],
            },
        },
    }

def run(args: dict) -> str:
    action = args.get("action")
    path = Path(args.get("path", ""))

    if action == "read":
        if not path.exists():
            return f"文件不存在：{path}"
        try:
            text = path.read_text(encoding="utf-8")
            if len(text) > 4000:
                return text[:4000] + f"\n\n…（已截断，共 {len(text)} 字符）"
            return text
        except Exception as e:
            return f"读取失败：{e}"

    if action == "write":
        content = args.get("content", "")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return f"已写入：{path}"
        except Exception as e:
            return f"写入失败：{e}"

    return f"未知操作：{action}"
