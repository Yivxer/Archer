from __future__ import annotations

from typing import Literal

PermissionLevel = Literal["read-only", "write-local", "write-vault", "deploy-remote"]


def permission_level_for_tool(
    skill_name: str,
    args: dict | None = None,
    skill_meta: dict | None = None,
) -> PermissionLevel:
    name = str(skill_name or "").strip()
    payload = args or {}
    action = str(payload.get("action", "")).strip().lower()
    path = str(payload.get("path", "") or payload.get("filename", "")).strip()

    if (skill_meta or {}).get("version") == "mcp":
        return "write-local" if (skill_meta or {}).get("mcp_permission") == "write" else "read-only"

    if name == "obsidian_write":
        return "write-vault"
    if name == "hugo_blog":
        return "deploy-remote" if action == "deploy" else "write-local"
    if name in {"github", "git", "git_ops"}:
        return "deploy-remote" if action in {"push", "publish", "deploy"} else "write-local"
    if name == "file_ops":
        if "/yivxer-blog/content/posts/" in path and action == "write":
            return "deploy-remote"
        return "write-local" if action in {"write", "append", "edit", "delete"} else "read-only"
    if name in {"shell", "shell_execute"}:
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
    return "read-only"


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
