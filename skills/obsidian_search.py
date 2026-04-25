import subprocess
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
    max_results = args.get("max_results", 20)

    if not keyword:
        return "错误：keyword 不能为空"

    vault = _vault()
    try:
        result = subprocess.run(
            ["grep", "-r", "-l", "--include=*.md", "-i", keyword, str(vault)],
            capture_output=True, text=True, timeout=15,
        )
        files = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        if not files:
            return f"未找到包含「{keyword}」的笔记。"

        lines = [f"找到 {len(files)} 篇笔记包含「{keyword}」：\n"]
        for f in files[:max_results]:
            rel = Path(f).relative_to(vault) if Path(f).is_relative_to(vault) else Path(f)
            lines.append(f"  - {rel}")

        if len(files) > max_results:
            lines.append(f"\n…还有 {len(files) - max_results} 条未显示")

        return "\n".join(lines)
    except subprocess.TimeoutExpired:
        return "搜索超时（15s）"
    except Exception as e:
        return f"搜索失败：{e}"
