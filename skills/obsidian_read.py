import tomllib
from pathlib import Path

SKILL = {
    "name": "obsidian_read",
    "description": "按路径读取 Obsidian vault 中的笔记内容",
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
            "name": "obsidian_read",
            "description": (
                "读取 Obsidian vault 中的笔记文件内容。"
                "path 参数是相对于 vault 根目录的路径，例如 '20个人系统🚀/205AI记忆🦞/SOUL.md'。"
                "也可以传入绝对路径。"
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
                },
                "required": ["path"],
            },
        },
    }

def run(args: dict) -> str:
    raw_path = args.get("path", "").strip()
    max_chars = args.get("max_chars", 4000)

    p = Path(raw_path)
    if not p.is_absolute():
        p = _vault() / raw_path

    if not p.exists():
        return f"笔记不存在：{p}"

    try:
        text = p.read_text(encoding="utf-8")
        if len(text) > max_chars:
            return text[:max_chars] + f"\n\n…（已截断，共 {len(text)} 字符）"
        return text
    except Exception as e:
        return f"读取失败：{e}"
