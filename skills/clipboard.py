"""
剪贴板读写技能（macOS）。
"""
import subprocess
from pathlib import Path

SKILL = {
    "name": "clipboard",
    "description": "读取或写入 macOS 剪贴板内容",
    "version": "1.0.0",
    "author": "archer-builtin",
}


def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "clipboard",
            "description": (
                "读取当前剪贴板文字内容，或将文字写入剪贴板。"
                "action=read 返回当前剪贴板内容；action=write 将 text 写入剪贴板。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["read", "write"],
                        "description": "read 读取 / write 写入",
                    },
                    "text": {
                        "type": "string",
                        "description": "写入剪贴板的内容（action=write 时必填）",
                    },
                },
                "required": ["action"],
            },
        },
    }


def _run_impl(action: str, text: str = "") -> str:
    if action == "read":
        result = subprocess.run(["pbpaste"], capture_output=True, text=True)
        content = result.stdout
        if not content:
            return "（剪贴板为空）"
        preview = content[:200]
        suffix = f"\n…（共 {len(content)} 字符）" if len(content) > 200 else ""
        return preview + suffix

    if action == "write":
        if not text:
            return "text 不能为空"
        subprocess.run(["pbcopy"], input=text.encode(), check=True)
        return f"已写入剪贴板（{len(text)} 字符）"

    return f"未知 action：{action}（支持 read / write）"


def run(action: str, text: str = "") -> str:
    try:
        return _run_impl(action, text)
    except Exception as e:
        return f"剪贴板操作失败：{type(e).__name__}: {e}"
