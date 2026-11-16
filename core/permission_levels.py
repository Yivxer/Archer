from __future__ import annotations

from typing import Literal

PermissionLevel = Literal["read-only", "write-local", "write-vault", "deploy-remote", "unknown"]
_KNOWN_LEVELS = {"read-only", "write-local", "write-vault", "deploy-remote"}


def permission_level_for_tool(
    skill_name: str,
    args: dict | None = None,
    skill_meta: dict | None = None,
) -> PermissionLevel:
    name = str(skill_name or "").strip()
    payload = args if isinstance(args, dict) else {}
    action = str(payload.get("action", "")).strip().lower()
    path = str(payload.get("path", "") or payload.get("filename", "")).strip()
    if skill_meta is not None and not isinstance(skill_meta, dict):
        return "unknown"
    meta = skill_meta or {}

    if meta.get("version") == "mcp":
        mcp_permission = str(meta.get("mcp_permission") or "").strip().lower()
        if mcp_permission == "write":
            return "write-local"
        if mcp_permission == "read":
            return "read-only"
        return "unknown"

    if name == "obsidian_write":
        return "write-vault"
    if name == "hugo_blog":
        return "deploy-remote" if action == "deploy" else "write-local"
    if name in {"github", "git", "git_ops", "github_ops"}:
        # github_ops is the registered skill. Read actions stay read-only;
        # creating issues or running arbitrary gh is a remote side effect.
        # Any other github_ops action stays at the remote ceiling so an
        # unrecognized action is not labeled read-only.
        if name == "github_ops" and action in {"list_repos", "list_issues", "list_prs", "view_repo"}:
            return "read-only"
        if action in {"push", "publish", "deploy", "create_issue", "run"} or name == "github_ops":
            return "deploy-remote"
        return "write-local"
    if name == "file_ops":
        if "/yivxer-blog/content/posts/" in path and action == "write":
            return "deploy-remote"
        return "write-local" if action in {"write", "append", "edit", "delete"} else "read-only"
    if name in {"shell", "shell_execute", "run_shell"}:
        command = str(payload.get("command", "")).lower()
        if "git push" in command or "rsync" in command or "deploy" in command:
            return "deploy-remote"
        return "write-local"
    if name.endswith("_read") or name.endswith("_search") or name in {
        "web_search",
        "web_fetch",
        "obsidian_read",
        "obsidian_search",
        "code_search",
        "doctor",
        "status",
    }:
        return "read-only"
    # Residual names use the explicit registry contract. A name that was never
    # classified stays unknown so a missing rule cannot look like a read grant.
    from skills.catalog import contract_for_skill_name

    level = contract_for_skill_name(name)["permissionLevel"]
    if level in _KNOWN_LEVELS:
        return level  # type: ignore[return-value]
    return "unknown"


# B3.1: P0 critical skills —— 副作用大、失败影响高的 skill，需更严的执行包装 + 失败提示
# 用于 tool_runtime.invoke 差异化处理（如更严超时、失败时发 failureHintEvent）
P0_CRITICAL_SKILLS: frozenset[str] = frozenset({
    "hugo_blog",        # 博客发布：远程部署，失败可能留下半发布状态
    "obsidian_write",   # Obsidian 写入：vault 文件修改，失败可能损坏笔记
    "file_ops",         # 文件操作：本地文件写入/删除
    "shell",            # Shell 执行：任意命令
    "shell_execute",    # Shell 执行别名
    "run_shell",        # Shell 执行别名
    "github",           # Git push：远程操作
    "git_ops",          # Git 操作
})


def is_p0_critical_skill(skill_name: str) -> bool:
    """判断是否为 P0 critical skill（需要更严的执行包装）."""
    return str(skill_name or "").strip() in P0_CRITICAL_SKILLS
