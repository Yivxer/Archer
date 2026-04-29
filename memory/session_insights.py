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
        return {"sessions": 0, "turns": 0, "topics": [], "skills": []}

    total_turns = 0
    all_user_text = []
    skill_calls = Counter()

    for s in sessions:
        turns = s["turns"]
        user_msgs = [m["content"] for m in turns if m.get("role") == "user"]
        total_turns += len(user_msgs)
        all_user_text.extend(user_msgs)

        # 粗略检测技能调用（assistant 消息里有 tool_calls 不一定存在 JSON session 里）
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
    }


def format_report(days: int = 7) -> str:
    data = analyze(days)
    if data["sessions"] == 0:
        return f"最近 {days} 天没有会话记录。"

    lines = [
        f"最近 {data['days']} 天  {data['sessions']} 次会话  共 {data['turns']} 轮对话",
        f"平均每次 {data['avg_turns_per_session']} 轮",
    ]
    if data["top_skills"]:
        skill_str = "  ".join(f"{k}×{v}" for k, v in data["top_skills"])
        lines.append(f"高频技能  {skill_str}")

    return "\n".join(lines)
