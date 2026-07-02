"""A7 proactive touch suggestions.

This module only produces local, reviewable suggestions. It does not send
notifications or mutate user data.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DEEP_MEMORY_TYPES = {
    "emotion_pattern",
    "value",
    "value_conflict",
    "life_theme",
    "self_narrative",
    "project_mythology",
    "relationship_pattern",
    "creative_identity",
    "growth_marker",
    "reflection_anchor",
}


def scan_proactive_touch(
    db_path: Path,
    sessions_dir: Path,
    now: datetime | None = None,
    cfg: dict | None = None,
) -> list[dict]:
    cfg = cfg or {}
    options = cfg.get("proactive", {}) if isinstance(cfg.get("proactive", {}), dict) else {}
    if options.get("enabled", True) is False:
        return []

    now = now or datetime.now()
    items: list[dict] = []
    deep_session = _deep_session_item(sessions_dir, now, options)
    if deep_session:
        items.append(deep_session)
    deep_memory = _deep_memory_item(db_path, now, options)
    if deep_memory:
        items.append(deep_memory)
    anxiety = _anxiety_item(db_path, now, options)
    if anxiety:
        items.append(anxiety)
    hypothesis = _due_hypothesis_item(db_path, now, options)
    if hypothesis:
        items.append(hypothesis)

    rank = {"high": 0, "medium": 1, "low": 2}
    return sorted(items, key=lambda item: rank.get(item.get("severity", "low"), 9))[:5]


def _deep_session_item(sessions_dir: Path, now: datetime, options: dict) -> dict | None:
    threshold_days = int(options.get("deep_session_days", 7) or 7)
    turn_threshold = int(options.get("deep_session_turns", 8) or 8)
    latest: tuple[datetime, Path, int] | None = None
    if not sessions_dir.exists():
        return None
    for path in sessions_dir.glob("*.json"):
        created_at = _session_time(path)
        turns = _session_turns(path)
        if turns < turn_threshold:
            continue
        if latest is None or created_at > latest[0]:
            latest = (created_at, path, turns)
    if latest is None:
        return None
    age_days = (now - latest[0]).days
    if age_days < threshold_days:
        return None
    return {
        "id": "deep-session-review",
        "kind": "deep_session_review",
        "severity": "medium",
        "title": "有一段深度对话很久没回看",
        "detail": f"上次深度对话约 {age_days} 天前，{latest[2]} 轮。",
        "action": "回看历史",
        "target": "Sessions",
    }


def _deep_memory_item(db_path: Path, now: datetime, options: dict) -> dict | None:
    threshold_days = int(options.get("deep_memory_days", 30) or 30)
    if not db_path.exists():
        return None
    cutoff = (now - timedelta(days=threshold_days)).isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    try:
        placeholders = ",".join("?" for _ in DEEP_MEMORY_TYPES)
        rows = conn.execute(
            f"SELECT id, content, type, importance, last_used_at, updated_at, created_at "
            f"FROM memories WHERE status = 'active' "
            f"AND (type IN ({placeholders}) OR importance >= 5) "
            f"AND COALESCE(last_used_at, updated_at, created_at) < ? "
            f"ORDER BY importance DESC, created_at ASC LIMIT 1",
            (*sorted(DEEP_MEMORY_TYPES), cutoff),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    if not rows:
        return None
    mid, content, memory_type, importance, last_used_at, updated_at, created_at = rows[0]
    last_seen = _parse_iso(last_used_at or updated_at or created_at)
    age_days = (now - last_seen).days if last_seen else threshold_days
    return {
        "id": f"deep-memory-review-{mid}",
        "kind": "deep_memory_review",
        "severity": "medium" if importance < 5 else "high",
        "title": "有一条深层记忆需要回看",
        "detail": f"{memory_type} 约 {age_days} 天未被使用：{str(content)[:36]}",
        "action": "打开记忆",
        "target": "Memory",
    }


def _anxiety_item(db_path: Path, now: datetime, options: dict) -> dict | None:
    days = int(options.get("anxiety_days", 7) or 7)
    threshold = float(options.get("anxiety_score", 7) or 7)
    if not db_path.exists():
        return None
    cutoff = (now - timedelta(days=days)).isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT AVG(score), COUNT(*) FROM session_emotions "
            "WHERE emotion = '焦虑' AND created_at >= ?",
            (cutoff,),
        ).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        conn.close()
    if not row or not row[0] or row[0] < threshold:
        return None
    score = round(float(row[0]), 1)
    return {
        "id": "anxiety-checkin",
        "kind": "anxiety_checkin",
        "severity": "high" if score >= 8 else "medium",
        "title": "近期焦虑偏高",
        "detail": f"近 {days} 天焦虑平均 {score}/10，可以做一次轻复盘。",
        "action": "开始复盘",
        "target": "Chat",
    }


def _due_hypothesis_item(db_path: Path, now: datetime, options: dict) -> dict | None:
    if options.get("hypothesis_due", True) is False:
        return None
    if not db_path.exists():
        return None
    stamp = now.isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT id, title, statement, validate_after FROM hypotheses "
            "WHERE status='active' AND validate_after <= ? "
            "AND (muted_until IS NULL OR muted_until = '' OR muted_until <= ?) "
            "ORDER BY validate_after ASC, id ASC LIMIT 1",
            (stamp, stamp),
        ).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        conn.close()
    if not row:
        return None
    due_at = _parse_iso(str(row["validate_after"] or ""))
    overdue_days = max(0, (now - due_at).days) if due_at else 0
    detail = f"到期约 {overdue_days} 天：{str(row['statement'])[:42]}"
    return {
        "id": f"hypothesis-review-{row['id']}",
        "kind": "hypothesis_review",
        "severity": "medium",
        "title": f"有一个假设到了验证时间：{row['title']}",
        "detail": detail,
        "action": "验证假设",
        "target": "Memory",
    }


def _session_time(path: Path) -> datetime:
    try:
        return datetime.strptime(path.stem[:15], "%Y%m%d_%H%M%S")
    except Exception:
        return datetime.fromtimestamp(path.stat().st_mtime)


def _session_turns(path: Path) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if not isinstance(data, list):
        return 0
    user_messages = [item for item in data if isinstance(item, dict) and item.get("role") == "user"]
    return len(user_messages)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None
