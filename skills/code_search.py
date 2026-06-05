"""
代码搜索技能：在文件或目录中精准查找关键词，返回行号和上下文。
比 file_search 更轻量，比 shell grep 更友好，专为大文件定位设计。
配合 file_ops start_line 使用：先 code_search 拿行号，再定点读取。
"""
import subprocess
from pathlib import Path

SKILL = {
    "name": "code_search",
    "description": "在代码文件中搜索关键词，返回行号和上下文，用于大文件定位",
    "version": "1.0.0",
    "author": "archer-builtin",
}


def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "code_search",
            "description": (
                "在文件或目录中搜索关键词，返回匹配行号和周围上下文。"
                "专为大文件定位设计：先用 code_search 找到目标行号，"
                "再用 file_ops action=read start_line=N 定点读取，避免反复读整个大文件。"
                "支持正则表达式（grep -E）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词或正则表达式（如 'gate-card|邀请码|invite'）",
                    },
                    "path": {
                        "type": "string",
                        "description": "搜索路径：文件路径或目录路径",
                    },
                    "context_lines": {
                        "type": "integer",
                        "description": "匹配行前后各显示几行，默认 2",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最多返回几处匹配，默认 10",
                    },
                    "ext": {
                        "type": "string",
                        "description": "只搜索指定扩展名（如 html、py、js），留空搜索所有文件",
                    },
                },
                "required": ["keyword", "path"],
            },
        },
    }


def run(args: dict) -> str:
    keyword      = args.get("keyword", "").strip()
    raw_path     = args.get("path", "").strip()
    context      = int(args.get("context_lines", 2))
    max_results  = int(args.get("max_results", 10))
    ext          = args.get("ext", "").strip().lstrip(".")

    if not keyword:
        return "错误：keyword 不能为空"

    path = Path(raw_path).expanduser()
    if not path.exists():
        return f"路径不存在：{path}"

    # 构建 grep 命令
    cmd = ["grep", "-En", "--color=never", f"-C{context}"]

    if path.is_dir():
        cmd += ["-r"]
        if ext:
            cmd += ["--include", f"*.{ext}"]

    cmd += [keyword, str(path)]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15
        )
        output = result.stdout.strip()
        if not output:
            return f"未找到匹配「{keyword}」\n路径：{path}"

        # 截取前 max_results 处匹配（按 -- 分隔块计）
        blocks = output.split("\n--\n")
        if len(blocks) > max_results:
            blocks = blocks[:max_results]
            truncated = True
        else:
            truncated = False

        result_text = f"\n--\n".join(blocks)
        count = output.count("\n") + 1

        summary = f"搜索「{keyword}」于 {path.name}，找到约 {count} 行匹配"
        if truncated:
            summary += f"（仅显示前 {max_results} 处）"
        summary += "：\n\n"

        return summary + result_text

    except subprocess.TimeoutExpired:
        return "搜索超时（15s）"
    except Exception as e:
        return f"搜索失败：{e}"
