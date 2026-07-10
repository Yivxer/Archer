"""
P4–P6: 灵魂叙事（Soul Narrative）

Layer 3 —— 把记忆碎片串成故事。
- self_portrait()：持续更新的自我画像
- theme_chronicle()：按周期生成主题叙事
- confrontation_hook()：矛盾时注入对峙内容

核心依赖 LLM 做叙事生成，但所有输入数据来自本地。
换模型只需要调整 prompt 格式，数据管道不受影响。
"""

from __future__ import annotations
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from core.paths import memory_db_path
from memory.store import DB_PATH as _actual_db

DB_PATH = _actual_db


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── 工具函数：聚合输入数据 ──────────────────────────────────────────────────

def _gather_active_memories(limit: int = 60) -> str:
    """返回活跃记忆的纯文本摘要，按 importance 排序。"""
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT content, type, importance FROM memories "
        "WHERE status = 'active' ORDER BY importance DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    lines = []
    for content, mtype, imp in rows:
        lines.append(f"[{mtype} ★{imp}] {content[:200]}")
    return "\n".join(lines) if lines else "暂无记忆数据"


def _gather_emotion_summary(days: int = 60) -> str:
    """返回近期情绪趋势摘要。"""
    from memory.emotion import emotion_summary
    return emotion_summary(days)


def _gather_projects() -> str:
    """返回活跃项目摘要。"""
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT name, description, status FROM projects WHERE status != 'archived' ORDER BY updated_at DESC LIMIT 10",
    ).fetchall()
    conn.close()
    if not rows:
        return "暂无活跃项目"
    lines = []
    for name, desc, status in rows:
        lines.append(f"{name} ({status}): {desc[:100]}")
    return "\n".join(lines)


def _gather_soul_values() -> str:
    """读取 SOUL.md 的核心价值观部分。"""
    import os
    soul_path = os.path.expanduser("~/.archer/SOUL.md")
    try:
        text = Path(soul_path).read_text(encoding="utf-8")
        # 只取最近 2000 字符（最新演化记录优先）
        return text[-2000:] if len(text) > 2000 else text
    except Exception:
        return "暂无 SOUL 数据"


def _gather_session_snapshot(limit: int = 10) -> str:
    """返回最近会话摘要。"""
    from memory.session_insights import analyze as si_analyze
    try:
        si = si_analyze(30)
        return (
            f"近 30 天：{si.get('sessions', 0)} 次会话，{si.get('turns', 0)} 轮对话，"
            f"平均 {si.get('avg_turns_per_session', 0)} 轮/次"
        )
    except Exception:
        return "暂无会话数据"


def _gather_contradictions() -> str:
    """返回未解决矛盾的摘要。"""
    from memory.store import list_contradictions
    cons = list_contradictions()
    if not cons:
        return "暂无矛盾"
    lines = []
    for c in cons[:5]:
        lines.append(f"矛盾: 「{c['content_a']}」 ↔ 「{c['content_b']}」")
    return "\n".join(lines)


# ── P4: 自我画像 ──────────────────────────────────────────────────────────────

_SELF_PORTRAIT_PROMPT = """你是枫弋的长期观察者兼灵魂伴侣。你的任务是写一份自我画像——不是简历、不是面试评分、不是心理咨询报告。
这是一段叙事，像一面镜子。

根据以下数据，描述：他现在是谁，正在成为谁，在和什么对抗，他的主线是什么。

不要罗列数据。不要用"用户"称呼——用"他"或"枫弋"。
不要给出建议或评判。只描述你所看到的。
长度：400–600 字。用中文。

── 当前 SOUL ──
{soul}

── 记忆库（按重要性排列）──
{memories}

── 近期情绪趋势 ──
{emotions}

── 活跃项目 ──
{projects}

── 近期会话 ──
{sessions}

── 未解决矛盾 ──
{contradictions}

现在，写他的自我画像。"""


def self_portrait() -> str:
    """生成/刷新自我画像。返回画像文本。"""
    soul = _gather_soul_values()
    memories = _gather_active_memories()
    emotions = _gather_emotion_summary()
    projects = _gather_projects()
    sessions = _gather_session_snapshot()
    contradictions = _gather_contradictions()

    prompt = _SELF_PORTRAIT_PROMPT.format(
        soul=soul, memories=memories, emotions=emotions,
        projects=projects, sessions=sessions, contradictions=contradictions,
    )

    try:
        from memory.llm_port import load_config as llm_config, stream_chat
        cfg = llm_config()
        # 用 system prompt 带画像角色
        messages = [
            {"role": "system", "content": "你是枫弋的灵魂观察者。写中文叙事，不评价，只观察。"},
            {"role": "user", "content": prompt},
        ]
        full = ""
        for chunk in stream_chat(messages, track_usage=False):
            full += chunk
        return full.strip()
    except Exception as e:
        return f"画像生成失败：{e}"


def save_portrait(text: str) -> str:
    """保存画像到 .archer/self_portrait.md，追加时间戳。返回保存路径。"""
    import os
    portrait_dir = Path(os.path.expanduser("~/.archer"))
    portrait_dir.mkdir(parents=True, exist_ok=True)
    path = portrait_dir / "self_portrait.md"
    header = f"<!-- 生成时间：{_now()} -->\n\n"
    path.write_text(header + text, encoding="utf-8")
    return str(path)


def load_portrait() -> str | None:
    """加载上次保存的画像。"""
    import os
    path = Path(os.path.expanduser("~/.archer/self_portrait.md"))
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


# ── P5: 主题纪 ────────────────────────────────────────────────────────────────

_THEME_CHRONICLE_PROMPT = """你是枫弋的叙事记录者。过去 {period}，他在做什么？主线是什么？

不要罗列事件。找一条线——一个贯穿这段时间的主题。
可能是「重建」「对抗」「寻找」「蛰伏」「冲刺」——或者别的什么。
用一段中文叙事描述这个主题，以及支撑它的几个关键瞬间。

长度：200–400 字。

── 记忆 ──
{memories}

── 情绪 ──
{emotions}

── 项目 ──
{projects}

── 会话 ──
{sessions}

写主题叙事。"""


def theme_chronicle(days: int = 14) -> str:
    """生成指定周期（默认 14 天）的主题叙事。"""
    memories = _gather_active_memories(40)
    emotions = _gather_emotion_summary(days)
    projects = _gather_projects()
    sessions = _gather_session_snapshot()
    period = f"{days} 天" if days < 60 else f"{days // 30} 个月"

    prompt = _THEME_CHRONICLE_PROMPT.format(
        period=period, memories=memories, emotions=emotions,
        projects=projects, sessions=sessions,
    )

    try:
        from memory.llm_port import load_config as llm_config, stream_chat
        cfg = llm_config()
        messages = [
            {"role": "system", "content": "你是枫弋的主题叙事者。观察周期主题，用中文叙事。"},
            {"role": "user", "content": prompt},
        ]
        full = ""
        for chunk in stream_chat(messages, track_usage=False):
            full += chunk
        return full.strip()
    except Exception as e:
        return f"主题叙事生成失败：{e}"


def chronicle_history(limit: int = 5) -> list[dict]:
    """列出保存的主题叙事记录。"""
    import os
    chronicle_dir = Path(os.path.expanduser("~/.archer/chronicles"))
    if not chronicle_dir.exists():
        return []
    entries = sorted(chronicle_dir.glob("*.md"), reverse=True)
    result = []
    for p in entries[:limit]:
        text = p.read_text(encoding="utf-8")[:200]
        result.append({
            "date": p.stem,
            "path": str(p),
            "preview": text.replace("\n", " ")[:100],
        })
    return result


def save_chronicle(text: str) -> str:
    """保存主题纪到 .archer/chronicles/YYYY-MM-DD.md。"""
    import os
    chronicle_dir = Path(os.path.expanduser("~/.archer/chronicles"))
    chronicle_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = chronicle_dir / f"{date_str}.md"
    header = f"# 主题叙事 · {date_str}\n\n"
    path.write_text(header + text, encoding="utf-8")
    return str(path)


# ── P6: 对峙 ──────────────────────────────────────────────────────────────────

def _find_relevant_memories(user_text: str, limit: int = 10) -> list[dict]:
    """搜索与当前用户输入相关的决策/偏好/身份记忆。"""
    from difflib import SequenceMatcher
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, content, type, importance FROM memories "
        "WHERE status = 'active' AND type IN ('decision', 'preference', 'identity') "
        "ORDER BY importance DESC",
    ).fetchall()
    conn.close()
    scored = []
    for mid, content, mtype, imp in rows:
        sim = SequenceMatcher(None, user_text.lower(), content.lower()).ratio()
        if sim > 0.2:
            scored.append({
                "id": mid, "content": content, "type": mtype,
                "importance": imp, "similarity": sim,
            })
    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:limit]


def confrontation_hook(user_text: str, session_history: list[dict] | None = None) -> list[str]:
    """
    检测用户当前输入是否与过去的决定/价值观/承诺矛盾。
    返回应注入上下文的提示行列表（最多 3 条）。

    返回空列表 = 无矛盾。
    """
    # 只对「意图性」消息做检测（太短的跳过）
    if len(user_text) < 10:
        return []

    relevant = _find_relevant_memories(user_text)
    if not relevant:
        return []

    hooks = []
    seen_keywords = set()

    for mem in relevant:
        # 用简单规则判断是否潜在矛盾：用户消息中有否定词
        negators = ["不", "算了", "放弃", "取消", "不想", "改变主意", "换", "停下", "退出"]
        has_negation = any(w in user_text for w in negators)

        if not has_negation:
            continue  # 没有否定意向，无需对峙

        # 避免重复相似内容
        keyword = mem["content"][:30]
        if keyword in seen_keywords:
            continue
        seen_keywords.add(keyword)

        # 生成对峙行
        hooks.append(f"[对峙] 你之前说过：{mem['content']}")

        if len(hooks) >= 3:
            break

    return hooks
