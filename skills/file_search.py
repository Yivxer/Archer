import os
from pathlib import Path

SKILL = {
    "name": "file_search",
    "description": "在本地磁盘搜索文件，按名称或内容查找",
    "version": "1.0.0",
    "author": "archer-builtin",
}

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "file_search",
            "description": (
                "在本地磁盘搜索文件。"
                "mode=name 按文件名搜索；mode=content 按内容搜索（grep）。"
                "找到后返回路径列表，可配合 @路径 引用使用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词（文件名或内容片段）",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["name", "content"],
                        "description": "搜索模式：name=按文件名（默认）、content=按文件内容",
                    },
                    "directory": {
                        "type": "string",
                        "description": "搜索起始目录，默认 ~/（家目录）",
                    },
                    "ext": {
                        "type": "string",
                        "description": "限定扩展名，例如 md / py / txt（可选）",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回条数，默认 20",
                    },
                },
                "required": ["keyword"],
            },
        },
    }

def run(args: dict) -> str:
    keyword   = args.get("keyword", "").strip()
    mode      = args.get("mode", "name")
    directory = args.get("directory", str(Path.home()))
    ext       = args.get("ext", "")
    try:
        limit = int(args.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20

    if not keyword:
        return "错误：keyword 不能为空"

    directory_path = Path(directory).expanduser()
    if not directory_path.exists():
        return f"搜索失败：目录不存在：{directory_path}"

    limit = max(1, min(limit, 100))

    ext = ext.strip().lstrip(".")

    try:
        lines: list[str] = []
        if mode == "name":
            needle = keyword.lower()
            suffix = f".{ext.lower()}" if ext else ""
            for path in _walk_files(directory_path):
                name = path.name.lower()
                if needle in name and (not suffix or name.endswith(suffix)):
                    lines.append(str(path))
                    if len(lines) >= limit:
                        break
        else:  # content
            allowed_exts = {f".{ext.lower()}"} if ext else {".md", ".txt", ".py"}
            needle = keyword.lower()
            for path in _walk_files(directory_path):
                if path.suffix.lower() not in allowed_exts:
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                if needle in text.lower():
                    lines.append(str(path))
                    if len(lines) >= limit:
                        break

        if not lines:
            return f'未找到{"文件名" if mode == "name" else "内容"}包含「{keyword}」的文件。'

        output = [f'找到 {len(lines)} 个文件（mode={mode}，keyword={keyword}）：\n']
        for p in lines:
            output.append(f'  @{p}')
        output.append('\n提示：用 @路径 直接引用文件内容')
        return '\n'.join(output)

    except Exception as e:
        return f"搜索失败：{e}"

def _walk_files(root: Path):
    skip_dirs = {".git", "node_modules", "__pycache__"}
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        for filename in files:
            if filename.startswith("."):
                continue
            yield Path(current) / filename
