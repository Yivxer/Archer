"""
run_shell → shell 的别名技能。
DeepSeek 有时把 shell 技能叫成 run_shell，这里做透明转发，避免报错打断工具链。
"""
from skills.shell import run, SKILL as _S, schema as _schema_orig

SKILL = {**_S, "name": "run_shell"}


def schema() -> dict:
    s = _schema_orig()
    s["function"]["name"] = "run_shell"
    s["function"]["description"] = (
        "shell 技能的别名。执行终端命令，返回输出。"
        "推荐直接使用 shell 技能；此别名保留以兼容旧调用。"
    )
    return s
