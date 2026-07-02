"""Obsidian Vault Bridge Phase 1: sensor state + lightweight index."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# focus 检测窗口：最近 N 分钟内修改的笔记视为"正在编辑"
FOCUS_WINDOW_MINUTES = 10
# 索引刷新间隔：短于这个间隔不重复全量扫描
REFRESH_COOLDOWN_SECONDS = 30
# 单次索引扫描上限（防超大 vault 卡死）
MAX_INDEX_NOTES = 10000
MAX_SENSOR_EXCERPT_CHARS = 2000
MAX_CONTEXT_CHARS = 3500


def _conn() -> sqlite3.Connection:
    import memory.store as _store
    conn = sqlite3.connect(_store.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_vault_index_table() -> None:
    """创建 vault_notes 索引表 + vault_focus 状态表。"""
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vault_notes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            path        TEXT    NOT NULL UNIQUE,
            title       TEXT    DEFAULT '',
            mtime       TEXT    NOT NULL,
            size        INTEGER DEFAULT 0,
            tags        TEXT   DEFAULT '[]',
            indexed_at  TEXT    NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vault_notes_mtime ON vault_notes(mtime DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vault_notes_path ON vault_notes(path)")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS vault_focus (
            id              INTEGER PRIMARY KEY CHECK (id = 1),
            note_path       TEXT,
            note_title      TEXT    DEFAULT '',
            excerpt         TEXT    DEFAULT '',
            selected_text   TEXT    DEFAULT '',
            visible_headings TEXT   DEFAULT '[]',
            tags            TEXT   DEFAULT '[]',
            detected_at     TEXT    NOT NULL,
            detection_method TEXT   DEFAULT 'mtime'
        )
    """)
    _ensure_focus_columns(conn)
    conn.commit()
    conn.close()


def _ensure_focus_columns(conn: sqlite3.Connection) -> None:
    """Backfill columns for vault_focus created by earlier Phase 1 builds."""
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(vault_focus)").fetchall()
    }
    for name, ddl in {
        "note_title": "ALTER TABLE vault_focus ADD COLUMN note_title TEXT DEFAULT ''",
        "excerpt": "ALTER TABLE vault_focus ADD COLUMN excerpt TEXT DEFAULT ''",
        "selected_text": "ALTER TABLE vault_focus ADD COLUMN selected_text TEXT DEFAULT ''",
        "visible_headings": "ALTER TABLE vault_focus ADD COLUMN visible_headings TEXT DEFAULT '[]'",
        "tags": "ALTER TABLE vault_focus ADD COLUMN tags TEXT DEFAULT '[]'",
    }.items():
        if name not in existing:
            conn.execute(ddl)


def refresh_index(force: bool = False) -> dict:
    """全量扫描 vault，更新 vault_notes 索引。

    force=False 时受 REFRESH_COOLDOWN_SECONDS 限制，避免频繁扫描。
    """
    from skills._vault import resolve_vault, walk_notes, read_note, parse_frontmatter
    import json
    import time

    init_vault_index_table()

    vault = resolve_vault()
    if vault is None:
        return {"ok": False, "reason": "Obsidian vault 未配置"}

    # cooldown 检查（索引表为空时首次扫描绕过 cooldown）
    if not force:
        conn = _conn()
        row = conn.execute(
            "SELECT indexed_at FROM vault_notes ORDER BY indexed_at DESC LIMIT 1"
        ).fetchone()
        # 统计索引行数，0 表示首次扫描
        count_row = conn.execute("SELECT COUNT(*) AS c FROM vault_notes").fetchone()
        conn.close()
        existing_count = count_row["c"] if count_row else 0
        if existing_count > 0 and row:
            try:
                last = datetime.fromisoformat(row["indexed_at"])
                if (datetime.now() - last).total_seconds() < REFRESH_COOLDOWN_SECONDS:
                    return {
                        "ok": True,
                        "skipped": True,
                        "reason": f"索引冷却中（{REFRESH_COOLDOWN_SECONDS}s 内不重复）",
                    }
            except Exception:
                pass

    count = 0
    now_str = datetime.now().isoformat(timespec="seconds")
    conn = _conn()
    for path in walk_notes(vault):
        if count >= MAX_INDEX_NOTES:
            break
        try:
            stat = path.stat()
            content = read_note(path)
            props, _ = parse_frontmatter(content)
            title = props.get("title") or path.stem
            tags_raw = props.get("tags", [])
            if isinstance(tags_raw, str):
                # 支持 YAML inline array: [a, b, c]
                s = tags_raw.strip()
                if s.startswith("[") and s.endswith("]"):
                    inner = s[1:-1]
                    tags_raw = [
                        t.strip().strip('"').strip("'")
                        for t in inner.split(",") if t.strip()
                    ] if inner.strip() else []
                else:
                    tags_raw = [tags_raw]
            tags_json = json.dumps(tags_raw, ensure_ascii=False)
            mtime = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
            conn.execute(
                """INSERT INTO vault_notes (path, title, mtime, size, tags, indexed_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(path) DO UPDATE SET
                     title=excluded.title,
                     mtime=excluded.mtime,
                     size=excluded.size,
                     tags=excluded.tags,
                     indexed_at=excluded.indexed_at""",
                (str(path.relative_to(vault)), title, mtime, stat.st_size, tags_json, now_str),
            )
            count += 1
        except Exception:
            continue

    conn.commit()
    conn.close()
    return {"ok": True, "indexed": count, "vault": str(vault)}


def detect_current_focus() -> dict:
    """检测用户当前正在编辑哪篇笔记。

    策略：找 vault_notes 索引中 mtime 最近的笔记，
    且满足：
    1. mtime 在 FOCUS_WINDOW_MINUTES 内（10 分钟内）
    2. mtime 距"现在"至少 1 秒（避免 iCloud 同步漂移把 mtime 写成未来时间）
    3. 文件非空（size > 0，避免把刚创建的空笔记误判为 focus）
    超出窗口返回 None（用户没在编辑）。
    """
    init_vault_index_table()
    now = datetime.now()
    cutoff = now - timedelta(minutes=FOCUS_WINDOW_MINUTES)
    cutoff_str = cutoff.isoformat(timespec="seconds")
    # 下限：mtime 不能晚于 now + 1 秒（容忍小幅时钟漂移，但拒绝未来时间）
    future_limit = (now + timedelta(seconds=1)).isoformat(timespec="seconds")

    conn = _conn()
    row = conn.execute(
        "SELECT path, title, mtime, size FROM vault_notes "
        "WHERE mtime > ? AND mtime < ? AND size > 0 "
        "ORDER BY mtime DESC LIMIT 1",
        (cutoff_str, future_limit),
    ).fetchone()

    if not row:
        # 没有最近修改的笔记。但如果现有缓存是 sensor 来源（Obsidian 插件显式推送）
        # 且仍在 2x 窗口内，保留 sensor 数据，不清空——
        # 因为 sensor focus 反映用户"正在看哪篇笔记"，不依赖文件 mtime。
        existing = conn.execute("SELECT * FROM vault_focus WHERE id=1").fetchone()
        if existing and existing["note_path"] and existing["detection_method"] == "sensor":
            try:
                last = datetime.fromisoformat(existing["detected_at"])
                if now - last < timedelta(minutes=FOCUS_WINDOW_MINUTES * 2):
                    conn.close()
                    return {
                        "focused": True,
                        "note_path": existing["note_path"],
                        "note_title": existing["note_title"],
                        "detected_at": existing["detected_at"],
                        "detection_method": "sensor",
                        "reason": "sensor 缓存仍在 2x 窗口内，保留",
                    }
            except Exception:
                pass
        # sensor 缓存也过期了，清空
        _store_focus(conn, None, "", "", "", [], [], "mtime")
        conn.commit()
        conn.close()
        return {
            "focused": False,
            "note_path": None,
            "reason": f"最近 {FOCUS_WINDOW_MINUTES} 分钟内无修改的笔记",
        }

    detected_at = now.isoformat(timespec="seconds")
    _store_focus(conn, row["path"], row["title"], "", "", [], [], "mtime", detected_at=detected_at)
    conn.commit()
    conn.close()

    return {
        "focused": True,
        "note_path": row["path"],
        "note_title": row["title"],
        "mtime": row["mtime"],
        "detected_at": detected_at,
        "detection_method": "mtime",
    }


def get_current_focus() -> dict:
    """读取上次检测到的 focus 状态（不主动检测）。"""
    init_vault_index_table()
    conn = _conn()
    row = conn.execute("SELECT * FROM vault_focus WHERE id=1").fetchone()
    conn.close()

    if not row or not row["note_path"]:
        return {"focused": False, "note_path": None}

    note_title = row["note_title"] or ""
    if not note_title:
        conn = _conn()
        note_row = conn.execute(
            "SELECT title FROM vault_notes WHERE path=?", (row["note_path"],)
        ).fetchone()
        conn.close()
        note_title = note_row["title"] if note_row else ""

    return {
        "focused": True,
        "note_path": row["note_path"],
        "note_title": note_title,
        "excerpt": row["excerpt"] or "",
        "selected_text": row["selected_text"] or "",
        "visible_headings": _json_list(row["visible_headings"]),
        "tags": _json_list(row["tags"]),
        "detected_at": row["detected_at"],
        "detection_method": row["detection_method"],
    }


def ingest_focus_event(payload: dict) -> dict:
    """Record an explicit Obsidian focus event.

    This is the real sensor path. The older mtime detector remains only as a
    fallback for machines without an Obsidian plugin.
    """
    from skills._vault import resolve_vault, resolve_note_path, read_note, parse_frontmatter

    init_vault_index_table()
    vault = resolve_vault()
    if vault is None:
        return {"ok": False, "reason": "Obsidian vault 未配置"}

    raw_path = str(
        payload.get("file_path")
        or payload.get("filePath")
        or payload.get("path")
        or ""
    ).strip()
    if not raw_path:
        return {"ok": False, "reason": "file_path is required"}

    try:
        note = resolve_note_path(raw_path)
        rel_path = str(note.relative_to(vault))
    except Exception as exc:
        return {"ok": False, "reason": f"路径被拒绝：{exc}"}

    title = str(payload.get("title") or note.stem).strip()
    selected_text = _trim_text(payload.get("selected_text") or payload.get("selectedText") or "", 1000)
    excerpt = _trim_text(payload.get("content_preview") or payload.get("contentPreview") or payload.get("excerpt") or "", MAX_SENSOR_EXCERPT_CHARS)
    headings = _as_string_list(payload.get("visible_headings") or payload.get("visibleHeadings"))
    tags = _as_string_list(payload.get("tags"))

    if note.exists() and note.is_file():
        try:
            content = read_note(note)
            props, body = parse_frontmatter(content)
            if not title:
                title = str(props.get("title") or note.stem)
            if not tags:
                tags = _normalize_tags(props.get("tags"))
            if not excerpt:
                excerpt = _trim_text(selected_text or _first_meaningful_excerpt(body), MAX_SENSOR_EXCERPT_CHARS)
            stat = note.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
            conn = _conn()
            conn.execute(
                """INSERT INTO vault_notes (path, title, mtime, size, tags, indexed_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(path) DO UPDATE SET
                     title=excluded.title,
                     mtime=excluded.mtime,
                     size=excluded.size,
                     tags=excluded.tags,
                     indexed_at=excluded.indexed_at""",
                (
                    rel_path,
                    title or note.stem,
                    mtime,
                    stat.st_size,
                    json.dumps(tags, ensure_ascii=False),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            _store_focus(conn, rel_path, title or note.stem, excerpt, selected_text, headings, tags, "sensor")
            conn.commit()
            conn.close()
        except Exception as exc:
            return {"ok": False, "reason": f"focus event failed: {exc}"}
    else:
        conn = _conn()
        _store_focus(conn, rel_path, title or note.stem, excerpt, selected_text, headings, tags, "sensor")
        conn.commit()
        conn.close()

    focus = get_current_focus()
    return {"ok": True, "focus": focus}


def build_focus_context(max_chars: int = MAX_CONTEXT_CHARS) -> tuple[str, dict | None]:
    """Return prompt-ready context for the current Obsidian focus.

    Phase 3 自动注入：如果缓存 focus 已过期（detected_at 早于 FOCUS_WINDOW），
    主动调 detect_current_focus() 刷新一次。这样无 Obsidian sensor 插件时
    也能靠 mtime fallback 自动维持 focus 新鲜度。
    """
    from skills._vault import resolve_vault, resolve_note_path, read_note

    focus = get_current_focus()
    if focus.get("focused"):
        # 检查 detected_at 是否过期
        detected_at = str(focus.get("detected_at") or "")
        if detected_at:
            try:
                last = datetime.fromisoformat(detected_at)
                if datetime.now() - last > timedelta(minutes=FOCUS_WINDOW_MINUTES):
                    # 过期了，主动刷新一次
                    focus = detect_current_focus()
            except Exception:
                pass
    else:
        # 没缓存 focus，主动 detect 一次（fallback 路径）
        focus = detect_current_focus()

    if not focus.get("focused"):
        return "", None

    note_path = str(focus.get("note_path") or "")
    if not note_path:
        return "", None

    excerpt = str(focus.get("selected_text") or focus.get("excerpt") or "")
    if not excerpt:
        try:
            vault = resolve_vault()
            if vault is None:
                return "", None
            note = resolve_note_path(note_path)
            excerpt = _first_meaningful_excerpt(read_note(note))
        except Exception:
            excerpt = ""
    excerpt = _trim_text(excerpt, max_chars)
    if not excerpt:
        return "", None

    source = {
        "title": focus.get("note_title") or Path(note_path).stem,
        "path": note_path,
        "score": 1.0 if focus.get("detection_method") == "sensor" else 0.65,
        "reason": "当前 Obsidian focus" if focus.get("detection_method") == "sensor" else "最近修改的 Obsidian 笔记",
        "detection_method": focus.get("detection_method"),
    }
    context = (
        "以下是 Obsidian 当前聚焦笔记的只读上下文。"
        "它用于理解用户此刻正在处理的内容；除非用户要求，不要机械复述来源。\n\n"
        f"标题：{source['title']}\n"
        f"路径：{note_path}\n"
        f"来源：{source['reason']}\n\n"
        f"{excerpt}"
    )
    return context, source


def search_indexed_notes(keyword: str = "", limit: int = 20) -> list[dict]:
    """从索引快速搜索笔记（不读文件，只用索引表）。"""
    init_vault_index_table()
    limit = max(1, min(int(limit), 100))
    conn = _conn()

    if keyword:
        like = f"%{keyword}%"
        rows = conn.execute(
            "SELECT path, title, mtime, size, tags FROM vault_notes "
            "WHERE path LIKE ? OR title LIKE ? "
            "ORDER BY mtime DESC LIMIT ?",
            (like, like, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT path, title, mtime, size, tags FROM vault_notes "
            "ORDER BY mtime DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()

    import json
    results = []
    for row in rows:
        try:
            tags = json.loads(row["tags"] or "[]")
        except Exception:
            tags = []
        results.append({
            "path": row["path"],
            "title": row["title"],
            "mtime": row["mtime"],
            "size": row["size"],
            "tags": tags,
        })
    return results


def _store_focus(
    conn: sqlite3.Connection,
    note_path: str | None,
    note_title: str,
    excerpt: str,
    selected_text: str,
    visible_headings: list[str],
    tags: list[str],
    detection_method: str,
    *,
    detected_at: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO vault_focus
           (id, note_path, note_title, excerpt, selected_text, visible_headings, tags, detected_at, detection_method)
           VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             note_path=excluded.note_path,
             note_title=excluded.note_title,
             excerpt=excluded.excerpt,
             selected_text=excluded.selected_text,
             visible_headings=excluded.visible_headings,
             tags=excluded.tags,
             detected_at=excluded.detected_at,
             detection_method=excluded.detection_method""",
        (
            note_path,
            note_title,
            excerpt,
            selected_text,
            json.dumps(visible_headings, ensure_ascii=False),
            json.dumps(tags, ensure_ascii=False),
            detected_at or datetime.now().isoformat(timespec="seconds"),
            detection_method,
        ),
    )


def _trim_text(value: object, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"\n\n...（已截断，共 {len(text)} 字符）"


def _as_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()][:20]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _json_list(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except Exception:
        return []
    return _as_string_list(parsed)


def _normalize_tags(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        raw = value.strip()
        if raw.startswith("[") and raw.endswith("]"):
            return [
                item.strip().strip('"').strip("'")
                for item in raw[1:-1].split(",")
                if item.strip()
            ]
        if raw:
            return [raw]
    return []


def _first_meaningful_excerpt(text: str, limit: int = MAX_SENSOR_EXCERPT_CHARS) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if lines:
                lines.append("")
            continue
        if stripped.startswith(("---", "%%")):
            continue
        lines.append(stripped)
        if sum(len(item) for item in lines) >= limit:
            break
    return _trim_text("\n".join(lines).strip(), limit)
