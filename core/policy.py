"""
Policy Layer (Step 2 / v1.2 Phase 0)

在技能执行前评估风险，返回 ALLOW / CONFIRM / STRONG_CONFIRM / DENY 四种决策。
stateless，所有逻辑纯函数，便于测试。

v1.2 变更：
- file_ops 路径判断改为 resolve+relative_to，杜绝路径遍历/字符串绕过
- shell 增加风险评分：low/medium/high/critical，high 触发 strong_confirm

v1.5 P0-S1 变更：
- is_inside_vault() 使用 os.path.realpath() 防止符号链接攻击
- is_sensitive_path() 检查 resolved path，检测 vault 内文件指向敏感路径的情况

v1.5 P0-S2 变更：
- score_shell_risk() 增加 _normalize_shell_command() 和 _detect_bypass()
- 防御 ANSI-C 引用（$'...'）、${IFS}、$() 等绕过手法

v1.5 P0-S3 变更：
- scan_code_for_dangers() 增加 AST 分析和编码绕过检测
"""
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse


from core.policy_code_scan import (  # Compatibility exports for existing callers.
    _DANGEROUS_APIS,
    _DANGEROUS_APIS_SET,
    _DANGEROUS_FUNCTIONS,
    _decode_escape_sequences,
    _get_attr_prefix,
    _get_call_name,
    _get_string_arg,
    _scan_ast,
    _scan_string,
    scan_code_for_dangers,
)


def _safe_realpath(path: str) -> str | None:
    """
    安全获取真实路径。
    - 展开 ~（os.path.realpath 本身不展开 ~）
    - 跟随所有符号链接到最终真实路径
    - 失败返回 None
    """
    try:
        expanded = os.path.expanduser(path)
        return os.path.realpath(expanded)
    except (OSError, ValueError):
        return None


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
    """
    判断 child 是否在 vault 内，防止符号链接攻击。

    防御逻辑：
    - 使用 os.path.realpath() 完全跟随符号链接链到真实路径
    - 检查 child 的真实路径是否以 vault 的真实路径为前缀
    - 即使 vault 本身是符号链接也能正确处理

    攻击场景示例：
    - vault/symlink -> /etc/passwd → 检测为 vault 外（安全）
    - vault/symlink -> symlink2 -> /etc/passwd → 检测为 vault 外（安全）
    """
    child_real = _safe_realpath(child)
    vault_real = _safe_realpath(vault_path)

    if child_real is None or vault_real is None:
        return False

    # 使用路径前缀检查，兼容 vault 是符号链接的场景
    return child_real.startswith(vault_real + os.sep) or child_real == vault_real


def is_sensitive_path(path: str) -> bool:
    """
    判断路径是否可能包含密钥、token 或本地身份凭证。

    检查点：
    - 路径组件中是否含敏感目录名（.ssh/.gnupg/.aws/.kube）
    - 文件名是否是敏感文件（.env/id_rsa/credentials 等）
    - 文件后缀是否是敏感扩展名（.pem/.key/.p12/.pfx）
    - 特别注意：检查 resolved path，检测 vault 内文件指向敏感路径的情况

    攻击场景示例：
    - vault/evil -> ~/.ssh/id_rsa → resolved path 包含 .ssh → 检测为敏感（安全）
    """
    if not path:
        return False

    # 获取 resolved path（跟随符号链接）
    resolved = _safe_realpath(path) or path
    p = Path(resolved).expanduser()  # resolved 已是绝对路径，直接用
    parts = {part.lower() for part in p.parts}
    name = p.name.lower()
    sensitive_dirs = {".ssh", ".gnupg", ".aws", ".kube"}
    sensitive_files = {
        ".env",
        ".netrc",
        "archer.toml",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "credentials",
    }
    return (
        bool(parts & sensitive_dirs)
        or name in sensitive_files
        or name.startswith(".env.")
        or name.endswith((".pem", ".key", ".p12", ".pfx"))
    )


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
    (re.compile(r"\bchmod\s+[0-7]*7[0-7]*\s+/", re.I), "开放根路径权限"),
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

# ── shell 中风险（medium → CONFIRM）────────────────────────────────────────────
_SHELL_MEDIUM_RISK: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(^|[^\d])>>?\s*(?!/dev/null\b)"), "输出重定向写入"),
    (re.compile(r"\btee\s+(-a\s+)?(?!/dev/null\b)", re.I), "tee 写入文件"),
    (re.compile(r"\b(touch|mkdir|cp|mv|rm|ln)\b", re.I), "文件系统变更"),
    (re.compile(r"\b(sed|perl)\b.*\s-i(\b|[.])", re.I), "原地修改文件"),
    (re.compile(r"\b(git\s+(commit|push|reset|clean|rebase|merge)|gh\s+pr\s+merge)\b", re.I), "版本库变更"),
    (re.compile(r"\b(npm|pnpm|yarn|bun)\s+(install|add|remove|update)\b", re.I), "依赖变更"),
    (re.compile(r"\b(pip|pip3)\s+install\b|\bpython3?\s+-m\s+pip\s+install\b", re.I), "Python 依赖变更"),
]


def _normalize_shell_command(command: str) -> str:
    """
    展开 shell 常见绕过编码，降低正则被绕过的风险。
    返回归一化后的命令字符串，用于后续正则匹配。

    处理的绕过手法：
    - $'...'  ANSI-C 引用（含 \\t \\n \\xHH 等）
    - ${IFS}   bash 内部字段分隔符（用空格代替）
    - $VAR     最简单的变量替换（删除变量名，保留 $ 后内容）
    - 多余空白/制表符折叠为单个空格

    注意：不展开真正的环境变量值（做不到，也不需要），
    这里只做「让绕过难度变大」的归一化，不是完整 shell parse。
    """
    import shlex
    normalized = command

    # 1. 展开 $'...' ANSI-C 引用
    #    $'\\t' -> 制表符, $'\\n' -> 换行, $'\\x72' -> 'r'
    def _expand_ansi_c(m: re.Match) -> str:
        try:
            # m.group(0) 是 $'...' 整个字符串
            # 用 shlex.quote 的反向思路：eval 不安全，用 encode/decode
            content = m.group(1)
            # 处理 \xHH
            content = re.sub(
                r"\\x([0-9a-fA-F]{2})",
                lambda x: chr(int(x.group(1), 16)),
                content,
            )
            # 处理 \n \t \r \\ \'
            content = (
                content.replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace("\\r", "\r")
                .replace("\\\\", "\\")
                .replace("\\'", "'")
            )
            return content
        except Exception:
            return m.group(0)  # 展开失败，保留原样

    # 反复展开，处理嵌套/多次
    prev = ""
    while prev != normalized:
        prev = normalized
        normalized = re.sub(r"\$\'([^\']*)\'", _expand_ansi_c, normalized)

    # 2. ${IFS} 替换为空格（bash 绕过常用）
    normalized = re.sub(r"\$\{IFS\}", " ", normalized, flags=re.I)
    normalized = re.sub(r"\$IFS\b", " ", normalized, flags=re.I)

    # 3. 简单变量引用 ${...} 替换为空（不让变量名干扰正则）
    #    只处理没有明显恶意拼接的情况
    normalized = re.sub(r"\$\{[a-zA-Z_][a-zA-Z0-9_]*\}", "", normalized)

    # 4. 折叠连续空白为单个空格，去除首尾空白
    normalized = re.sub(r"\s+", " ", normalized).strip()

    return normalized


def _detect_bypass(command: str) -> str | None:
    """
    检测已知的 shell 绕过手法，命中即返回原因字符串。
    不归一化，直接检测原始命令中的绕过特征。
    """
    # ANSI-C 引用 $'...' —— 常见于绕过空格检测
    if re.search(r"\$\'", command):
        return "疑似使用 ANSI-C 引用绕过（$'...'）"

    # ${IFS} 或 $IFS —— bash 环境变量绕过空格
    if re.search(r"\$IFS\b|\$\{IFS\}", command, re.I):
        return "疑似使用 $IFS 绕过空格检测"

    # 命令交替 $(...) 或反引号 ``` —— 隐藏真实命令
    if re.search(r"\$\(|`[^`]+`", command):
        return "疑似使用命令替换 $(...) 或反引号隐藏命令"

    # 进程替换 <(...) —— 绕过管道检测
    if re.search(r"<\(", command):
        return "疑似使用进程替换 <(...) 绕过"

    # here string <<< —— 绕过管道检测
    if re.search(r"<<<", command):
        return "疑似使用 here-string <<< 绕过"

    # eval 包裹 —— 延迟执行绕过静态检测
    if re.search(r"\beval\b\s*[(\"\'|$|`]|\beval\b\s+[a-zA-Z_]", command):
        return "使用 eval 包裹命令（绕过静态检测）"

    return None


def score_shell_risk(command: str) -> tuple[str, str]:
    """评估 shell 命令风险等级，返回 (risk_level, reason)。
    risk_level: critical / high / medium / low
    """
    # 先检测绕过手法，命中则至少 medium
    bypass_reason = _detect_bypass(command)
    if bypass_reason:
        # 绕过手法本身算 high（需要用户强确认）
        return "high", bypass_reason

    # 归一化后再做正则匹配，降低绕过概率
    normalized = _normalize_shell_command(command)

    for pattern, desc in _SHELL_DENYLIST:
        if pattern.search(normalized):
            return "critical", desc
    for pattern, desc in _SHELL_HIGH_RISK:
        if pattern.search(normalized):
            return "high", desc
    for pattern, desc in _SHELL_MEDIUM_RISK:
        if pattern.search(normalized):
            return "medium", desc
    if re.search(r"\|\s*(sh|bash|zsh|python|python3|ruby|perl)\b", normalized, re.I):
        return "medium", "管道到解释器"
    return "low", ""


def check(skill_name: str, args: dict, skills: Mapping[str, object], cfg: dict | None = None) -> PolicyResult:
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

    if meta.get("version") == "mcp":
        server = meta.get("mcp_server", "")
        tool_name = meta.get("mcp_tool", "")
        if (not server or not tool_name) and "__" in skill_name:
            server, tool_name = skill_name.split("__", 1)
        if server and tool_name:
            return check_mcp_tool(server, tool_name, args, cfg=cfg)
        return PolicyResult(
            Decision.CONFIRM,
            reason=f"MCP 工具元数据不完整：{skill_name}",
            risk="medium",
        )

    if skill_name == "shell":
        command = args.get("command", "")
        risk_level, reason = score_shell_risk(command)
        if risk_level == "critical":
            return PolicyResult(Decision.DENY, reason=f"安全策略阻止：{reason}", risk="critical")
        if risk_level == "high":
            return PolicyResult(Decision.STRONG_CONFIRM, reason=f"高风险命令：{reason}\n$ {command}", risk="high")
        if risk_level == "medium":
            return PolicyResult(Decision.CONFIRM, reason=f"shell: {command}", risk="medium")
        return PolicyResult(Decision.ALLOW, reason=f"shell: {command}", risk="low")

    if skill_name in ("obsidian_read", "obsidian_search"):
        return PolicyResult(Decision.ALLOW, risk="low")

    if skill_name == "obsidian_write":
        path = args.get("path", "") or args.get("target", "")
        # 低风险路径白名单：Archer 项目相关的笔记目录自动放行
        low_risk_prefixes = [
            "50计划清单📌/Archer/",
            "Archer/",
        ]
        is_low_risk = any(
            path.startswith(prefix) or f"/{prefix}" in path
            for prefix in low_risk_prefixes
        )
        if is_low_risk:
            return PolicyResult(Decision.ALLOW, risk="low")
        return PolicyResult(
            Decision.CONFIRM,
            reason=f"写入 Obsidian → {path or '（未指定路径）'}",
            risk="medium",
        )

    if skill_name == "hugo_blog":
        action = str(args.get("action", "")).strip().lower()
        if action in {"list", "read", "doctor"}:
            return PolicyResult(Decision.ALLOW, risk="low")
        return PolicyResult(
            Decision.CONFIRM,
            reason=f"博客副作用 [{action or '未指定动作'}] 需要用户确认",
            risk="medium",
        )

    if skill_name == "file_ops":
        action = args.get("action", "read")
        path = args.get("path", "")
        if is_sensitive_path(path):
            return PolicyResult(
                Decision.CONFIRM,
                reason=f"敏感路径访问 [{action}] → {path or '（未指定路径）'}",
                risk="high",
            )
        if action in ("write", "append"):
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
        # installer 由技能内部自主执行（下载→静态扫描→安装），
        # 不弹工具批准卡片，让 Archer 像 agent 一样直接规划并完成安装。
        return PolicyResult(Decision.ALLOW, risk="critical")

    if skill_name == "github_ops" and args.get("action") == "run":
        return PolicyResult(
            Decision.STRONG_CONFIRM,
            reason=f"GitHub 任意子命令需要强确认：gh {args.get('command', '')}",
            risk="high",
        )

    if risk in ("high", "critical") and meta.get("requires_confirmation", False):
        return PolicyResult(
            Decision.CONFIRM,
            reason=f"高风险技能 [{skill_name}]",
            risk=risk,
        )

    return PolicyResult(Decision.ALLOW, risk=risk)


# ── P5.4: 子任务工具隔离 ───────────────────────────────────────────────────────

SUBTASK_ALLOW_LIST = frozenset({
    "web_search",
    "web_fetch",
    "file_ops",
    "file_search",
    "obsidian_read",
    "obsidian_search",
    "code_search",
    "pdf_reader",
    "rss_reader",
    "weather",
})

SUBTASK_DENY_LIST = frozenset({
    "shell",
    "run_shell",
    "github_ops",
    "obsidian_write",
    "hugo_blog",
    "npm_run",
    "code_edit",
    "installer",
    "browser_automation",
    "image_generator",
    "workflow_automation",
    "memory_save",
    "process_manager",
    "frontend_dev",
    "market_research",
    "video_script",
    "code_review",
    "soul_evolution",
    "weekly_review",
    "humanizer",
    "summarize",
})


def check_subtask(
    skill_name: str,
    args: dict | None = None,
    skills: dict | None = None,
    cfg: dict | None = None,
) -> PolicyResult:
    """Policy gate for isolated subtasks: allow-list + deny side effects."""
    args = args or {}
    if skill_name in SUBTASK_DENY_LIST:
        return PolicyResult(
            Decision.DENY,
            reason=f"子任务隔离：禁用 {skill_name}",
            risk="high",
        )
    if skill_name not in SUBTASK_ALLOW_LIST:
        return PolicyResult(
            Decision.DENY,
            reason=f"子任务隔离：未授权 {skill_name}",
            risk="medium",
        )
    if skill_name == "file_ops" and args.get("action") in ("write", "append"):
        return PolicyResult(
            Decision.DENY,
            reason="子任务隔离：禁止 file_ops 写入",
            risk="high",
        )
    return check(skill_name, args, skills or {}, cfg=cfg)


def check_shell_command(command: str) -> tuple[bool, str]:
    """向后兼容接口：检查 shell 命令是否命中 critical 黑名单，返回 (allowed, reason)。"""
    risk_level, reason = score_shell_risk(command)
    return risk_level != "critical", reason


# ── MCP 工具安全检查 ──────────────────────────────────────────────────────────

# MCP 服务器黑名单：已知高风险服务器
_MCP_SERVER_DENYLIST: set[str] = {
    "archer-local-shell",
    "archer-unsafe-eval",
}

# MCP 工具名黑名单：高危工具（直接拒绝）
_MCP_TOOL_DENYLIST: set[str] = {
    "run_shell",
    "execute_command",
    "shell_exec",
    "bash",
    "run_python",
    "eval_code",
    "write_file",
    "delete_file",
    "read_sensitive",
}

# MCP 工具名关键词：需要额外检查
_MCP_TOOL_KEYWORDS_ALERT: dict[str, str] = {
    "file":    "疑似文件操作",
    "path":    "疑似路径访问",
    "read":    "疑似文件读取",
    "write":   "疑似文件写入",
    "delete":  "疑似文件删除",
    "shell":   "疑似 shell 执行",
    "exec":    "疑似命令执行",
    "run":     "疑似命令执行",
    "cmd":     "疑似命令执行",
    "command": "疑似命令执行",
    "ssh":     "疑似远程连接",
    "http":    "疑似网络请求",
    "fetch":   "疑似网络请求",
    "download": "疑似网络下载",
    "upload":  "疑似网络上传",
    "sensitive": "疑似敏感信息访问",
    "secret":  "疑似密钥访问",
    "credential": "疑似凭证访问",
    "env":     "疑似环境变量访问",
}


def _iter_mcp_arg_fields(value, path: tuple[str, ...] = ()):
    """递归展开 MCP 参数，返回叶子字段名、字段路径和值。"""
    if isinstance(value, dict):
        for key, child in value.items():
            key_str = str(key)
            yield from _iter_mcp_arg_fields(child, (*path, key_str))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            yield from _iter_mcp_arg_fields(child, (*path, str(idx)))
    else:
        field = path[-1] if path else ""
        yield field, ".".join(path), value


def _mcp_server_permission(cfg: dict, server: str, tool_name: str):
    """Resolve an explicit server/tool grant from Archer config."""
    mcp_cfg = cfg.get("mcp") if isinstance(cfg, dict) else None
    if not isinstance(mcp_cfg, dict) or mcp_cfg.get("enabled") is not True:
        return None, [], "MCP 未启用"
    servers = mcp_cfg.get("servers")
    if not isinstance(servers, list):
        return None, [], f"MCP server {server!r} 未配置"
    server_cfg = next(
        (item for item in servers if isinstance(item, dict) and item.get("name") == server),
        None,
    )
    if server_cfg is None:
        return None, [], f"MCP server {server!r} 未配置"
    if server_cfg.get("enabled") is not True:
        return None, [], f"MCP server {server!r} 未启用"
    permissions = server_cfg.get("permissions")
    permissions = permissions if isinstance(permissions, dict) else {}
    tools = permissions.get("tools")
    tools = tools if isinstance(tools, dict) else {}
    level = str(tools.get(tool_name, "")).strip().lower()
    if level not in {"read", "write"}:
        return None, [], f"MCP 工具 {server}__{tool_name} 未授权"
    domains = permissions.get("allowed_domains")
    domains = domains if isinstance(domains, list) else []
    return level, [str(item).strip().lower().rstrip(".") for item in domains], ""


def _mcp_url_hosts(arg_fields) -> list[tuple[str, str]]:
    hosts: list[tuple[str, str]] = []
    for _field, field_path, value in arg_fields:
        if not isinstance(value, str):
            continue
        try:
            parsed = urlparse(value.strip())
        except ValueError:
            hosts.append((field_path, ""))
            continue
        if parsed.scheme in {"http", "https"}:
            hosts.append((field_path, parsed.hostname or ""))
    return hosts


def check_mcp_tool(
    server: str,
    tool_name: str,
    tool_args: dict | None = None,
    cfg: dict | None = None,
) -> PolicyResult:
    """
    检查 MCP 工具调用的安全性，返回 PolicyResult。

    生产配置采用拒绝优先：server 必须显式启用，工具必须声明 read/write，
    HTTP(S) 参数必须命中域名白名单。之后继续执行黑名单、敏感路径与
    shell 风险检查；write 能力始终要求用户确认。

    cfg=None 仅保留给旧的独立策略调用；生产入口始终传入完整配置。
    """
    fn_name = f"{server}__{tool_name}"

    configured_level = None
    allowed_domains: list[str] = []
    if cfg is not None:
        configured_level, allowed_domains, config_error = _mcp_server_permission(
            cfg, server, tool_name
        )
        if config_error:
            return PolicyResult(Decision.DENY, reason=config_error, risk="high")

    # 1. 服务器黑名单检查
    if server in _MCP_SERVER_DENYLIST:
        return PolicyResult(
            Decision.DENY,
            reason=f"MCP 服务器 {server!r} 在黑名单中",
            risk="critical",
        )

    # 2. 工具名黑名单检查
    if tool_name in _MCP_TOOL_DENYLIST:
        return PolicyResult(
            Decision.DENY,
            reason=f"MCP 工具 {fn_name!r} 在黑名单中（高危工具）",
            risk="critical",
        )

    # 3. 工具名关键词扫描
    alert_reason = None
    for keyword, desc in _MCP_TOOL_KEYWORDS_ALERT.items():
        if keyword in tool_name.lower():
            alert_reason = desc
            break

    args = tool_args or {}

    arg_fields = list(_iter_mcp_arg_fields(args))

    if configured_level is not None:
        from core.mcp import _domain_allowed

        for field_path, host in _mcp_url_hosts(arg_fields):
            if not _domain_allowed(host, allowed_domains):
                return PolicyResult(
                    Decision.DENY,
                    reason=f"MCP {fn_name} 的域名未授权 [{field_path}] → {host or '(invalid)'}",
                    risk="high",
                )

    # 4. 路径参数敏感检查
    path_fields = ["path", "file", "filepath", "file_path", "url", "uri", "target"]
    for field, field_path, path_val in arg_fields:
        if field not in path_fields or not isinstance(path_val, str):
            continue
        # 敏感路径检查
        if is_sensitive_path(path_val):
            return PolicyResult(
                Decision.CONFIRM,
                reason=f"MCP {fn_name} 访问敏感路径 [{field_path}] → {path_val}",
                risk="high",
            )
        # vault 外文件操作检查
        vault_path = (cfg or {}).get("obsidian", {}).get("vault_path", "")
        if vault_path and not is_inside_vault(path_val, vault_path):
            # 允许 vault 外路径（标准文件操作），但如果有关键词则降级
            if alert_reason:
                return PolicyResult(
                    Decision.CONFIRM,
                    reason=f"MCP {fn_name} {alert_reason}（vault 外路径）→ {path_val}",
                    risk="medium",
                )

    # 5. shell 命令参数检查
    cmd_fields = ["command", "cmd", "shell", "code", "script", "expr", "expression"]
    for field, field_path, cmd_val in arg_fields:
        if field not in cmd_fields or not isinstance(cmd_val, str):
            continue
        risk_level, reason = score_shell_risk(cmd_val)
        if risk_level == "critical":
            return PolicyResult(
                Decision.DENY,
                reason=f"MCP {fn_name} 包含危险命令 [{field_path}]：{reason}",
                risk="critical",
            )
        if risk_level == "high":
            return PolicyResult(
                Decision.STRONG_CONFIRM,
                reason=f"MCP {fn_name} 高风险命令 [{field_path}]：{reason}",
                risk="high",
            )
        if risk_level == "medium":
            return PolicyResult(
                Decision.CONFIRM,
                reason=f"MCP {fn_name} 中风险 [{field_path}]：{reason}",
                risk="medium",
            )

    if configured_level == "write":
        return PolicyResult(
            Decision.CONFIRM,
            reason=f"MCP {fn_name} 具有写入能力，需要显式确认",
            risk="medium",
        )

    if configured_level == "read":
        return PolicyResult(
            Decision.ALLOW,
            reason=f"MCP {fn_name} 已获只读授权",
            risk="low",
        )

    # 6. 有关键词但无具体危险 → medium CONFIRM
    if alert_reason:
        return PolicyResult(
            Decision.CONFIRM,
            reason=f"MCP {fn_name} {alert_reason}",
            risk="medium",
        )

    # 默认：MCP 工具默认 medium
    return PolicyResult(
        Decision.ALLOW,
        reason=f"MCP {fn_name}",
        risk="medium",
    )
