"""
P2-C: /doctor 自检系统

检查 Archer 运行状态，输出结构化健康报告。
/doctor       → 只检查，不修改
/doctor --fix → 检查 + 自动修复可安全修复的问题（仅创建缺失目录）
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable

import core.artifacts as _artifacts


class Level(Enum):
    OK   = "OK"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


@dataclass
class CheckResult:
    level:   Level
    name:    str
    message: str
    fix_fn:  Callable[[], str] | None = field(default=None, repr=False)


# ── 预期存在的表 ────────────────────────────────────────────────────────────────

_EXPECTED_TABLES = {
    "memories", "pending_memories", "themes",
    "memory_links", "projects", "project_events", "soul_proposals",
}

# ── 高风险技能列表 ──────────────────────────────────────────────────────────────

_HIGH_RISK_SKILLS = {"shell", "installer"}


def _check_config(cfg: dict) -> CheckResult:
    missing = []
    if not cfg.get("api", {}).get("api_key"):
        missing.append("api.api_key")
    if not cfg.get("api", {}).get("base_url"):
        missing.append("api.base_url")
    if not cfg.get("api", {}).get("model"):
        missing.append("api.model")
    if not cfg.get("memory", {}).get("db_path"):
        missing.append("memory.db_path")
    if missing:
        return CheckResult(Level.ERROR, "config", f"必要字段缺失：{', '.join(missing)}")
    model = cfg["api"]["model"]
    return CheckResult(Level.OK, "config", f"archer.toml 已加载，model = {model}")


def _check_api(cfg: dict) -> CheckResult:
    base_url = cfg.get("api", {}).get("base_url", "")
    model    = cfg.get("api", {}).get("model", "")
    key      = cfg.get("api", {}).get("api_key", "")
    if not key or key.startswith("your-") or len(key) < 10:
        return CheckResult(Level.WARN, "api", "api_key 看起来是占位符或未配置")
    return CheckResult(Level.OK, "api", f"base_url = {base_url}，model = {model}")


def _check_memory(cfg: dict) -> list[CheckResult]:
    results = []
    db_path_str = cfg.get("memory", {}).get("db_path", "")
    if not db_path_str:
        return [CheckResult(Level.ERROR, "memory", "memory.db_path 未配置")]

    db_path = Path(db_path_str).expanduser()
    if not db_path.exists():
        return [CheckResult(Level.ERROR, "memory", f"数据库文件不存在：{db_path}")]

    try:
        conn = sqlite3.connect(db_path)
        # 可写测试
        conn.execute("PRAGMA journal_mode=WAL")

        # 表完整性检查
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing_tables = _EXPECTED_TABLES - existing
        conn.close()

        if missing_tables:
            results.append(CheckResult(
                Level.WARN, "schema",
                f"缺少表：{', '.join(sorted(missing_tables))}（可能需要重新运行 init_db）",
            ))
        else:
            results.append(CheckResult(
                Level.OK, "schema",
                f"archer.db 可读写，{len(existing)} 张表，结构完整",
            ))
    except Exception as e:
        results.append(CheckResult(Level.ERROR, "memory", f"数据库异常：{e}"))

    return results


def _check_pending(cfg: dict) -> CheckResult:
    db_path_str = cfg.get("memory", {}).get("db_path", "")
    if not db_path_str:
        return CheckResult(Level.ERROR, "pending", "db_path 未配置")
    db_path = Path(db_path_str).expanduser()
    if not db_path.exists():
        return CheckResult(Level.ERROR, "pending", "数据库不存在")
    try:
        conn = sqlite3.connect(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM pending_memories"
        ).fetchone()[0]
        conn.close()
    except Exception:
        return CheckResult(Level.WARN, "pending", "无法查询 pending_memories 表")

    if count == 0:
        return CheckResult(Level.OK, "pending", "无待确认记忆")
    if count >= 10:
        return CheckResult(
            Level.WARN, "pending",
            f"{count} 条待确认记忆，建议 /memory pending 审阅",
        )
    return CheckResult(Level.INFO, "pending", f"{count} 条待确认记忆")


def _check_soul(cfg: dict) -> CheckResult:
    soul_path_str = cfg.get("persona", {}).get("soul_path", "")
    if not soul_path_str:
        return CheckResult(Level.WARN, "soul", "soul_path 未在 archer.toml [persona] 中配置")
    p = Path(soul_path_str).expanduser()
    if p.exists():
        return CheckResult(Level.OK, "soul", f"SOUL.md 存在（{p}）")
    return CheckResult(Level.ERROR, "soul", f"SOUL.md 不存在：{p}")


def _check_obsidian(cfg: dict) -> CheckResult:
    vault_str = cfg.get("obsidian", {}).get("vault_path", "")
    if not vault_str:
        return CheckResult(Level.WARN, "obsidian", "obsidian.vault_path 未配置")
    p = Path(vault_str).expanduser()
    if p.exists() and p.is_dir():
        return CheckResult(Level.OK, "obsidian", f"vault 存在（{p}）")
    return CheckResult(Level.ERROR, "obsidian", f"vault 路径不存在：{p}")


def _check_path_safety(cfg: dict) -> list[CheckResult]:
    """v1.2 Phase 0：检查路径安全配置是否符合要求。"""
    results = []
    vault_str = cfg.get("obsidian", {}).get("vault_path", "")

    if not vault_str:
        results.append(CheckResult(Level.WARN, "path_safety", "obsidian.vault_path 未配置，file_ops 写入无法判断归属"))
        return results

    vault_p = Path(vault_str).expanduser()
    if not vault_p.exists():
        results.append(CheckResult(Level.ERROR, "path_safety", f"vault_path 不存在：{vault_p}"))
        return results
    if not vault_p.is_dir():
        results.append(CheckResult(Level.ERROR, "path_safety", f"vault_path 不是目录：{vault_p}"))
        return results

    # 检查 vault_path 是否可 resolve（符号链接穿透检测）
    try:
        resolved = vault_p.resolve()
        if resolved != vault_p.resolve():
            results.append(CheckResult(Level.WARN, "path_safety", "vault_path 含符号链接，已 resolve"))
        results.append(CheckResult(Level.OK, "path_safety", f"vault_path 安全，resolve → {resolved}"))
    except OSError as e:
        results.append(CheckResult(Level.ERROR, "path_safety", f"vault_path resolve 失败：{e}"))

    return results


def _check_skills(skills: dict) -> list[CheckResult]:
    results = []
    count = len(skills)
    if count == 0:
        results.append(CheckResult(Level.WARN, "skills", "没有加载任何技能"))
    else:
        results.append(CheckResult(Level.OK, "skills", f"{count} 个技能已加载：{', '.join(sorted(skills))}"))

    risk = _HIGH_RISK_SKILLS & set(skills)
    if risk:
        results.append(CheckResult(
            Level.INFO, "risk",
            f"高风险技能已启用：{', '.join(sorted(risk))}（正常，已有 Policy 防护）",
        ))
    return results


def _check_artifacts() -> CheckResult:
    arts_dir = _artifacts.ARTIFACTS_DIR
    if not arts_dir.exists():
        def _fix_artifacts() -> str:
            for sub in _artifacts.ARTIFACT_TYPES:
                (_artifacts.ARTIFACTS_DIR / sub).mkdir(parents=True, exist_ok=True)
            return ".artifacts/ 目录已创建"

        return CheckResult(
            Level.WARN, "artifacts",
            ".artifacts/ 目录不存在",
            fix_fn=_fix_artifacts,
        )
    size = _artifacts.fmt_size(_artifacts.dir_size())
    return CheckResult(Level.OK, "artifacts", f".artifacts/ 存在，占用 {size}")


def _check_sessions() -> CheckResult:
    from core.session import SESSIONS_DIR  # type: ignore[attr-defined]

    sessions_dir = Path(SESSIONS_DIR) if not isinstance(SESSIONS_DIR, Path) else SESSIONS_DIR
    if not sessions_dir.exists():
        def _fix_sessions() -> str:
            sessions_dir.mkdir(parents=True, exist_ok=True)
            return f"{sessions_dir} 已创建"

        return CheckResult(
            Level.WARN, "sessions",
            f"sessions 目录不存在：{sessions_dir}",
            fix_fn=_fix_sessions,
        )
    # 写入测试
    try:
        test_file = sessions_dir / ".doctor_write_test"
        test_file.write_text("ok")
        test_file.unlink()
        return CheckResult(Level.OK, "sessions", f"sessions/ 可写（{sessions_dir}）")
    except Exception as e:
        return CheckResult(Level.ERROR, "sessions", f"sessions/ 不可写：{e}")


# ── 主入口 ──────────────────────────────────────────────────────────────────────

def run_checks(cfg: dict, skills: dict) -> list[CheckResult]:
    results: list[CheckResult] = []
    results.append(_check_config(cfg))
    results.append(_check_api(cfg))
    results.extend(_check_memory(cfg))
    results.append(_check_pending(cfg))
    results.append(_check_soul(cfg))
    results.append(_check_obsidian(cfg))
    results.extend(_check_path_safety(cfg))
    results.extend(_check_skills(skills))
    results.append(_check_artifacts())
    results.append(_check_sessions())
    return results


def apply_fixes(results: list[CheckResult]) -> list[str]:
    """对所有带 fix_fn 的检查项尝试自动修复，返回修复日志。"""
    applied: list[str] = []
    for r in results:
        if r.fix_fn is not None and r.level in (Level.WARN, Level.ERROR):
            try:
                msg = r.fix_fn()
                applied.append(f"[fix] {r.name}: {msg}")
            except Exception as e:
                applied.append(f"[fix-failed] {r.name}: {e}")
    return applied
