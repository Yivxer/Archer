import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "archer.db"

MEMORY_TYPES = [
    "identity",   # 身份信息（我是谁、价值观）
    "preference", # 偏好（做事方式、沟通风格）
    "project",    # 项目（进展、卡点）
    "decision",   # 决策（做了哪个选择、为什么）
    "todo",       # 待办
    "insight",    # 洞察（学到了什么）
    "risk",       # 风险（潜在问题）
    "context",    # 临时上下文
    "reflection", # 复盘摘要（/reflect 产出，不自动注入上下文）
]

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            content      TEXT    NOT NULL,
            tags         TEXT    DEFAULT '',
            type         TEXT    DEFAULT 'insight',
            importance   INTEGER DEFAULT 3,
            status       TEXT    DEFAULT 'active',
            source       TEXT    DEFAULT '',
            created_at   TEXT    NOT NULL,
            updated_at   TEXT    NOT NULL,
            archived_at  TEXT,
            scope        TEXT    DEFAULT 'user',
            confidence   REAL    DEFAULT 0.8,
            last_used_at TEXT,
            valid_until  TEXT
        )
    """)
    # 为已有数据库补列（幂等）
    for ddl in [
        "ALTER TABLE memories ADD COLUMN type TEXT DEFAULT 'insight'",
        "ALTER TABLE memories ADD COLUMN status TEXT DEFAULT 'active'",
        "ALTER TABLE memories ADD COLUMN archived_at TEXT",
        "ALTER TABLE memories ADD COLUMN scope TEXT DEFAULT 'user'",
        "ALTER TABLE memories ADD COLUMN confidence REAL DEFAULT 0.8",
        "ALTER TABLE memories ADD COLUMN last_used_at TEXT",
        "ALTER TABLE memories ADD COLUMN valid_until TEXT",
    ]:
        try:
            conn.execute(ddl)
        except Exception:
            pass
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
            content, tags,
            content='memories', content_rowid='id',
            tokenize='trigram'
        )
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts(rowid, content, tags) VALUES (new.id, new.content, new.tags);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, content, tags) VALUES ('delete', old.id, old.content, old.tags);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, content, tags) VALUES ('delete', old.id, old.content, old.tags);
            INSERT INTO memories_fts(rowid, content, tags) VALUES (new.id, new.content, new.tags);
        END
    """)
    # 同步已有数据到 FTS 索引（幂等）
    conn.execute("INSERT OR IGNORE INTO memories_fts(memories_fts) VALUES ('rebuild')")
    # pending_memories：待用户确认的候选记忆，进程崩溃也不丢失
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_memories (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            content    TEXT    NOT NULL,
            type       TEXT    DEFAULT 'insight',
            importance INTEGER DEFAULT 3,
            tags       TEXT    DEFAULT '',
            source     TEXT    DEFAULT 'auto',
            confidence REAL    DEFAULT 0.7,
            created_at TEXT    NOT NULL
        )
    """)
    try:
        conn.execute("ALTER TABLE pending_memories ADD COLUMN confidence REAL DEFAULT 0.7")
    except Exception:
        pass
    # themes：跨会话行为模式归纳
    conn.execute("""
        CREATE TABLE IF NOT EXISTS themes (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            name             TEXT    NOT NULL,
            description      TEXT    DEFAULT '',
            category         TEXT    DEFAULT 'behavior',
            occurrence_count INTEGER DEFAULT 1,
            last_seen_at     TEXT    NOT NULL,
            created_at       TEXT    NOT NULL
        )
    """)
    # memory_links：记忆与主题的多对多关联
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_links (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id   INTEGER NOT NULL,
            theme_id    INTEGER NOT NULL,
            strength    REAL    DEFAULT 0.5,
            created_at  TEXT    NOT NULL,
            UNIQUE(memory_id, theme_id)
        )
    """)
    conn.commit()
    conn.close()

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")

def save(content: str, tags: str = "", type: str = "insight", importance: int = 3,
         source: str = "", scope: str = "user", confidence: float = 0.8,
         valid_until: str | None = None) -> int:
    content = content.strip()
    tags = tags.strip()
    if type not in MEMORY_TYPES:
        type = "insight"
    try:
        importance = int(importance)
    except Exception:
        importance = 3
    importance = max(1, min(5, importance))

    conn = sqlite3.connect(DB_PATH)
    existing = conn.execute(
        "SELECT id FROM memories WHERE content = ? AND status = 'active' LIMIT 1",
        (content,),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE memories SET importance = MAX(importance, ?), updated_at = ? WHERE id = ?",
            (importance, _now(), existing[0]),
        )
        conn.commit()
        conn.close()
        return existing[0]

    cur = conn.execute(
        "INSERT INTO memories (content, tags, type, importance, source, scope, confidence, valid_until, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (content, tags, type, importance, source, scope, confidence, valid_until, _now(), _now()),
    )
    conn.commit()
    mid = cur.lastrowid
    conn.close()
    return mid

def _row_to_dict(r, has_date: bool = False) -> dict:
    d = {"id": r[0], "content": r[1], "tags": r[2], "type": r[3], "importance": r[4]}
    idx = 5
    if has_date:
        d["created_at"] = r[idx]; idx += 1
    d["confidence"] = r[idx] if idx < len(r) else 0.8
    d["valid_until"] = r[idx + 1] if idx + 1 < len(r) else None
    return d

def list_all(limit: int = 50) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, content, tags, type, importance, created_at, confidence, valid_until FROM memories "
        "WHERE status = 'active' ORDER BY importance DESC, updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r, has_date=True) for r in rows]

def search(keyword: str, limit: int = 10) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            "SELECT m.id, m.content, m.tags, m.type, m.importance, m.created_at, m.confidence, m.valid_until "
            "FROM memories_fts f JOIN memories m ON f.rowid = m.id "
            "WHERE memories_fts MATCH ? AND m.status = 'active' "
            "ORDER BY m.importance DESC, rank LIMIT ?",
            (keyword, limit),
        ).fetchall()
    except Exception:
        like = f"%{keyword}%"
        rows = conn.execute(
            "SELECT id, content, tags, type, importance, created_at, confidence, valid_until FROM memories "
            "WHERE status = 'active' AND (content LIKE ? OR tags LIKE ?) "
            "ORDER BY importance DESC LIMIT ?",
            (like, like, limit),
        ).fetchall()
    conn.close()
    return [_row_to_dict(r, has_date=True) for r in rows]

def delete(mid: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM memories WHERE id = ?", (mid,))
    conn.commit()
    conn.close()

def update(mid: int, content: str, tags: str | None = None,
           type: str | None = None, importance: int | None = None) -> bool:
    fields = ["content = ?", "updated_at = ?"]
    values: list = [content.strip(), _now()]

    if tags is not None:
        fields.append("tags = ?")
        values.append(tags.strip())
    if type is not None:
        fields.append("type = ?")
        values.append(type if type in MEMORY_TYPES else "insight")
    if importance is not None:
        fields.append("importance = ?")
        values.append(max(1, min(5, int(importance))))

    values.append(mid)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        f"UPDATE memories SET {', '.join(fields)} WHERE id = ? AND status = 'active'",
        values,
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok

def archive(mid: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "UPDATE memories SET status = 'archived', archived_at = ?, updated_at = ? "
        "WHERE id = ? AND status = 'active'",
        (_now(), _now(), mid),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok

def recent(limit: int = 5) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, content, tags, type, importance, confidence, valid_until FROM memories "
        "WHERE status = 'active' ORDER BY importance DESC, updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]

def high_importance(min_importance: int = 4, limit: int = 3) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, content, tags, type, importance, confidence, valid_until FROM memories "
        "WHERE status = 'active' AND importance >= ? "
        "AND type IN ('identity', 'preference', 'project', 'decision') "
        "ORDER BY importance DESC, updated_at DESC LIMIT ?",
        (min_importance, limit),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def update_last_used(mid: int):
    """更新记忆的最后使用时间，用于 retrieve 调用后追踪活跃度。"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE memories SET last_used_at = ? WHERE id = ?", (_now(), mid))
    conn.commit()
    conn.close()


# ── Pending Memories（持久化候选记忆）─────────────────────────────────────────

def add_pending(content: str, type: str = "insight", importance: int = 3,
                tags: str = "", source: str = "auto", confidence: float = 0.7) -> int:
    """将候选记忆写入 pending_memories 表，返回 ID。"""
    content = content.strip()
    if type not in MEMORY_TYPES:
        type = "insight"
    try:
        importance = max(1, min(5, int(importance)))
    except Exception:
        importance = 3

    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "INSERT INTO pending_memories (content, type, importance, tags, source, confidence, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (content, type, importance, tags.strip(), source, float(confidence), _now()),
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def list_pending(limit: int = 50) -> list[dict]:
    """返回所有待确认记忆。"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, content, type, importance, tags, source, confidence, created_at "
        "FROM pending_memories ORDER BY id LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [
        {
            "id": r[0], "content": r[1], "type": r[2],
            "importance": r[3], "tags": r[4], "source": r[5],
            "confidence": r[6], "created_at": r[7],
        }
        for r in rows
    ]


def count_pending() -> int:
    """返回待确认记忆数量。"""
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM pending_memories").fetchone()[0]
    conn.close()
    return n


def accept_pending(pid: int | str) -> list[int]:
    """
    接受待确认记忆，写入主 memories 表并从 pending 中删除。
    pid 可以是具体 ID 或 "all"。返回写入的 memory ID 列表。
    """
    conn = sqlite3.connect(DB_PATH)
    if str(pid) == "all":
        rows = conn.execute(
            "SELECT id, content, type, importance, tags, source, confidence FROM pending_memories"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, content, type, importance, tags, source, confidence FROM pending_memories WHERE id = ?",
            (int(pid),),
        ).fetchall()
    conn.close()

    if not rows:
        return []

    memory_ids = []
    accepted_pids = []
    for row in rows:
        p_id, content, type_, importance, tags, source, confidence = row
        mid = save(content, tags=tags, type=type_, importance=importance, source=source, confidence=confidence)
        memory_ids.append(mid)
        accepted_pids.append(p_id)

    conn = sqlite3.connect(DB_PATH)
    if str(pid) == "all":
        conn.execute("DELETE FROM pending_memories")
    else:
        conn.execute("DELETE FROM pending_memories WHERE id = ?", (int(pid),))
    conn.commit()
    conn.close()

    return memory_ids


def reject_pending(pid: int | str) -> int:
    """
    丢弃待确认记忆。pid 可以是具体 ID 或 "all"。返回删除数量。
    """
    conn = sqlite3.connect(DB_PATH)
    if str(pid) == "all":
        n = conn.execute("SELECT COUNT(*) FROM pending_memories").fetchone()[0]
        conn.execute("DELETE FROM pending_memories")
    else:
        cur = conn.execute("DELETE FROM pending_memories WHERE id = ?", (int(pid),))
        n = cur.rowcount
    conn.commit()
    conn.close()
    return n


# ── Themes（跨会话模式归纳）─────────────────────────────────────────────────────

def save_theme(name: str, description: str = "", category: str = "behavior") -> int:
    """保存或更新一个主题，重名时增加 occurrence_count。返回 theme ID。"""
    name = name.strip()
    conn = sqlite3.connect(DB_PATH)
    existing = conn.execute(
        "SELECT id FROM themes WHERE name = ? LIMIT 1", (name,)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE themes SET occurrence_count = occurrence_count + 1, "
            "last_seen_at = ?, description = CASE WHEN ? != '' THEN ? ELSE description END "
            "WHERE id = ?",
            (_now(), description, description, existing[0]),
        )
        conn.commit()
        tid = existing[0]
    else:
        cur = conn.execute(
            "INSERT INTO themes (name, description, category, occurrence_count, last_seen_at, created_at) "
            "VALUES (?, ?, ?, 1, ?, ?)",
            (name, description.strip(), category, _now(), _now()),
        )
        conn.commit()
        tid = cur.lastrowid
    conn.close()
    return tid


def list_themes(limit: int = 20) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, name, description, category, occurrence_count, last_seen_at "
        "FROM themes ORDER BY occurrence_count DESC, last_seen_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "name": r[1], "description": r[2],
         "category": r[3], "occurrence_count": r[4], "last_seen_at": r[5]}
        for r in rows
    ]


def link_memory_to_theme(memory_id: int, theme_id: int, strength: float = 0.5):
    """关联记忆与主题，已存在则更新 strength。"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO memory_links (memory_id, theme_id, strength, created_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(memory_id, theme_id) DO UPDATE SET strength = excluded.strength",
        (memory_id, theme_id, float(strength), _now()),
    )
    conn.commit()
    conn.close()


def get_theme_memories(theme_id: int, limit: int = 10) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT m.id, m.content, m.tags, m.type, m.importance, m.confidence, m.valid_until, ml.strength "
        "FROM memory_links ml JOIN memories m ON ml.memory_id = m.id "
        "WHERE ml.theme_id = ? AND m.status = 'active' "
        "ORDER BY ml.strength DESC, m.importance DESC LIMIT ?",
        (theme_id, limit),
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "content": r[1], "tags": r[2], "type": r[3],
         "importance": r[4], "confidence": r[5], "valid_until": r[6], "strength": r[7]}
        for r in rows
    ]


def get_memories_for_detection(limit: int = 50) -> list[dict]:
    """返回用于主题检测的核心记忆（importance >= 3，排除 reflection/context）。"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, content, tags, type, importance, confidence, valid_until FROM memories "
        "WHERE status = 'active' AND importance >= 3 "
        "AND type NOT IN ('reflection', 'context') "
        "ORDER BY importance DESC, updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]
