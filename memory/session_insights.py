"""
扫描最近 N 天的 session 文件，生成行为洞察。
"""
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

SESSIONS_DIR = Path(__file__).parent / "sessions"


def _load_recent(days: int = 7) -> list[dict]:
    cutoff = datetime.now() - timedelta(days=days)
    sessions = []
    for f in sorted(SESSIONS_DIR.glob("*.json")):
        if datetime.fromtimestamp(f.stat().st_mtime) >= cutoff:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                sessions.append({"file": f.name, "turns": data})
            except Exception:
                pass
    return sessions


def analyze(days: int = 7) -> dict:
    sessions = _load_recent(days)
    if not sessions:
        return {"sessions": 0, "turns": 0, "days": days, "top_skills": [],
                "avg_turns_per_session": 0, "daily": {}}

    total_turns = 0
    skill_calls = Counter()
    daily: dict[str, int] = {}

    for s in sessions:
        turns = s["turns"]
        user_msgs = [m["content"] for m in turns if m.get("role") == "user"]
        total_turns += len(user_msgs)

        # 从文件名提取日期（格式 20260425_102830.json）
        fname = s["file"]
        try:
            date_str = f"{fname[4:6]}-{fname[6:8]}"
        except Exception:
            date_str = "??"
        daily[date_str] = daily.get(date_str, 0) + len(user_msgs)

        for m in turns:
            if m.get("role") == "assistant":
                content = m.get("content", "")
                if "→" in content:
                    for part in content.split("→"):
                        part = part.strip().strip("[]").split("…")[0].strip()
                        if part and len(part) < 30:
                            skill_calls[part] += 1

    return {
        "sessions": len(sessions),
        "turns": total_turns,
        "days": days,
        "top_skills": skill_calls.most_common(5),
        "avg_turns_per_session": round(total_turns / len(sessions), 1),
        "daily": daily,
    }


def search_sessions(keyword: str, limit: int = 15) -> list[dict]:
    """全文搜索所有 session 文件，返回匹配项列表。"""
    kw = keyword.lower()
    results = []
    for f in sorted(SESSIONS_DIR.glob("*.json"), reverse=True):
        try:
            msgs = json.loads(f.read_text(encoding="utf-8"))
            for m in msgs:
                if m.get("role") == "user":
                    content = str(m.get("content", ""))
                    if kw in content.lower():
                        results.append({
                            "session_id": f.stem,
                            "preview": content[:100].replace("\n", " "),
                        })
                        break
        except Exception:
            pass
        if len(results) >= limit:
            break
    return results


def format_report(days: int = 7) -> str:
    data = analyze(days)
    if data["sessions"] == 0:
        return f"[dim]最近 {days} 天没有会话记录。[/dim]"

    lines = [
        f"  [bold]最近 {data['days']} 天[/bold]  "
        f"[dim]{data['sessions']} 次会话  {data['turns']} 轮  均 {data['avg_turns_per_session']} 轮/次[/dim]",
    ]

    # 每日柱状图
    daily = data.get("daily", {})
    if daily:
        max_val = max(daily.values(), default=1)
        lines.append("")
        for date in sorted(daily.keys()):
            turns = daily[date]
            bar_w = max(1, int(turns / max_val * 16))
            lines.append(f"  [dim]{date}[/dim]  [#4dd9d4]{'█' * bar_w}[/#4dd9d4]  [dim]{turns}[/dim]")

    if data["top_skills"]:
        lines.append("")
        skill_str = "  ".join(f"[dim]{k}×{v}[/dim]" for k, v in data["top_skills"])
        lines.append(f"  高频技能  {skill_str}")

    return "\n".join(lines)
