import subprocess
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
    limit     = int(args.get("limit", 20))

    if not keyword:
        return "错误：keyword 不能为空"

    directory = str(Path(directory).expanduser())

    try:
        if mode == "name":
            name_pat = f"*{keyword}*" + (f".{ext}" if ext else "")
            cmd = (
                f'find "{directory}" -iname "{name_pat}" '
                f'-not -path "*/.*" -not -path "*/node_modules/*" '
                f'2>/dev/null | head -{limit}'
            )
        else:  # content
            ext_flag = f'--include="*.{ext}"' if ext else '--include="*.md" --include="*.txt" --include="*.py"'
            cmd = (
                f'grep -r -l {ext_flag} -i "{keyword}" "{directory}" '
                f'--exclude-dir=".git" --exclude-dir="node_modules" '
                f'2>/dev/null | head -{limit}'
            )

        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        lines  = [l.strip() for l in result.stdout.splitlines() if l.strip()]

        if not lines:
            return f'未找到{"文件名" if mode == "name" else "内容"}包含「{keyword}」的文件。'

        output = [f'找到 {len(lines)} 个文件（mode={mode}，keyword={keyword}）：\n']
        for p in lines:
            output.append(f'  @{p}')
        output.append('\n提示：用 @路径 直接引用文件内容')
        return '\n'.join(output)

    except subprocess.TimeoutExpired:
        return "搜索超时（15s）"
    except Exception as e:
        return f"搜索失败：{e}"
