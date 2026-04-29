import tomllib
from pathlib import Path

SKILL = {
    "name": "obsidian_search",
    "description": "在 Obsidian vault 中全文搜索关键词，返回匹配的笔记列表",
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
            "name": "obsidian_search",
            "description": (
                "在整个 Obsidian vault 中全文搜索关键词，返回包含该词的笔记路径和匹配行。"
                "适合在不知道笔记具体位置时查找内容。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "要搜索的关键词",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最多返回的匹配条数，默认 20",
                    },
                },
                "required": ["keyword"],
            },
        },
    }

def run(args: dict) -> str:
    keyword = args.get("keyword", "").strip()
    try:
        max_results = int(args.get("max_results", 20))
    except (TypeError, ValueError):
        max_results = 20
    max_results = max(1, min(max_results, 100))

    if not keyword:
        return "错误：keyword 不能为空"

    vault = _vault().expanduser().resolve()
    if not vault.exists():
        return f"搜索失败：vault 不存在：{vault}"

    try:
        needle = keyword.lower()
        files: list[Path] = []
        for path in _walk_notes(vault):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if needle in text.lower():
                files.append(path)
                if len(files) >= max_results + 1:
                    break
        if not files:
            return f"未找到包含「{keyword}」的笔记。"

        lines = [f"找到 {len(files)} 篇笔记包含「{keyword}」：\n"]
        for f in files[:max_results]:
            rel = f.relative_to(vault)
            lines.append(f"  - {rel}")

        if len(files) > max_results:
            lines.append(f"\n…还有 {len(files) - max_results} 条未显示")

        return "\n".join(lines)
    except Exception as e:
        return f"搜索失败：{e}"

def _walk_notes(vault: Path):
    skip_dirs = {".git", ".obsidian", "node_modules", "__pycache__"}
    for path in vault.rglob("*.md"):
        if any(part in skip_dirs for part in path.parts):
            continue
        resolved = path.resolve()
        try:
            resolved.relative_to(vault)
        except ValueError:
            continue
        yield resolved
