"""
code_edit — 精准代码编辑技能

解决 file_ops 只能整体覆写的问题。
支持三种操作：
  str_replace  — 替换文件中的精确字符串（唯一匹配）
  insert       — 在指定行号后插入多行内容
  delete_lines — 删除指定行号范围

设计参考：Anthropic computer-use / Claude Code 的 str_replace_editor 语义。

配合 code_search + file_ops start_line 使用：
  1. code_search 定位目标代码块
  2. file_ops read start_line=N 确认上下文
  3. code_edit str_replace 精准替换
"""
from pathlib import Path

SKILL = {
    "name": "code_edit",
    "description": "精准修改代码文件：字符串替换、行号插入、行号删除",
    "version": "1.0.0",
    "author": "archer-builtin",
    "risk": "medium",
    "default_timeout": 10,
}


def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "code_edit",
            "description": (
                "精准修改代码文件，不需要整体重写。"
                "action=str_replace：把文件中的 old_str 替换为 new_str，old_str 必须在文件中唯一出现；"
                "action=insert：在 insert_line 行后插入 new_str（支持多行）；"
                "action=delete_lines：删除 start_line 到 end_line 之间的行（含两端）。"
                "使用前先用 file_ops read 或 code_search 确认目标内容，避免替换错误。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径，支持绝对路径和 ~ 开头的路径",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["str_replace", "insert", "delete_lines"],
                        "description": "操作类型：str_replace / insert / delete_lines",
                    },
                    "old_str": {
                        "type": "string",
                        "description": "（action=str_replace 必填）要替换的原始字符串，必须在文件中唯一出现",
                    },
                    "new_str": {
                        "type": "string",
                        "description": "（action=str_replace/insert 必填）替换后的字符串或插入的内容，支持多行",
                    },
                    "insert_line": {
                        "type": "integer",
                        "description": "（action=insert 必填）在此行号之后插入，行号从 1 开始；0 表示插入到文件最顶部",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "（action=delete_lines 必填）删除起始行号（含），从 1 开始",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "（action=delete_lines 必填）删除结束行号（含），从 1 开始",
                    },
                },
                "required": ["path", "action"],
            },
        },
    }


def run(args: dict) -> str:
    raw_path = args.get("path", "").strip()
    action = args.get("action", "")
    path = Path(raw_path).expanduser()

    if not path.exists():
        return f"文件不存在：{path}"
    if path.is_dir():
        return f"{path} 是目录，无法编辑"

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return f"读取失败：{e}"

    # ── str_replace ──────────────────────────────────────────────────────────
    if action == "str_replace":
        old_str = args.get("old_str", "")
        new_str = args.get("new_str", "")
        if not old_str:
            return "错误：str_replace 需要提供 old_str"

        count = text.count(old_str)
        if count == 0:
            # 给出附近上下文提示
            return (
                f"错误：在 {path.name} 中未找到 old_str。\n"
                f"提示：先用 code_search 或 file_ops read 确认原始文本，注意空格/缩进/换行是否完全匹配。\n"
                f"old_str 首50字符：{repr(old_str[:50])}"
            )
        if count > 1:
            return (
                f"错误：old_str 在文件中出现了 {count} 次（必须唯一）。\n"
                f"请在 old_str 中包含更多上下文以唯一定位目标位置。\n"
                f"old_str 首50字符：{repr(old_str[:50])}"
            )

        new_text = text.replace(old_str, new_str, 1)
        try:
            path.write_text(new_text, encoding="utf-8")
        except Exception as e:
            return f"写入失败：{e}"

        # 统计变化
        old_lines = old_str.count("\n") + 1
        new_lines = new_str.count("\n") + 1
        delta = new_lines - old_lines
        sign = f"+{delta}" if delta >= 0 else str(delta)
        return (
            f"已替换：{path.name}\n"
            f"  原：{old_lines} 行 → 新：{new_lines} 行（{sign} 行）"
        )

    # ── insert ───────────────────────────────────────────────────────────────
    if action == "insert":
        new_str = args.get("new_str", "")
        insert_line = int(args.get("insert_line", 0))
        if not new_str:
            return "错误：insert 需要提供 new_str"

        lines = text.split("\n")
        total = len(lines)

        if insert_line < 0 or insert_line > total:
            return f"错误：insert_line={insert_line} 超出范围（文件共 {total} 行）"

        insert_lines = new_str.split("\n")
        # 在 insert_line 后插入（0 表示顶部）
        new_lines = lines[:insert_line] + insert_lines + lines[insert_line:]
        new_text = "\n".join(new_lines)

        try:
            path.write_text(new_text, encoding="utf-8")
        except Exception as e:
            return f"写入失败：{e}"

        return (
            f"已插入：{path.name}\n"
            f"  在第 {insert_line} 行后插入了 {len(insert_lines)} 行\n"
            f"  文件行数：{total} → {len(new_lines)}"
        )

    # ── delete_lines ─────────────────────────────────────────────────────────
    if action == "delete_lines":
        start = int(args.get("start_line", 0))
        end = int(args.get("end_line", 0))

        if not start or not end:
            return "错误：delete_lines 需要 start_line 和 end_line"

        lines = text.split("\n")
        total = len(lines)

        if start < 1 or end > total or start > end:
            return (
                f"错误：行号范围 {start}-{end} 无效（文件共 {total} 行）"
            )

        deleted_count = end - start + 1
        new_lines = lines[:start - 1] + lines[end:]
        new_text = "\n".join(new_lines)

        try:
            path.write_text(new_text, encoding="utf-8")
        except Exception as e:
            return f"写入失败：{e}"

        return (
            f"已删除：{path.name}\n"
            f"  删除第 {start}～{end} 行，共 {deleted_count} 行\n"
            f"  文件行数：{total} → {len(new_lines)}"
        )

    return f"未知操作：{action}，可用：str_replace / insert / delete_lines"
