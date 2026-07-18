"""Deterministic period reviews from local sessions and memories."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


PERIOD_WINDOWS = {
    "weekly": 7,
    "monthly": 30,
    "life_stage": 90,
}

PERIOD_TITLES = {
    "weekly": "周复盘",
    "monthly": "月复盘",
    "life_stage": "人生阶段复盘",
}

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


def build_period_review(
    db_path: Path,
    sessions_dir: Path,
    period: str = "weekly",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a local, non-LLM review for weekly/monthly/life-stage windows."""
    period = period if period in PERIOD_WINDOWS else "weekly"
    now = now or datetime.now()
    days = PERIOD_WINDOWS[period]
    start = now - timedelta(days=days)

    sessions = _load_sessions(sessions_dir, start=start, end=now)
    memories = _load_memories(db_path, start=start, end=now)
    user_turns = sum(item["user_turns"] for item in sessions)
    deep_memories = [
        item for item in memories
        if item["type"] in DEEP_MEMORY_TYPES or item["importance"] >= 5 or item.get("depth", 3) >= 4
    ]
    themes = _theme_counts(memories)
    growth_markers = [item["content"] for item in memories if item["type"] == "growth_marker"][:5]
    highlights = [item["content"] for item in sorted(memories, key=_memory_rank, reverse=True)[:6]]
    questions = _suggest_questions(period, themes, growth_markers, user_turns)

    review = {
        "period": period,
        "title": PERIOD_TITLES[period],
        "window": {
            "days": days,
            "start": start.isoformat(timespec="seconds"),
            "end": now.isoformat(timespec="seconds"),
        },
        "metrics": {
            "sessions": len(sessions),
            "user_turns": user_turns,
            "memories": len(memories),
            "deep_memories": len(deep_memories),
        },
        "themes": themes,
        "highlights": highlights,
        "growth_markers": growth_markers,
        "suggested_questions": questions,
    }
    review["markdown"] = format_period_review_markdown(review)
    return review


def format_period_review_markdown(review: dict[str, Any]) -> str:
    metrics = review["metrics"]
    window = review["window"]
    lines = [
        f"# {review['title']}",
        "",
        f"窗口：{window['start'][:10]} 至 {window['end'][:10]}",
        f"会话：{metrics['sessions']} 次；用户轮次：{metrics['user_turns']}；新增记忆：{metrics['memories']}；深层记忆：{metrics['deep_memories']}",
        "",
        "## 本期信号",
        "",
    ]
    lines.extend(_bullets(review.get("highlights", []), empty="暂无明显信号。"))
    lines.extend(["", "## 成长标记", ""])
    lines.extend(_bullets(review.get("growth_markers", []), empty="暂无新增成长标记。"))
    lines.extend(["", "## 高频主题", ""])
    theme_lines = [f"{item['type']} × {item['count']}" for item in review.get("themes", [])]
    lines.extend(_bullets(theme_lines, empty="暂无高频主题。"))
    lines.extend(["", "## 下次追问", ""])
    lines.extend(_bullets(review.get("suggested_questions", []), empty="继续积累会话后再复盘。"))
    return "\n".join(lines).strip() + "\n"


def _load_sessions(sessions_dir: Path, start: datetime, end: datetime) -> list[dict[str, Any]]:
    if not sessions_dir.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(sessions_dir.glob("*.json")):
        created_at = _session_time(path)
        if not (start <= created_at <= end):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = []
        if not isinstance(data, list):
            data = []
        user_messages = [item for item in data if isinstance(item, dict) and item.get("role") == "user"]
        items.append({"id": path.stem, "created_at": created_at.isoformat(timespec="seconds"), "user_turns": len(user_messages)})
    return items


def _load_memories(db_path: Path, start: datetime, end: datetime) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, content, type, importance, depth, created_at, updated_at FROM memories "
            "WHERE status = 'active' AND created_at >= ? AND created_at <= ? "
            "ORDER BY importance DESC, created_at DESC",
            (start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    return [
        {
            "id": row["id"],
            "content": str(row["content"]),
            "type": str(row["type"] or "insight"),
            "importance": int(row["importance"] or 3),
            "depth": _clamp_depth(row["depth"] if "depth" in row.keys() else 3),
            "created_at": str(row["created_at"] or ""),
            "updated_at": str(row["updated_at"] or ""),
        }
        for row in rows
    ]


def _theme_counts(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(item["type"] for item in memories)
    return [{"type": key, "count": value} for key, value in counts.most_common(6)]


def _suggest_questions(period: str, themes: list[dict[str, Any]], growth_markers: list[str], user_turns: int) -> list[str]:
    questions = []
    if growth_markers:
        questions.append("哪些变化已经从一次性进展，变成了稳定习惯？")
    if themes:
        top = themes[0]["type"]
        questions.append(f"{top} 反复出现，是因为它真的重要，还是因为它还没有闭环？")
    if user_turns == 0:
        questions.append("这一期没有会话记录，哪些变化发生在 Archer 之外？")
    if period == "life_stage":
        questions.append("这个阶段真正结束的旧叙事是什么？新的叙事又是什么？")
    else:
        questions.append("下一期最小的推进动作是什么？")
    return questions[:4]


def _bullets(items: list[str], empty: str) -> list[str]:
    clean = [str(item).strip() for item in items if str(item).strip()]
    if not clean:
        return [f"- {empty}"]
    return [f"- {item}" for item in clean]


def _memory_rank(item: dict[str, Any]) -> tuple[int, int]:
    return (int(item.get("importance", 3)), int(item.get("depth", 3)), 1 if item.get("type") in DEEP_MEMORY_TYPES else 0)


def _clamp_depth(value: object) -> int:
    try:
        depth = int(str(value)) if not isinstance(value, (int, float)) else int(value)
    except Exception:
        depth = 3
    return max(1, min(5, depth))


def _session_time(path: Path) -> datetime:
    try:
        return datetime.strptime(path.stem[:15], "%Y%m%d_%H%M%S")
    except Exception:
        return datetime.fromtimestamp(path.stat().st_mtime)
