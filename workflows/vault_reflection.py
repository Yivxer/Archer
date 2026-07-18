"""
vault_reflection.py — Obsidian 笔记后台结晶（Vault Bridge Phase 2 核心）

把 Obsidian 笔记喂给 LLM 提炼，输出进入 Memory pending，不自动写回 Obsidian。
提炼维度（对应计划 §7.3）：
  - 核心观点 → pending (type=insight)
  - 核心矛盾 → pending (type=value_conflict)
  - 情绪模式 → pending (type=emotion_pattern)
  - 可复利方法论 → pending (type=insight)
  - 长期主题 → pending (type=life_theme)
  - 高置信度 → soul_proposal

触发方式（Phase 1 Sensor 未实现，暂不依赖 focus event）：
  - 手动指定单篇笔记 reflect_on_note(path)
  - 扫描最近 N 天修改的笔记 reflect_on_recent(days=7)

cooldown：同一篇笔记 COOLDOWN_HOURS 内不重复结晶，除非 force=True。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# 同一篇笔记的最短结晶间隔
COOLDOWN_HOURS = 12
# 单篇笔记喂给 LLM 的最大字符数
MAX_NOTE_CHARS = 8000
# 批量扫描时单次最多结晶笔记数
MAX_BATCH_NOTES = 5
# 最近修改的最小字数门槛（太短的笔记不值得结晶）
MIN_NOTE_CHARS = 200


def _now() -> datetime:
    return datetime.now()


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).isoformat(timespec="seconds")


def _conn() -> sqlite3.Connection:
    import memory.store as _store
    conn = sqlite3.connect(_store.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_reflections_table() -> None:
    """创建 vault_reflections 表（记录每次结晶，用于 cooldown 和展示）。"""
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vault_reflections (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            note_path       TEXT    NOT NULL,
            note_hash       TEXT    NOT NULL,
            note_title      TEXT    DEFAULT '',
            reflected_at    TEXT    NOT NULL,
            insights_count  INTEGER DEFAULT 0,
            pending_ids     TEXT    DEFAULT '[]',
            soul_proposal_id INTEGER,
            confidence      REAL    DEFAULT 0.0,
            summary         TEXT    DEFAULT ''
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_vault_reflections_path "
        "ON vault_reflections(note_path)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_vault_reflections_time "
        "ON vault_reflections(reflected_at DESC)"
    )
    conn.commit()
    conn.close()


def _note_hash(content: str) -> str:
    return hashlib.md5(content.encode("utf-8")).hexdigest()[:16]


def _is_on_cooldown(note_path: str, now: datetime | None = None) -> tuple[bool, str]:
    """检查某篇笔记是否在冷却期内。返回 (是否冷却中, 上次结晶时间)。"""
    base = now or _now()
    cutoff = _stamp(base - timedelta(hours=COOLDOWN_HOURS))
    conn = _conn()
    row = conn.execute(
        "SELECT reflected_at FROM vault_reflections "
        "WHERE note_path=? AND reflected_at > ? "
        "ORDER BY reflected_at DESC LIMIT 1",
        (note_path, cutoff),
    ).fetchone()
    conn.close()
    if row:
        return True, row["reflected_at"]
    return False, ""


def _call_llm_reflect(content: str, title: str) -> Optional[dict]:
    """调 LLM 提炼笔记，返回结构化结果。失败返回 None，并打印日志。"""
    truncated = content[:MAX_NOTE_CHARS]
    if len(content) > MAX_NOTE_CHARS:
        truncated += f"\n\n…（已截断，原文共 {len(content)} 字符）"

    try:
        from core.llm import stream_chat
    except Exception as e:
        print(f"[vault_reflection] import stream_chat failed: {e}", file=sys.stderr)
        return None

    messages = [
        {
            "role": "system",
            "content": (
                "你是一个深度阅读助手。阅读用户的 Obsidian 笔记，提炼出值得长期保留的洞察。"
                "只提炼笔记中明确表达或强烈暗示的内容，不要编造。"
                "如果笔记内容太碎、太短、没有可提炼的价值，所有字段留空，confidence 设为 0。"
                "严格返回 JSON，不要包裹 markdown 代码块。\n\n"
                "JSON 结构：\n"
                "{\n"
                '  "core_insight": "核心观点，一句话",\n'
                '  "core_tension": "笔记中体现的核心矛盾或张力，没有则留空",\n'
                '  "emotion_pattern": "情绪或心理模式，没有则留空",\n'
                '  "reusable_method": "可复利的方法论或做法，没有则留空",\n'
                '  "life_theme": "如果这篇笔记指向一个长期主题，写出主题名，没有则留空",\n'
                '  "related_threads": ["相关线索1", "线索2"],\n'
                '  "confidence": 0.0到1.0的浮点数，表示提炼置信度,\n'
                '  "soul_worthy": true或false，是否值得进入人格档案,\n'
                '  "soul_note": "如果 soul_worthy 为 true，写出建议追加到 SOUL.md 的一句话，否则留空"\n'
                "}"
            ),
        },
        {
            "role": "user",
            "content": f"笔记标题：{title}\n\n笔记内容：\n{truncated}",
        },
    ]

    result = ""
    try:
        for chunk in stream_chat(messages, track_usage=False):
            result += chunk
    except Exception as e:
        print(f"[vault_reflection] stream_chat failed: {e}", file=sys.stderr)
        return None

    parsed = _parse_llm_json(result)
    if parsed is None:
        print(f"[vault_reflection] JSON parse failed (first 200 chars): {result[:200]}", file=sys.stderr)
    return parsed


def _parse_llm_json(raw: str) -> Optional[dict]:
    """解析 LLM 返回的 JSON，容错处理 markdown 包裹和多余文本。"""
    text = raw.strip()
    # 去掉 markdown 代码块包裹
    if text.startswith("```"):
        lines = text.splitlines()
        # 去掉首尾的 ``` 行
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # 尝试提取第一个 { 到最后一个 } 之间的内容
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
        else:
            return None

    if not isinstance(data, dict):
        return None
    return data


def _save_reflection_to_memory(result: dict, note_path: str, note_title: str) -> dict:
    """把提炼结果存入 Memory pending 和 Soul proposal。返回创建的 ID 列表。"""
    import memory.store as store

    pending_ids: list[int] = []
    confidence = float(result.get("confidence", 0.0) or 0.0)
    confidence = max(0.0, min(1.0, confidence))
    source = "vault_reflection"
    suggest = f"来自 Obsidian 笔记：{note_path}"

    # 核心观点
    core = (result.get("core_insight") or "").strip()
    if core:
        pid = store.add_pending(
            core, type="insight", importance=4, source=source,
            confidence=confidence, suggest_reason=suggest,
        )
        pending_ids.append(pid)

    # 核心矛盾
    tension = (result.get("core_tension") or "").strip()
    if tension:
        pid = store.add_pending(
            tension, type="value_conflict", importance=4, source=source,
            confidence=confidence, suggest_reason=suggest,
        )
        pending_ids.append(pid)

    # 情绪模式
    emotion = (result.get("emotion_pattern") or "").strip()
    if emotion:
        pid = store.add_pending(
            emotion, type="emotion_pattern", importance=3, source=source,
            confidence=confidence, suggest_reason=suggest,
        )
        pending_ids.append(pid)

    # 可复利方法论
    method = (result.get("reusable_method") or "").strip()
    if method:
        pid = store.add_pending(
            method, type="insight", importance=3, source=source,
            confidence=confidence, suggest_reason=suggest, tags="方法论",
        )
        pending_ids.append(pid)

    # 长期主题
    theme = (result.get("life_theme") or "").strip()
    if theme:
        pid = store.add_pending(
            theme, type="life_theme", importance=4, source=source,
            confidence=confidence, suggest_reason=suggest,
        )
        pending_ids.append(pid)

    # Soul proposal
    soul_proposal_id = None
    if result.get("soul_worthy") and confidence >= 0.7:
        soul_note = (result.get("soul_note") or "").strip()
        if soul_note:
            try:
                soul_proposal_id = store.add_soul_proposal(soul_note, source=source)
            except Exception:
                pass

    return {
        "pending_ids": pending_ids,
        "soul_proposal_id": soul_proposal_id,
        "confidence": confidence,
    }


def _record_reflection(
    note_path: str,
    note_hash: str,
    note_title: str,
    saved: dict,
    summary: str,
) -> int:
    """记录本次结晶到 vault_reflections 表，返回记录 ID。"""
    conn = _conn()
    cur = conn.execute(
        """INSERT INTO vault_reflections
           (note_path, note_hash, note_title, reflected_at,
            insights_count, pending_ids, soul_proposal_id, confidence, summary)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            note_path,
            note_hash,
            note_title,
            _stamp(),
            len(saved.get("pending_ids", [])),
            json.dumps(saved.get("pending_ids", [])),
            saved.get("soul_proposal_id"),
            saved.get("confidence", 0.0),
            summary[:500],
        ),
    )
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    assert rid is not None, "INSERT 未返回 lastrowid"
    return int(rid)


def reflect_on_note(note_path: str, force: bool = False) -> dict:
    """对单篇 Obsidian 笔记做结晶。

    返回 dict：{ok, skipped, reason, pending_ids, soul_proposal_id, confidence}
    """
    from skills._vault import resolve_vault, read_note, walk_notes, parse_frontmatter

    init_reflections_table()

    vault = resolve_vault()
    if vault is None:
        return {"ok": False, "reason": "Obsidian vault 未配置"}

    # 解析路径（支持相对 vault 的路径）
    raw = note_path.strip()
    p = Path(raw)
    if not p.is_absolute():
        p = vault / raw
    try:
        p = p.resolve()
        p.relative_to(vault)
    except Exception:
        return {"ok": False, "reason": f"路径不在 vault 内：{note_path}"}

    if not p.exists() or not p.suffix == ".md":
        return {"ok": False, "reason": f"笔记不存在或非 .md：{note_path}"}

    # cooldown 检查
    rel_path = str(p.relative_to(vault))
    if not force:
        cooling, last = _is_on_cooldown(rel_path)
        if cooling:
            return {
                "ok": False,
                "skipped": True,
                "reason": f"该笔记在冷却期内（上次结晶：{last}，{COOLDOWN_HOURS}h 内不重复）",
            }

    content = read_note(p)
    if len(content) < MIN_NOTE_CHARS:
        return {"ok": False, "reason": f"笔记太短（{len(content)} 字符），不值得结晶"}

    props, _ = parse_frontmatter(content)
    title = props.get("title") or p.stem

    # 调 LLM 提炼
    result = _call_llm_reflect(content, title)
    if result is None:
        return {"ok": False, "reason": "LLM 提炼失败或返回无法解析"}

    confidence = float(result.get("confidence", 0.0) or 0.0)
    # 如果 LLM 判断没有可提炼内容
    if confidence < 0.3 and not (result.get("core_insight") or "").strip():
        _record_reflection(rel_path, _note_hash(content), title, {"pending_ids": []}, "无可提炼内容")
        return {"ok": True, "skipped": True, "reason": "LLM 判断无可提炼内容", "confidence": confidence}

    # 存入 Memory pending
    saved = _save_reflection_to_memory(result, rel_path, title)

    # 生成摘要
    summary = result.get("core_insight") or title
    _record_reflection(rel_path, _note_hash(content), title, saved, summary)

    return {
        "ok": True,
        "note_path": rel_path,
        "note_title": title,
        "pending_ids": saved["pending_ids"],
        "soul_proposal_id": saved["soul_proposal_id"],
        "confidence": saved["confidence"],
        "summary": summary,
    }


def reflect_on_recent(
    days: int = 7,
    max_notes: int = MAX_BATCH_NOTES,
    force: bool = False,
    progress_callback: Optional[callable] = None,
) -> dict:
    """扫描最近 N 天修改的笔记，对每篇做结晶。

    返回 dict：{ok, reflected: [...], skipped: [...], total}

    progress_callback 可选：每完成一篇笔记后调用，传入 {"done": int, "total": int, "note_path": str, "ok": bool}。
    用于 API 层做流式进度反馈或日志记录。
    """
    from skills._vault import resolve_vault, walk_notes, read_note

    init_reflections_table()

    vault = resolve_vault()
    if vault is None:
        return {"ok": False, "reason": "Obsidian vault 未配置"}

    days = max(1, min(int(days), 90))
    max_notes = max(1, min(int(max_notes), 20))

    cutoff = datetime.now() - timedelta(days=days)
    candidates: list[tuple[Path, datetime]] = []

    for path in walk_notes(vault):
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
        except Exception:
            continue
        if mtime >= cutoff:
            # 跳过太短的
            try:
                if len(read_note(path)) < MIN_NOTE_CHARS:
                    continue
            except Exception:
                continue
            candidates.append((path, mtime))

    # 按修改时间倒序
    candidates.sort(key=lambda x: x[1], reverse=True)

    # 只取前 max_notes 篇
    batch = candidates[:max_notes]
    batch_total = len(batch)
    reflected = []
    skipped = []

    for idx, (path, mtime) in enumerate(batch, start=1):
        rel = str(path.relative_to(vault))
        result = reflect_on_note(rel, force=force)
        ok = bool(result.get("ok") and not result.get("skipped"))
        if ok:
            reflected.append(result)
        else:
            skipped.append({"note_path": rel, "reason": result.get("reason", "unknown")})

        # 进度回调
        if progress_callback is not None:
            try:
                progress_callback({
                    "done": idx,
                    "total": batch_total,
                    "note_path": rel,
                    "ok": ok,
                })
            except Exception:
                pass  # 回调失败不影响主流程

    return {
        "ok": True,
        "days": days,
        "reflected": reflected,
        "skipped": skipped,
        "total": len(reflected),
        "batch_total": batch_total,
    }


def list_recent_reflections(limit: int = 20) -> list[dict]:
    """返回最近的结晶记录。"""
    init_reflections_table()
    limit = max(1, min(int(limit), 100))
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM vault_reflections ORDER BY reflected_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    results = []
    for row in rows:
        try:
            pending_ids = json.loads(row["pending_ids"] or "[]")
        except Exception:
            pending_ids = []
        results.append({
            "id": row["id"],
            "note_path": row["note_path"],
            "note_title": row["note_title"],
            "reflected_at": row["reflected_at"],
            "insights_count": row["insights_count"],
            "pending_ids": pending_ids,
            "soul_proposal_id": row["soul_proposal_id"],
            "confidence": row["confidence"],
            "summary": row["summary"],
        })
    return results
