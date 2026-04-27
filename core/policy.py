"""
Policy Layer (Step 2 / v1.2 Phase 0)

在技能执行前评估风险，返回 ALLOW / CONFIRM / STRONG_CONFIRM / DENY 四种决策。
stateless，所有逻辑纯函数，便于测试。

v1.2 变更：
- file_ops 路径判断改为 resolve+relative_to，杜绝路径遍历/字符串绕过
- shell 增加风险评分：low/medium/high/critical，high 触发 strong_confirm
"""
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Decision(Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"               # 需要用户 y/n 确认
    STRONG_CONFIRM = "strong_confirm" # 高风险：需要输入命令前缀确认
    DENY = "deny"                     # 直接拒绝，不给机会


@dataclass
class PolicyResult:
    decision: Decision
    reason: str = ""
    risk: str = "low"


# ── 路径安全：vault 归属判断 ─────────────────────────────────────────────────────

def is_inside_vault(child: str, vault_path: str) -> bool:
    """使用 resolve+relative_to 判断路径是否在 vault 内，杜绝路径遍历和字符串绕过。"""
    try:
        child_p = Path(child).expanduser().resolve()
        vault_p = Path(vault_path).expanduser().resolve()
        child_p.relative_to(vault_p)
        return True
    except (ValueError, OSError):
        return False


# ── shell 黑名单（critical → DENY）───────────────────────────────────────────────
_SHELL_DENYLIST: list[tuple[re.Pattern, str]] = [
    (re.compile(r"rm\s+.*-[^\s]*r[^\s]*.*\s+/?~", re.I),      "递归删除家目录"),
    (re.compile(r"rm\s+.*-[^\s]*r[^\s]*\s+/\s*$", re.I),      "递归删除根目录"),
    (re.compile(r"rm\s+.*-[^\s]*r[^\s]*\s+/[^a-zA-Z]", re.I), "递归删除根目录路径"),
    (re.compile(r"--no-preserve-root"),                          "--no-preserve-root"),
    (re.compile(r"\bsudo\s+rm\b", re.I),                        "sudo rm"),
    (re.compile(r"\bmkfs\b"),                                    "格式化文件系统"),
    (re.compile(r"\bdd\b.*\bof=/dev/"),                          "写入块设备"),
    (re.compile(r"(curl|wget).*\|\s*(ba)?sh", re.I),            "网络脚本直接执行"),
    (re.compile(r":\(\)\s*\{.*:\|:", re.S),                     "Fork bomb"),
    (re.compile(r">\s*/dev/sd"),                                 "写入块设备"),
    (re.compile(r"\bcrontab\s+-r\b", re.I),                     "清空 crontab"),
]

# ── shell 高风险（high → STRONG_CONFIRM）────────────────────────────────────────
_SHELL_HIGH_RISK: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bsudo\b"),                          "sudo 提权"),
    (re.compile(r"\bchmod\s+-[^\s]*R", re.I),          "递归修改权限"),
    (re.compile(r"\bchown\s+-[^\s]*R", re.I),          "递归修改所有者"),
    (re.compile(r"\bfind\b.*--delete\b", re.I),        "find -delete 批量删除"),
    (re.compile(r"\blaunchctl\b"),                     "launchctl 系统服务"),
    (re.compile(r"\bnohup\b"),                         "后台常驻进程"),
    (re.compile(r"\bosascript\b"),                     "osascript 系统自动化"),
    (re.compile(r"\bdefaults\s+write\b", re.I),        "defaults write 系统设置"),
    (re.compile(r"\bpmset\b"),                         "pmset 电源管理"),
    (re.compile(r"\b(shutdown|reboot|halt|poweroff)\b"), "关机/重启"),
    (re.compile(r"\brm\b.*-[^\s]*r", re.I),            "递归删除"),
    (re.compile(r">\s*~/\.(zshrc|bashrc|bash_profile|gitconfig)", re.I), "写入 shell 配置"),
]


def score_shell_risk(command: str) -> tuple[str, str]:
    """评估 shell 命令风险等级，返回 (risk_level, reason)。
    risk_level: critical / high / medium / low
    """
    for pattern, desc in _SHELL_DENYLIST:
        if pattern.search(command):
            return "critical", desc
    for pattern, desc in _SHELL_HIGH_RISK:
        if pattern.search(command):
            return "high", desc
    if re.search(r"\|\s*(sh|bash|zsh|python|python3|ruby|perl)\b", command, re.I):
        return "medium", "管道到解释器"
    return "low", ""


# ── installer 代码扫描 ─────────────────────────────────────────────────────────
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


def check(skill_name: str, args: dict, skills: dict, cfg: dict | None = None) -> PolicyResult:
    """
    评估此次技能调用的风险，返回 PolicyResult。

    DENY          → 直接阻止，不给用户确认机会。
    STRONG_CONFIRM → 高风险，需要用户输入命令前缀确认。
    CONFIRM       → 暂停，等待用户 y/n。
    ALLOW         → 直接执行。
    """
    mod = skills.get(skill_name)
    meta = getattr(mod, "SKILL", {}) if mod else {}
    risk = meta.get("risk", "low")

    if skill_name == "shell":
        command = args.get("command", "")
        risk_level, reason = score_shell_risk(command)
        if risk_level == "critical":
            return PolicyResult(Decision.DENY, reason=f"安全策略阻止：{reason}", risk="critical")
        if risk_level == "high":
            return PolicyResult(Decision.STRONG_CONFIRM, reason=f"高风险命令：{reason}\n$ {command}", risk="high")
        if risk_level == "medium":
            return PolicyResult(Decision.CONFIRM, reason=f"shell: {command}", risk="medium")
        return PolicyResult(Decision.CONFIRM, reason=f"shell: {command}", risk="low")

    if skill_name in ("obsidian_read", "obsidian_write", "obsidian_search"):
        return PolicyResult(Decision.ALLOW, risk="low")

    if skill_name == "file_ops":
        action = args.get("action", "read")
        if action in ("write", "append"):
            path = args.get("path", "")
            vault_path = (cfg or {}).get("obsidian", {}).get("vault_path", "")
            if vault_path and path and is_inside_vault(path, vault_path):
                return PolicyResult(Decision.ALLOW, risk="low")
            return PolicyResult(
                Decision.CONFIRM,
                reason=f"文件写入 [{action}] → {path or '（未指定路径）'}",
                risk="high",
            )
        return PolicyResult(Decision.ALLOW, risk="low")

    if skill_name == "installer":
        return PolicyResult(Decision.ALLOW, risk="critical")

    if risk in ("high", "critical") and meta.get("requires_confirmation", False):
        return PolicyResult(
            Decision.CONFIRM,
            reason=f"高风险技能 [{skill_name}]",
            risk=risk,
        )

    return PolicyResult(Decision.ALLOW, risk=risk)


def check_shell_command(command: str) -> tuple[bool, str]:
    """向后兼容接口：检查 shell 命令是否命中 critical 黑名单，返回 (allowed, reason)。"""
    risk_level, reason = score_shell_risk(command)
    return risk_level != "critical", reason


def scan_code_for_dangers(code: str) -> list[str]:
    """扫描代码文本，返回命中的危险 API 列表。"""
    return [api for api in _DANGEROUS_APIS if api in code]
