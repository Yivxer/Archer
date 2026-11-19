"""
run_shell → shell 的别名技能。
DeepSeek 有时把 shell 技能叫成 run_shell，这里做透明转发，避免报错打断工具链。

SKILL 使用字面量，供 loader 在不导入模块的情况下注册；
run / schema 再转发到 shell。策略层按 shell 的命令分级处理这个别名。
"""
from skills.shell import run as _shell_run
from skills.shell import schema as _schema_orig

SKILL = {
    "name": "run_shell",
    "description": "执行终端 shell 命令（shell 的兼容别名）",
    "version": "1.2.0",
    "author": "archer-builtin",
    "risk": "high",
    "requires_confirmation": True,
    "default_timeout": 30,
}


def run(args: dict) -> str:
    return _shell_run(args)


def schema() -> dict:
    copied = _schema_orig()
    copied["function"]["name"] = "run_shell"
    copied["function"]["description"] = (
        "shell 技能的别名。执行终端命令，返回输出。"
        "推荐直接使用 shell 技能；此别名保留以兼容旧调用。"
    )
    return copied
