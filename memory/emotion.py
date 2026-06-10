"""
P3: 情绪地图（Emotional Cartography）

每次会话后提取情绪向量，按日聚合存储。
Layer 2 —— 低模型依赖：简单分类 prompt，任何模型都能做。
"""

from __future__ import annotations
import json
import sqlite3
import re
from datetime import datetime, timedelta
from pathlib import Path
from core.paths import memory_db_path

DB_PATH = memory_db_path(Path(__file__).parent / "archer.db")

EMOTIONS = ["焦虑", "专注", "疲惫", "兴奋", "平静", "沮丧"]

# 对于非中文输出做映射
_EMOTION_EN_MAP = {
    "anxiety": "焦虑", "focus": "专注", "fatigue": "疲惫",
    "excitement": "兴奋", "calm": "平静", "frustration": "沮丧",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def init_emotion_table():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_emotions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT    NOT NULL,
            emotion    TEXT    NOT NULL,
            score      REAL    NOT NULL DEFAULT 5.0,
            created_at TEXT    NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_session_emotions_date
        ON session_emotions(created_at)
    """)
    conn.commit()
    conn.close()


def _parse_emotion_json(text: str) -> dict[str, float] | None:
    """从 LLM 输出中提取情绪 JSON。容忍 markdown code block 和额外文字。"""
    # 尝试直接解析
    try:
        d = json.loads(text.strip())
        return _normalize(d)
    except Exception:
        pass
    # 尝试提取 ```json ... ``` 块
    m = re.search(r'\{[^}]+\}', text, re.DOTALL)
    if m:
        try:
            return _normalize(json.loads(m.group()))
        except Exception:
            pass
    return None


def _normalize(raw: dict) -> dict[str, float]:
    """将 JSON 键标准化为中文情绪名，值限制在 0-10。"""
    result: dict[str, float] = {}
    for k, v in raw.items():
        name = _EMOTION_EN_MAP.get(k.lower(), k)
        if name in EMOTIONS:
            try:
                result[name] = max(0.0, min(10.0, float(v)))
            except (ValueError, TypeError):
                result[name] = 5.0
    return result


def _build_emotion_prompt(history: list[dict]) -> str:
    """构造情绪分类 prompt。取最近 N 条消息的摘要。"""
    # 只取用户消息做摘要（最多 6 条）
    user_msgs = [
        m.get("content", "")[:300]
        for m in history[-12:] if m.get("role") == "user"
    ][-6:]
    summary = "\n".join(f"- {m}" for m in user_msgs)
    emotions_str = "/".join(EMOTIONS)
    return (
        "你是情绪分析师。根据以下对话中的用户消息（不是 AI 回复），"
        "评估用户在这场对话中的情绪状态。\n"
        f"情绪维度：{emotions_str}\n"
        "每项评分 0-10（0=无，10=极强）。\n"
        "只输出 JSON 对象，不要任何解释。\n\n"
        f"用户消息：\n{summary}\n\n"
        "JSON："
    )


def extract_emotion(history: list[dict], session_id: str, cfg: dict | None = None) -> dict[str, float] | None:
    """
    从会话历史中提取情绪向量。
    调用 LLM 做分类（低开销单次调用），结果存入 session_emotions 表。
    返回情绪向量字典。失败时返回 None（不阻塞主流程）。
    """
    if len(history) < 2:
        return None
    try:
        prompt = _build_emotion_prompt(history)
        from core.llm import stream_chat, load_config as llm_config
        cfg = cfg or llm_config()
        messages = [{"role": "user", "content": prompt}]
        # 收集流式输出
        full = ""
        for chunk in stream_chat(messages, track_usage=False):
            full += chunk
        parsed = _parse_emotion_json(full)
        if not parsed:
            return None
        # 存入 DB
        _save_emotions(session_id, parsed)
        return parsed
    except Exception:
        return None


def _save_emotions(session_id: str, emotions: dict[str, float]):
    conn = sqlite3.connect(DB_PATH)
    now = _now()
    for emotion, score in emotions.items():
        conn.execute(
            "INSERT INTO session_emotions (session_id, emotion, score, created_at) VALUES (?,?,?,?)",
            (session_id, emotion, score, now),
        )
    conn.commit()
    conn.close()


def emotion_trend(days: int = 30) -> dict[str, list[dict]]:
    """
    返回最近 N 天的情绪趋势数据。
    每天对同类型情绪取平均分。
    返回 {emotion_name: [{date, avg_score}, ...]}
    """
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT emotion, AVG(score) as avg_score, DATE(created_at) as day "
        "FROM session_emotions WHERE created_at >= ? "
        "GROUP BY emotion, day ORDER BY day",
        (cutoff,),
    ).fetchall()
    conn.close()
    result: dict[str, list[dict]] = {e: [] for e in EMOTIONS}
    for emotion, avg_score, day in rows:
        if emotion in result:
            result[emotion].append({"date": day, "avg_score": round(avg_score, 1)})
    return result


def emotion_summary(days: int = 30) -> str:
    """
    生成情绪摘要文本。例如：
    「近 30 天：平静 ↑ 专注 ↑ 焦虑 ↓ 疲惫 →」
    """
    trend = emotion_trend(days)
    lines = []
    for emotion in EMOTIONS:
        points = trend.get(emotion, [])
        if len(points) >= 2:
            first = points[0]["avg_score"]
            last = points[-1]["avg_score"]
            diff = last - first
            if abs(diff) < 0.5:
                arrow = "→"
            elif diff > 0:
                arrow = "↑"
            else:
                arrow = "↓"
            lines.append(f"{emotion} {arrow}")
    return "  ".join(lines) if lines else "暂无情绪数据"


# 当轮情绪信号词（规则版，零 LLM；想法 6）
_TURN_EMOTION_SIGNALS: dict[str, tuple[str, ...]] = {
    "焦虑": ("焦虑", "担心", "害怕", "慌", "不安", "纠结", "压力大"),
    "疲惫": ("累", "疲惫", "困", "撑不住", "没劲", "好累"),
    "沮丧": ("难受", "沮丧", "失落", "烦", "委屈", "孤独", "心烦"),
    "兴奋": ("兴奋", "激动", "开心", "太好了", "爽"),
    "平静": ("平静", "还好", "没事", "挺好的"),
    "专注": ("专注", "投入", "在做", "埋头"),
}


def _texts_for_turn_read(user_text: str, history: list[dict] | None) -> list[str]:
    out = [(user_text or "").strip()]
    if not history:
        return [t for t in out if t]
    for msg in reversed(history):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            t = content.strip()
        elif isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
            t = " ".join(parts).strip()
        else:
            t = ""
        if t:
            out.append(t)
        if len(out) >= 3:
            break
    return [t for t in out if t]


def infer_turn_emotion_hint(user_text: str, history: list[dict] | None = None) -> str | None:
    """从当轮 + 近几轮用户话里推断情绪读数，生成 prompt 提示（零 LLM）。

    用于调整当轮语气，而非事后复盘。失败/无信号时返回 None。
    """
    texts = _texts_for_turn_read(user_text, history)
    scores: dict[str, int] = {}
    for t in texts:
        for emotion, kws in _TURN_EMOTION_SIGNALS.items():
            for kw in kws:
                if kw in t:
                    scores[emotion] = scores.get(emotion, 0) + 1

    if scores:
        top = sorted(scores, key=scores.get, reverse=True)[:2]
        labels = "、".join(top)
        if any(e in top for e in ("焦虑", "疲惫", "沮丧")):
            tone = "语气放慢，多倾听少推进，不急着给方案。"
        else:
            tone = "保持敏锐克制，顺着当前节奏回应。"
        return f"[当轮情绪读数] 感知：{labels}。{tone}"

    try:
        recent = recent_emotion(days=3)
        if recent:
            peak = max(recent, key=recent.get)
            if recent[peak] >= 6:
                return (
                    f"[当轮情绪读数] 近几天{peak}偏高（{recent[peak]:.0f}/10）。"
                    "语气放慢，多倾听少推进。"
                )
    except Exception:
        pass
    return None


def recent_emotion(days: int = 7) -> dict[str, float] | None:
    """获取最近 N 天的平均情绪，用于 /status 等快速展示。"""
    conn = sqlite3.connect(DB_PATH)
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    rows = conn.execute(
        "SELECT emotion, AVG(score) FROM session_emotions WHERE created_at >= ? GROUP BY emotion",
        (cutoff,),
    ).fetchall()
    conn.close()
    if not rows:
        return None
    return {r[0]: round(r[1], 1) for r in rows if r[0] in EMOTIONS}
