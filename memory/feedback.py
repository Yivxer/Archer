"""
交互反馈信号追踪（进化机制 Phase 4）。

三类信号：
- followup：用户对上一条回复追问（说明没说清楚）
- correction：用户明确纠正 Archer 的行为或判断
- confirm：用户确认 Archer 的方向是对的

积累足够信号后，生成 PRESENCE.md 调整提议（写入 soul_proposals）。
"""
import re
import sqlite3

_CORRECTION_KW = frozenset([
    "不对", "错了", "不是", "不是这个", "不是这样", "不要这样",
    "你理解错了", "不是我要的", "重新", "换一种", "不对劲",
    "停止", "别这样", "不需要", "我没说", "并不是",
])
_CONFIRM_KW = frozenset([
    "对", "好的", "就这样", "就是这个", "正确", "完全对",
    "就是这意思", "很好", "不错", "继续", "可以", "没问题",
])
_FOLLOWUP_KW = frozenset([
    "你刚才", "上面", "你说的", "你提到", "再说一遍",
    "没明白", "解释一下", "什么意思", "不太懂", "能详细",
    "展开说", "具体说", "为什么这么说",
])


def _conn():
    import memory.store as _store
    return sqlite3.connect(_store.DB_PATH)


def init_table():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS interaction_feedback (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_type  TEXT NOT NULL,   -- followup / correction / confirm
                user_text    TEXT DEFAULT '',
                prev_text    TEXT DEFAULT '',  -- 上一条 AI 回复摘要
                session_id   TEXT DEFAULT '',
                created_at   TEXT DEFAULT (datetime('now','localtime'))
            )
        """)


def detect(user_text: str, prev_response: str = "", session_id: str = "") -> str | None:
    """
    检测用户输入的信号类型，记录并返回类型名；无信号返回 None。
    """
    text = user_text.strip()
    signal = None

    if any(kw in text for kw in _CORRECTION_KW):
        signal = "correction"
    elif any(kw in text for kw in _FOLLOWUP_KW):
        signal = "followup"
    elif len(text) <= 12 and any(kw in text for kw in _CONFIRM_KW):
        signal = "confirm"

    if signal:
        with _conn() as c:
            c.execute(
                "INSERT INTO interaction_feedback(signal_type,user_text,prev_text,session_id) VALUES(?,?,?,?)",
                (signal, text[:200], prev_response[:120], session_id),
            )
    return signal


def get_stats(days: int = 30) -> dict:
    with _conn() as c:
        rows = c.execute("""
            SELECT signal_type, COUNT(*) FROM interaction_feedback
            WHERE created_at >= datetime('now', ?, 'localtime')
            GROUP BY signal_type
        """, (f"-{days} days",)).fetchall()
    return {r[0]: r[1] for r in rows}


def should_propose(correction_threshold: int = 3) -> bool:
    """近 14 天 correction 信号 ≥ threshold 时，建议生成 PRESENCE 提议。"""
    stats = get_stats(14)
    return stats.get("correction", 0) >= correction_threshold


def generate_presence_proposal(cfg: dict) -> str | None:
    """
    分析最近 correction 记录，生成 PRESENCE.md 调整提议文本。
    返回提议字符串，或 None（信号不足）。
    """
    if not should_propose():
        return None

    with _conn() as c:
        rows = c.execute("""
            SELECT user_text, prev_text FROM interaction_feedback
            WHERE signal_type='correction'
            ORDER BY created_at DESC LIMIT 5
        """).fetchall()

    if not rows:
        return None

    examples = "\n".join(f"- 用户说：{r[0]}  |  Archer 之前：{r[1]}" for r in rows)
    return (
        f"[自动提议] 近期收到 {len(rows)} 条纠正信号，建议检查在场方式：\n"
        f"{examples}\n"
        "可能的调整方向：回答更简短 / 减少假设 / 先确认意图再展开。"
    )
