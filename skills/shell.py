import subprocess

SKILL = {
    "name": "shell",
    "description": "执行终端 shell 命令",
    "version": "1.0.0",
    "author": "archer-builtin",
}

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
