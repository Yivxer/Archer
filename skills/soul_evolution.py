"""
soul_evolution.py — Soul Profile 自我进化检测技能

触发 SoulProfile 进化检测流程：
1. 拉取近期高重要度 insight 类型记忆
2. 结合当前 SoulProfile，生成检查提示词
3. 将结果返回给 LLM 进行判断
"""
import sqlite3
import tomllib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from core.paths import memory_db_path
from memory.soul_profile import (
    load_soul_profile,
    build_evolution_check_prompt,
    build_stage_check_prompt,
)


SKILL: dict[str, Any] = {
    "name": "soul_evolution",
    "description": (
        "检测 Soul Profile 是否需要进化更新。"
        "从近期高重要度 insight 中判断 11 维度是否需要新增/删除/修改。"
    ),
    "version": "1.0.0",
    "author": "archer-builtin",
}


def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "soul_evolution",
            "description": (
                "检测 Soul Profile 是否需要进化更新。"
                "拉取近期（默认 14 天）高重要度（importance >= 4）insight 类型记忆，"
                "结合当前 SoulProfile 生成检查提示词。"
                "分两种模式：evolution（全维度检查）和 stage_check（仅检查阶段变化）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["evolution", "stage_check"],
                        "description": (
                            "evolution: 全维度进化检测。stage_check: 仅检测 current_life_stage 是否需要更新。"
                        ),
                    },
                    "days": {
                        "type": "integer",
                        "description": "回溯天数，默认 14。",
                    },
                    "recent_text": {
                        "type": "string",
                        "description": "近期自述文本（可选），用于 stage_check 模式提供上下文。",
                    },
                },
                "required": ["mode"],
            },
        },
    }


def _fetch_recent_insights(db_path: Path, days: int = 14) -> str:
    """从记忆库拉取近期高重要度 insight。"""
    if not db_path.is_file():
        return ""

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT content, importance, created_at
            FROM memories
            WHERE type IN ('insight', 'growth_marker', 'reflection')
              AND importance >= 4
              AND status = 'active'
              AND created_at >= ?
            ORDER BY importance DESC, created_at DESC
            LIMIT 15
            """,
            (cutoff,),
        ).fetchall()
        conn.close()

        if not rows:
            return ""

        lines = []
        for r in rows:
            date = r["created_at"][:10]
            imp = "★" * r["importance"]
            content = r["content"][:200]
            lines.append(f"[{date}] {imp} {content}")
        return "\n".join(lines)
    except Exception:
        return ""


def run(args: dict) -> str:
    mode = args.get("mode", "evolution")
    days = args.get("days", 14)
    recent_text = args.get("recent_text", "")

    cfg_path = Path(__file__).parent.parent / "archer.toml"
    with open(cfg_path, "rb") as f:
        cfg = tomllib.load(f)

    soul_profile = load_soul_profile(cfg["persona"].get("soul_profile_path", ""))

    if mode == "stage_check":
        return build_stage_check_prompt(soul_profile, recent_text=recent_text)

    # evolution mode: fetch insights + build full prompt
    db_path = Path(cfg["persona"].get("memory_db_path", memory_db_path(Path(__file__).parent / "archer.db")))
    insights = _fetch_recent_insights(db_path, days=days)

    return build_evolution_check_prompt(soul_profile, recent_insights=insights)
