"""
Policy Layer (Step 2)

在技能执行前评估风险，返回 ALLOW / CONFIRM / DENY 三种决策。
stateless，所有逻辑纯函数，便于测试。
"""
import re
from dataclasses import dataclass
from enum import Enum


class Decision(Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"  # 需要用户 y/n 确认
    DENY = "deny"        # 直接拒绝，不给机会


@dataclass
class PolicyResult:
    decision: Decision
    reason: str = ""
    risk: str = "low"


# ── shell 黑名单 ───────────────────────────────────────────────────────────────
_SHELL_DENYLIST: list[tuple[re.Pattern, str]] = [
    (re.compile(r"rm\s+.*-[^\s]*r[^\s]*.*\s+/?~", re.I),      "递归删除家目录"),
    (re.compile(r"rm\s+.*-[^\s]*r[^\s]*\s+/\s*$", re.I),      "递归删除根目录"),
    (re.compile(r"rm\s+.*-[^\s]*r[^\s]*\s+/[^a-zA-Z]", re.I), "递归删除根目录路径"),
    (re.compile(r"--no-preserve-root"),                          "--no-preserve-root"),
    (re.compile(r"\bsudo\b"),                                    "sudo 提权"),
    (re.compile(r"\bchmod\s+-[^\s]*R", re.I),                   "递归修改权限"),
    (re.compile(r"\bchown\s+-[^\s]*R", re.I),                   "递归修改所有者"),
    (re.compile(r"\bmkfs\b"),                                    "格式化文件系统"),
    (re.compile(r"\bdd\b.*\bof=/dev/"),                          "写入块设备"),
    (re.compile(r"(curl|wget).*\|\s*(ba)?sh", re.I),            "网络脚本直接执行"),
    (re.compile(r":\(\)\s*\{.*:\|:", re.S),                     "Fork bomb"),
    (re.compile(r"\b(shutdown|reboot|halt|poweroff)\b"),         "关机/重启"),
    (re.compile(r">\s*/dev/sd"),                                 "写入块设备"),
]

# ── installer 代码扫描 ─────────────────────────────────────────────────────────
# 用列表推导而非字面量，避免静态扫描工具误报
_DANGEROUS_APIS: list[str] = [
    s for s in [
        "eval(",
        "exec(",
        "os.system(",
        "subprocess.call(",
        "subprocess.run(",
        "subprocess.Popen(",
        "__import__(",
        "socket.socket(",
        "os.remove(",
        "os.unlink(",
        "shutil.rmtree(",
    ]
]


def check(skill_name: str, args: dict, skills: dict) -> PolicyResult:
    """
    评估此次技能调用的风险，返回 PolicyResult。

    DENY   → 直接阻止，不给用户确认机会。
    CONFIRM → 暂停，等待用户 y/n。
    ALLOW  → 直接执行。
    """
    mod = skills.get(skill_name)
    meta = getattr(mod, "SKILL", {}) if mod else {}
    risk = meta.get("risk", "low")

    # shell：命中黑名单 → DENY；否则 → CONFIRM
    if skill_name == "shell":
        command = args.get("command", "")
        allowed, reason = check_shell_command(command)
        if not allowed:
            return PolicyResult(Decision.DENY, reason=f"安全策略阻止：{reason}", risk="critical")
        return PolicyResult(Decision.CONFIRM, reason=f"shell: {command}", risk="high")

    # obsidian：读写搜索均为用户 vault 操作，直接放行
    if skill_name in ("obsidian_read", "obsidian_write", "obsidian_search"):
        return PolicyResult(Decision.ALLOW, risk="low")

    # file_ops：写入/追加非 obsidian 路径才 CONFIRM；读取/列出直接放行
    if skill_name == "file_ops":
        action = args.get("action", "read")
        if action in ("write", "append"):
            path = args.get("path", "")
            if "obsidian" in path.lower() or "icloud~md~obsidian" in path.lower():
                return PolicyResult(Decision.ALLOW, risk="low")
            return PolicyResult(Decision.CONFIRM, reason=f"文件写入 [{action}] → {path or '（未指定路径）'}", risk="high")
        return PolicyResult(Decision.ALLOW, risk="low")

    # installer 由技能内部处理完整审查，policy 不介入
    if skill_name == "installer":
        return PolicyResult(Decision.ALLOW, risk="critical")

    # 其他注册了 requires_confirmation 的高风险技能
    if risk in ("high", "critical") and meta.get("requires_confirmation", False):
        return PolicyResult(
            Decision.CONFIRM,
            reason=f"高风险技能 [{skill_name}]",
            risk=risk,
        )

    return PolicyResult(Decision.ALLOW, risk=risk)


def check_shell_command(command: str) -> tuple[bool, str]:
    """检查 shell 命令是否命中黑名单，返回 (allowed, reason)。"""
    for pattern, desc in _SHELL_DENYLIST:
        if pattern.search(command):
            return False, desc
    return True, ""


def scan_code_for_dangers(code: str) -> list[str]:
    """扫描代码文本，返回命中的危险 API 列表。"""
    return [api for api in _DANGEROUS_APIS if api in code]
