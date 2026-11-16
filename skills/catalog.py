"""Public skill catalog projected from the production registry.

The loader registration is the name source. Permission and approval labels are
explicit classifications of that registry. A skill with no classification is
reported as unknown; it is never presented as read-only or as not requiring
approval. Per-call ``permission_level_for_tool`` still has its own fallback and
is not reused here.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from skills.loader import SKILLS_DIR, _ast_literal_to_py, register_all_skills

KNOWN_RISKS = {"low", "medium", "high", "critical"}
KNOWN_LEVELS = {"read-only", "write-local", "write-vault", "deploy-remote"}
KNOWN_APPROVALS = {"required", "not_required", "conditional"}
_RECENT_DECISIONS = {"approved", "denied"}
_OUTPUT_SUMMARY = "未声明结构化输出"

# permission, basis, approval. basis is "fixed" or "ceiling".
# ceiling = the highest privilege a call can reach; individual calls may be lower.
_CONTRACT: dict[str, tuple[str, str, str]] = {
    "apple_reminders": ("write-local", "ceiling", "not_required"),
    "browser_automation": ("unknown", "unknown", "not_required"),
    "clipboard": ("write-local", "ceiling", "not_required"),
    "code_edit": ("write-local", "fixed", "not_required"),
    "code_review": ("write-local", "ceiling", "not_required"),
    "code_search": ("read-only", "fixed", "not_required"),
    "docx_editor": ("write-local", "fixed", "not_required"),
    "file_ops": ("deploy-remote", "ceiling", "conditional"),
    "file_search": ("read-only", "fixed", "not_required"),
    "frontend_dev": ("write-local", "ceiling", "not_required"),
    "github_ops": ("deploy-remote", "ceiling", "required"),
    "hugo_blog": ("deploy-remote", "ceiling", "conditional"),
    "humanizer": ("read-only", "fixed", "not_required"),
    "image_analysis": ("read-only", "fixed", "not_required"),
    "image_generator": ("write-local", "ceiling", "not_required"),
    "image_ocr": ("read-only", "fixed", "not_required"),
    "installer": ("write-local", "fixed", "not_required"),
    "market_research": ("write-local", "ceiling", "not_required"),
    "memory_save": ("write-local", "fixed", "not_required"),
    "npm_run": ("write-local", "ceiling", "not_required"),
    "obsidian_read": ("read-only", "fixed", "not_required"),
    "obsidian_search": ("read-only", "fixed", "not_required"),
    "obsidian_write": ("write-vault", "fixed", "conditional"),
    "page_screenshot": ("write-local", "fixed", "not_required"),
    "pdf_reader": ("read-only", "fixed", "not_required"),
    "process_manager": ("write-local", "fixed", "not_required"),
    "rss_reader": ("read-only", "fixed", "not_required"),
    "run_shell": ("deploy-remote", "ceiling", "conditional"),
    "screenshot": ("write-local", "fixed", "not_required"),
    "shell": ("deploy-remote", "ceiling", "conditional"),
    "site_check": ("read-only", "fixed", "not_required"),
    "soul_evolution": ("read-only", "fixed", "not_required"),
    "summarize": ("read-only", "fixed", "not_required"),
    "task_manager": ("write-local", "ceiling", "not_required"),
    "video_script": ("write-local", "ceiling", "not_required"),
    "weather": ("read-only", "fixed", "not_required"),
    "web_fetch": ("read-only", "fixed", "not_required"),
    "web_search": ("read-only", "fixed", "not_required"),
    "weekly_review": ("read-only", "fixed", "not_required"),
    "whisper_transcribe": ("write-local", "ceiling", "not_required"),
    "workflow_automation": ("write-local", "ceiling", "not_required"),
}


def contract_for_skill_name(name: str) -> dict[str, str]:
    """Classify one skill name. Unknown names stay unknown on every axis."""
    permission, basis, approval = _CONTRACT.get(name, ("unknown", "unknown", "unknown"))
    if permission not in KNOWN_LEVELS:
        permission = "unknown"
        basis = "unknown"
    if basis not in {"fixed", "ceiling"}:
        basis = "unknown"
    if approval not in KNOWN_APPROVALS:
        approval = "unknown"
    if permission == "unknown":
        basis = "unknown"
    return {
        "permissionLevel": permission,
        "permissionBasis": basis,
        "approval": approval,
    }


def _default_audit_items() -> list[dict] | None:
    try:
        from terminal.api._config import read_tool_approval_audit

        payload = read_tool_approval_audit(50)
    except Exception:
        return None
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return None
    return [item for item in items if isinstance(item, dict)]


def _recent_approval(name: str, items: list[dict] | None) -> dict[str, Any]:
    if items is None:
        return {"state": "unavailable", "count": 0, "latest": None}
    matched = [item for item in items if str(item.get("skillName") or "") == name]
    if not matched:
        return {"state": "none", "count": 0, "latest": None}

    def _recent_key(item: dict) -> float:
        timestamp = item.get("timestamp")
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
            return float(timestamp)
        return float("-inf")

    latest = max(matched, key=_recent_key)
    decision = str(latest.get("decision") or "")
    if decision not in _RECENT_DECISIONS:
        decision = "unknown"
    level = str(latest.get("permissionLevel") or "")
    if level not in KNOWN_LEVELS:
        level = "unknown"
    redacted: dict[str, Any] = {
        "decision": decision,
        "executed": bool(latest.get("executed")),
        "permissionLevel": level,
    }
    timestamp = latest.get("timestamp")
    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
        redacted["at"] = timestamp
    return {"state": "recorded", "count": len(matched), "latest": redacted}


def _imported_schema_files(tree: ast.AST) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for node in getattr(tree, "body", []):
        if not isinstance(node, ast.ImportFrom) or not node.module or not node.module.startswith("skills."):
            continue
        parts = node.module.split(".")
        if len(parts) != 2 or not parts[1].isidentifier():
            continue
        for alias in node.names:
            if alias.name != "schema":
                continue
            found[alias.asname or alias.name] = SKILLS_DIR / f"{parts[1]}.py"
    return found


def _schema_dict_from_file(path: Path, seen: set[Path]) -> dict | None:
    if path in seen or not path.is_file():
        return None
    seen.add(path)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    function = next(
        (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "schema"),
        None,
    )
    if function is None:
        return None
    for node in function.body:
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            parsed = _ast_literal_to_py(node.value)
            if isinstance(parsed, dict):
                return parsed
    imported = _imported_schema_files(tree)
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in imported:
            return _schema_dict_from_file(imported[node.func.id], seen)
    return None


def _input_summary(schema: dict | None) -> tuple[str, bool]:
    if not isinstance(schema, dict):
        return "未从注册源解析到输入声明", False
    function = schema.get("function")
    if not isinstance(function, dict):
        return "未从注册源解析到输入声明", False
    parameters = function.get("parameters") if isinstance(function.get("parameters"), dict) else {}
    properties = parameters.get("properties") if isinstance(parameters.get("properties"), dict) else {}
    required = [name for name in parameters.get("required") or [] if isinstance(name, str)]
    optional = [name for name in properties if isinstance(name, str) and name not in required]
    if not required and not optional:
        return "未声明输入字段", True
    parts: list[str] = []
    if required:
        parts.append("必填 " + "、".join(required))
    if optional:
        shown = optional[:8]
        text = "、".join(shown)
        if len(optional) > len(shown):
            text += f" 等{len(optional)}项"
        parts.append("可选 " + text)
    return "；".join(parts), True


def build_skill_catalog(
    *,
    disabled: set | None = None,
    audit_items: list[dict] | None = None,
    include_audit: bool = True,
) -> list[dict]:
    """Project the registered skills into the desktop/API contract."""
    disabled_names = {str(item) for item in (disabled or set())}
    if include_audit and audit_items is None:
        audit_items = _default_audit_items()
    if not include_audit:
        audit_items = []

    registry = register_all_skills()
    rows: list[dict] = []
    for name, meta in sorted(registry.metas().items()):
        classified = contract_for_skill_name(name)
        path = getattr(registry, "_paths", {}).get(name)
        schema = _schema_dict_from_file(path, set()) if isinstance(path, Path) else None
        input_summary, io_declared = _input_summary(schema)
        risk = str(getattr(meta, "risk", "") or "")
        if risk not in KNOWN_RISKS:
            risk = "unknown"
        rows.append({
            "name": name,
            "description": str(getattr(meta, "description", "") or name),
            "risk": risk,
            "enabled": name not in disabled_names,
            "permissionLevel": classified["permissionLevel"],
            "permissionBasis": classified["permissionBasis"],
            "approval": classified["approval"],
            "inputSummary": input_summary,
            "outputSummary": _OUTPUT_SUMMARY,
            "ioDeclared": io_declared,
            "recentApproval": _recent_approval(name, audit_items if include_audit else []),
        })
    return rows
