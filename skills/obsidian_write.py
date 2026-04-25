import tomllib
from datetime import datetime
from pathlib import Path

SKILL = {
    "name": "obsidian_write",
    "description": "写入或追加内容到 Obsidian vault 中的笔记",
    "version": "1.0.0",
    "author": "archer-builtin",
}

def _vault() -> Path:
    cfg_path = Path(__file__).parent.parent / "archer.toml"
    with open(cfg_path, "rb") as f:
        cfg = tomllib.load(f)
    return Path(cfg["obsidian"]["vault_path"])

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "obsidian_write",
            "description": (
                "向 Obsidian vault 中的笔记写入内容。"
                "mode=append 在文件末尾追加（默认）；mode=overwrite 覆盖整个文件；mode=prepend 在开头插入。"
                "若笔记不存在会自动创建。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "笔记路径（相对 vault 或绝对路径）",
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入的内容",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["append", "overwrite", "prepend"],
                        "description": "写入模式，默认 append",
                    },
                    "add_timestamp": {
                        "type": "boolean",
                        "description": "追加时是否自动加时间戳，默认 false",
                    },
                },
                "required": ["path", "content"],
            },
        },
    }

def run(args: dict) -> str:
    raw_path = args.get("path", "").strip()
    content = args.get("content", "")
    mode = args.get("mode", "append")
    add_ts = args.get("add_timestamp", False)

    p = Path(raw_path)
    if not p.is_absolute():
        p = _vault() / raw_path

    try:
        p.parent.mkdir(parents=True, exist_ok=True)

        if add_ts:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            content = f"\n<!-- {ts} -->\n{content}"

        if mode == "overwrite":
            p.write_text(content, encoding="utf-8")
            return f"已覆盖写入：{p.name}"

        if mode == "prepend":
            existing = p.read_text(encoding="utf-8") if p.exists() else ""
            p.write_text(content + "\n" + existing, encoding="utf-8")
            return f"已在开头插入内容：{p.name}"

        # 默认 append
        with open(p, "a", encoding="utf-8") as f:
            f.write("\n" + content)
        return f"已追加到：{p.name}"

    except Exception as e:
        return f"写入失败：{e}"
