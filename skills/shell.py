import re
import subprocess

SKILL = {
    "name": "shell",
    "description": "执行终端 shell 命令",
    "version": "1.2.0",
    "author": "archer-builtin",
    "risk": "high",
    "requires_confirmation": True,
    "default_timeout": 30,
}

_DANGEROUS = [
    r"rm\s+-rf\s+[/~]",
    r"sudo\s+",
    r"chmod\s+[0-7]*7[0-7]*\s+/",
    r">\s*/dev/sd",
    r"mkfs",
    r"dd\s+if=",
    r"shutdown",
    r"reboot",
    r"halt",
    r"curl\s+.+\|\s*(ba)?sh",
    r"wget\s+.+\|\s*(ba)?sh",
    r":\(\)\{.*\}",  # fork bomb
]

def _is_dangerous(cmd: str) -> bool:
    return any(re.search(p, cmd, re.IGNORECASE) for p in _DANGEROUS)

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "shell",
            "description": "在本地终端执行 shell 命令，返回输出结果。用于查看文件、运行脚本、系统操作等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的 shell 命令",
                    }
                },
                "required": ["command"],
            },
        },
    }

def run(args: dict) -> str:
    cmd = args.get("command", "").strip()
    if not cmd:
        return "错误：命令为空"

    if _is_dangerous(cmd):
        return f"[拒绝] 检测到高风险命令，已阻止：{cmd}\n如需执行请直接在终端运行。"

    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30
        )
        output = (result.stdout + result.stderr).strip()
        return output or "(无输出)"
    except subprocess.TimeoutExpired:
        return "错误：命令超时（30s）"
    except Exception as e:
        return f"错误：{e}"
