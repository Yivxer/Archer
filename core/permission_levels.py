from __future__ import annotations

from typing import Literal

PermissionLevel = Literal["read-only", "write-local", "write-vault", "deploy-remote"]


def permission_level_for_tool(skill_name: str, args: dict | None = None) -> PermissionLevel:
    name = str(skill_name or "").strip()
    payload = args or {}
    action = str(payload.get("action", "")).strip().lower()
    path = str(payload.get("path", "") or payload.get("filename", "")).strip()

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
