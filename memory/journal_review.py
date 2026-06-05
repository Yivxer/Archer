"""Local Obsidian journal review and emotion trajectory summaries."""
from __future__ import annotations

import re
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


EMOTION_KEYWORDS = ("焦虑", "专注", "疲惫", "兴奋", "平静", "沮丧")
MAX_NOTE_CHARS = 12000


def build_journal_review(
    vault_path: Path | str | None,
    db_path: Path,
    days: int = 30,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Scan recent Obsidian markdown notes and merge stored session emotions."""
    now = now or datetime.now()
    days = _clean_days(days)
    start = now - timedelta(days=days)
    vault = Path(vault_path).expanduser() if vault_path else None

    if not vault or not vault.exists() or not vault.is_dir():
        review = {
            "configured": False,
            "window": _window(days, start, now),
            "metrics": {"entries": 0, "characters": 0},
            "entries": [],
            "journal_emotions": {emotion: 0 for emotion in EMOTION_KEYWORDS},
            "session_emotions": {emotion: [] for emotion in EMOTION_KEYWORDS},
        }
        review["markdown"] = format_journal_review_markdown(review)
        return review

    entries = _load_recent_notes(vault, start=start, end=now)
    journal_emotions = _count_journal_emotions(entries)
    session_emotions = _load_session_emotions(db_path, start=start, end=now)
    review = {
        "configured": True,
        "window": _window(days, start, now),
        "metrics": {
            "entries": len(entries),
            "characters": sum(item["characters"] for item in entries),
        },
        "entries": [_public_entry(item) for item in entries],
        "journal_emotions": journal_emotions,
        "session_emotions": session_emotions,
    }
    review["markdown"] = format_journal_review_markdown(review)
    return review


def format_journal_review_markdown(review: dict[str, Any]) -> str:
    window = review["window"]
    metrics = review["metrics"]
    lines = [
        "# Obsidian 日记回顾",
        "",
        f"窗口：{window['start'][:10]} 至 {window['end'][:10]}",
        f"日记：{metrics['entries']} 篇；字数：{metrics['characters']}",
        "",
        "## 日记信号",
        "",
    ]

    entries = review.get("entries", [])
    if entries:
        for item in entries[:8]:
            lines.append(f"- {item['date']} · {Path(item['path']).name}：{item['preview']}")
    else:
        lines.append("- 暂无近期日记。")

    lines.extend(["", "## 情绪关键词", ""])
    keyword_lines = [
        f"{emotion} × {count}"
        for emotion, count in review.get("journal_emotions", {}).items()
        if count
    ]
    lines.extend(_bullets(keyword_lines, "暂无明显情绪关键词。"))

    lines.extend(["", "## 会话情绪轨迹", ""])
    trend_lines = _session_emotion_lines(review.get("session_emotions", {}))
    lines.extend(_bullets(trend_lines, "暂无会话情绪数据。"))
    return "\n".join(lines).strip() + "\n"


def _load_recent_notes(vault: Path, start: datetime, end: datetime) -> list[dict[str, Any]]:
    entries = []
    vault_real = vault.resolve()
    for path in sorted(vault.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(vault).parts):
            continue
        if path.is_symlink():
            continue
        try:
            resolved = path.resolve()
            if not str(resolved).startswith(str(vault_real)):
                continue
        except Exception:
            continue
        note_date = _note_date(path) or datetime.fromtimestamp(path.stat().st_mtime)
        if not (start <= note_date <= end):
            continue
        try:
            text = path.read_text(encoding="utf-8")[:MAX_NOTE_CHARS]
        except Exception:
            continue
        preview = re.sub(r"\s+", " ", text).strip()[:90]
        entries.append({
            "path": path.relative_to(vault).as_posix(),
            "date": note_date.date().isoformat(),
            "characters": len(text),
            "preview": preview,
            "text": text,
        })
    return sorted(entries, key=lambda item: item["date"], reverse=True)


def _count_journal_emotions(entries: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter()
    for item in entries:
        text = item.get("text", "")
        for emotion in EMOTION_KEYWORDS:
            counter[emotion] += text.count(emotion)
    return {emotion: int(counter.get(emotion, 0)) for emotion in EMOTION_KEYWORDS}


def _public_entry(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": item["path"],
        "date": item["date"],
        "characters": item["characters"],
        "preview": item["preview"],
    }


def _load_session_emotions(db_path: Path, start: datetime, end: datetime) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {emotion: [] for emotion in EMOTION_KEYWORDS}
    if not db_path.exists():
        return result
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT emotion, AVG(score) as avg_score, DATE(created_at) as day "
            "FROM session_emotions WHERE created_at >= ? AND created_at <= ? "
            "GROUP BY emotion, day ORDER BY day",
            (start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    for emotion, avg_score, day in rows:
        if emotion in result:
            result[emotion].append({"date": day, "avg_score": round(float(avg_score), 1)})
    return result


def _session_emotion_lines(trend: dict[str, list[dict[str, Any]]]) -> list[str]:
    lines = []
    for emotion in EMOTION_KEYWORDS:
        points = trend.get(emotion, [])
        if not points:
            continue
        if len(points) == 1:
            lines.append(f"{emotion}：{points[0]['avg_score']}")
        else:
            lines.append(f"{emotion}：{points[0]['avg_score']} -> {points[-1]['avg_score']}")
    return lines


def _note_date(path: Path) -> datetime | None:
    match = re.search(r"(20\d{2})[-_.年]?(0\d|1[0-2])[-_.月]?([0-2]\d|3[01])", path.stem)
    if not match:
        return None
    try:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _window(days: int, start: datetime, end: datetime) -> dict[str, Any]:
    return {
        "days": days,
        "start": start.isoformat(timespec="seconds"),
        "end": end.isoformat(timespec="seconds"),
    }


def _clean_days(value: int) -> int:
    try:
        days = int(value)
    except Exception:
        days = 30
    return max(1, min(days, 365))


def _bullets(items: list[str], empty: str) -> list[str]:
    clean = [item for item in items if item]
    if not clean:
        return [f"- {empty}"]
    return [f"- {item}" for item in clean]
