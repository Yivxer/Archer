import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from core.paths import memory_db_path

DB_PATH = memory_db_path(Path(__file__).parent / "archer.db")

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
    # A4：灵魂伴生体记忆类型
    "fact",
    "emotion_pattern",
    "value",
    "value_conflict",
    "life_theme",
    "self_narrative",
    "project_mythology",
    "relationship_pattern",
    "creative_identity",
    "growth_marker",
    "reflection_anchor",
]

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")   # 支持多线程并发写
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            content      TEXT    NOT NULL,
            tags         TEXT    DEFAULT '',
            type         TEXT    DEFAULT 'insight',
            importance   INTEGER DEFAULT 3,
            depth        INTEGER DEFAULT 3,
            status       TEXT    DEFAULT 'active',
            source       TEXT    DEFAULT '',
            created_at   TEXT    NOT NULL,
            updated_at   TEXT    NOT NULL,
            archived_at  TEXT,
            scope        TEXT    DEFAULT 'user',
            confidence   REAL    DEFAULT 0.8,
            last_used_at TEXT,
            valid_until  TEXT,
            observed_at  TEXT    DEFAULT '[]'
        )
    """)
    # 为已有数据库补列（幂等）
    for ddl in [
        "ALTER TABLE memories ADD COLUMN type TEXT DEFAULT 'insight'",
        "ALTER TABLE memories ADD COLUMN status TEXT DEFAULT 'active'",
        "ALTER TABLE memories ADD COLUMN archived_at TEXT",
        "ALTER TABLE memories ADD COLUMN depth INTEGER DEFAULT 3",
        "ALTER TABLE memories ADD COLUMN scope TEXT DEFAULT 'user'",
        "ALTER TABLE memories ADD COLUMN confidence REAL DEFAULT 0.8",
        "ALTER TABLE memories ADD COLUMN last_used_at TEXT",
        "ALTER TABLE memories ADD COLUMN valid_until TEXT",
        "ALTER TABLE memories ADD COLUMN observed_at TEXT DEFAULT '[]'",
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
            depth      INTEGER DEFAULT 3,
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
    try:
        conn.execute("ALTER TABLE pending_memories ADD COLUMN depth INTEGER DEFAULT 3")
    except Exception:
        pass
    # pending_memories status 列（pending/rejected，幂等补列）
    try:
        conn.execute("ALTER TABLE pending_memories ADD COLUMN status TEXT DEFAULT 'pending'")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE pending_memories ADD COLUMN suggest_reason TEXT DEFAULT ''")
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
    # projects：多项目追踪
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL UNIQUE,
            description TEXT    DEFAULT '',
            status      TEXT    DEFAULT 'active',
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL
        )
    """)
    # project_events：项目事件日志
    conn.execute("""
        CREATE TABLE IF NOT EXISTS project_events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            event_type TEXT    NOT NULL,
            content    TEXT    NOT NULL,
            created_at TEXT    NOT NULL
        )
    """)
    # soul_proposals：SOUL.md 演化提议，用户审阅后才写入
    conn.execute("""
        CREATE TABLE IF NOT EXISTS soul_proposals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            content     TEXT    NOT NULL,
            source      TEXT    DEFAULT 'reflect',
            status      TEXT    DEFAULT 'pending',
            created_at  TEXT    NOT NULL,
            reviewed_at TEXT
        )
    """)
    # scheduled_tasks：定时任务，启动时自动检查并执行到期项
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_name   TEXT    NOT NULL,
            label        TEXT    DEFAULT '',
            interval_h   INTEGER NOT NULL,
            args_json    TEXT    DEFAULT '{}',
            enabled      INTEGER DEFAULT 1,
            last_run_at  TEXT,
            next_run_at  TEXT    NOT NULL,
            created_at   TEXT    NOT NULL,
            catchup      TEXT    DEFAULT 'latest'
        )
    """)
    # v1.3.5: scheduled_tasks catchup 列（幂等补列）
    try:
        conn.execute("ALTER TABLE scheduled_tasks ADD COLUMN catchup TEXT DEFAULT 'latest'")
    except Exception:
        pass
    # v1.2 Phase 3: session_id 列（幂等补列）
    for tbl_col in [
        ("memories",       "session_id TEXT"),
        ("project_events", "session_id TEXT"),
        ("soul_proposals", "session_id TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE {tbl_col[0]} ADD COLUMN {tbl_col[1]}")
        except Exception:
            pass
    conn.commit()
    conn.close()
    # v1.2 Phase 2: 自我批评表
    from memory.critique import init_critiques_table
    init_critiques_table()
    # v1.3 Phase 1: 技能缺口追踪表
    from memory.skill_gap import init_skill_gap_table
    init_skill_gap_table()
    from memory.workflow_crystal import init_table as init_crystal_table
    init_crystal_table()
    from memory.feedback import init_table as init_feedback_table
    init_feedback_table()
    # v1.4: Work item 任务追踪表
    from memory.work import init_work_table
    init_work_table()
    # v1.5: Sub-task 子代理任务表
    from memory.subtask import init_subtask_table
    init_subtask_table()
    # v1.5: P1/P2 记忆矛盾追踪
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contradictions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_a    INTEGER NOT NULL,
            memory_b    INTEGER NOT NULL,
            description TEXT    DEFAULT '',
            status      TEXT    DEFAULT 'open',
            created_at  TEXT    NOT NULL,
            resolved_at TEXT,
            UNIQUE(memory_a, memory_b)
        )
    """)
    # v1.5: observed_at 列幂等补列
    try:
        conn.execute("ALTER TABLE memories ADD COLUMN observed_at TEXT DEFAULT '[]'")
    except Exception:
        pass
    conn.commit()
    conn.close()
    # v1.5: P3 情绪地图
    from memory.emotion import init_emotion_table
    init_emotion_table()

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _try_embed(memory_id: int, content: str) -> None:
    """静默计算并存储记忆向量嵌入（embedder 或 sqlite-vec 未安装时跳过）。"""
    try:
        from memory.embedder import encode
        from memory.vector_store import upsert
        upsert(memory_id, encode(content))
    except Exception:
        pass


def _clamp_depth(value: object) -> int:
    try:
        depth = int(value)
    except Exception:
        depth = 3
    return max(1, min(5, depth))


def save(content: str, tags: str = "", type: str = "insight", importance: int = 3,
         source: str = "", scope: str = "user", confidence: float = 0.8,
         valid_until: str | None = None, session_id: str | None = None,
         depth: int = 3) -> int:
    content = content.strip()
    tags = tags.strip()
    if type not in MEMORY_TYPES:
        type = "insight"
    try:
        importance = int(importance)
    except Exception:
        importance = 3
    importance = max(1, min(5, importance))
    depth = _clamp_depth(depth)

    conn = sqlite3.connect(DB_PATH)
    existing = conn.execute(
        "SELECT id FROM memories WHERE content = ? AND status = 'active' LIMIT 1",
        (content,),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE memories SET importance = MAX(importance, ?), depth = MAX(depth, ?), updated_at = ? WHERE id = ?",
            (importance, depth, _now(), existing[0]),
        )
        conn.commit()
        conn.close()
        return existing[0]

    cur = conn.execute(
        "INSERT INTO memories (content, tags, type, importance, depth, source, scope, confidence, "
        "valid_until, session_id, created_at, updated_at, observed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (content, tags, type, importance, depth, source, scope, confidence,
         valid_until, session_id, _now(), _now(), json.dumps([_now()])),
    )
    conn.commit()
    mid = cur.lastrowid
    conn.close()
    _try_embed(mid, content)
    # P2: 新记忆入库后自动矛盾检测
    contradiction_detect(mid, content)
    return mid

def _row_to_dict(r, has_date: bool = False) -> dict:
    d = {"id": r[0], "content": r[1], "tags": r[2], "type": r[3], "importance": r[4], "depth": _clamp_depth(r[5] if len(r) > 5 else 3)}
    idx = 6
    if has_date:
        d["created_at"] = r[idx]; idx += 1
    d["confidence"] = r[idx] if idx < len(r) else 0.8
    d["valid_until"] = r[idx + 1] if idx + 1 < len(r) else None
    return d

def list_by_type(memory_type: str, min_importance: int = 1, limit: int = 20) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, content, tags, type, importance, depth, created_at, confidence, valid_until FROM memories "
        "WHERE status = 'active' AND type = ? AND importance >= ? "
        "ORDER BY importance DESC, created_at DESC LIMIT ?",
        (memory_type, min_importance, limit),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r, has_date=True) for r in rows]


def list_all(limit: int = 50) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, content, tags, type, importance, depth, created_at, confidence, valid_until FROM memories "
        "WHERE status = 'active' ORDER BY importance DESC, updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r, has_date=True) for r in rows]

def get_by_ids(ids: list[int]) -> dict[int, dict]:
    """批量按 ID 获取活跃记忆，返回 {id: memory_dict}。"""
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            f"SELECT id, content, tags, type, importance, depth, created_at, confidence, valid_until "
            f"FROM memories WHERE id IN ({placeholders}) AND status = 'active'",
            ids,
        ).fetchall()
        result = {r[0]: _row_to_dict(r, has_date=True) for r in rows}
    except sqlite3.OperationalError:
        rows = conn.execute(
            f"SELECT id, content, tags, type, importance, created_at, confidence, valid_until "
            f"FROM memories WHERE id IN ({placeholders}) AND status = 'active'",
            ids,
        ).fetchall()
        result = {
            r[0]: {
                "id": r[0], "content": r[1], "tags": r[2], "type": r[3],
                "importance": r[4], "depth": 3, "created_at": r[5],
                "confidence": r[6], "valid_until": r[7],
            }
            for r in rows
        }
    conn.close()
    return result


def search(keyword: str, limit: int = 10) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    # FTS5 trigram 索引需要 ≥3 个字符，短词直接走 LIKE
    use_fts = len(keyword.strip()) >= 3
    try:
        if not use_fts:
            raise ValueError("keyword too short for FTS5 trigram")
        rows = conn.execute(
            "SELECT m.id, m.content, m.tags, m.type, m.importance, m.depth, m.created_at, m.confidence, m.valid_until "
            "FROM memories_fts f JOIN memories m ON f.rowid = m.id "
            "WHERE memories_fts MATCH ? AND m.status = 'active' "
            "ORDER BY m.importance DESC, rank LIMIT ?",
            (keyword, limit),
        ).fetchall()
    except Exception:
        like = f"%{keyword}%"
        rows = conn.execute(
            "SELECT id, content, tags, type, importance, depth, created_at, confidence, valid_until FROM memories "
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
    try:
        from memory.vector_store import delete as vec_delete
        vec_delete(mid)
    except Exception:
        pass

def update(mid: int, content: str, tags: str | None = None,
           type: str | None = None, importance: int | None = None,
           depth: int | None = None) -> bool:
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
    if depth is not None:
        fields.append("depth = ?")
        values.append(_clamp_depth(depth))

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
        "SELECT id, content, tags, type, importance, depth, confidence, valid_until FROM memories "
        "WHERE status = 'active' ORDER BY importance DESC, updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]

def high_importance(min_importance: int = 4, limit: int = 3) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, content, tags, type, importance, depth, confidence, valid_until FROM memories "
        "WHERE status = 'active' AND importance >= ? "
        "AND type IN ('identity', 'preference', 'project', 'decision', 'value', 'self_narrative', 'insight', 'fact', 'growth_marker') "
        "ORDER BY importance DESC, updated_at DESC LIMIT ?",
        (min_importance, limit),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def update_last_used(mid: int):
    """更新记忆的最后使用时间，用于 retrieve 调用后追踪活跃度。同时追加 observed_at。"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE memories SET last_used_at = ? WHERE id = ?", (_now(), mid))
    conn.commit()
    conn.close()
    observed(mid)


# ── Pending Memories（持久化候选记忆）─────────────────────────────────────────

def add_pending(content: str, type: str = "insight", importance: int = 3,
                tags: str = "", source: str = "auto", confidence: float = 0.7,
                depth: int = 3, suggest_reason: str = "") -> int:
    """将候选记忆写入 pending_memories 表，返回 ID。"""
    content = content.strip()
    if type not in MEMORY_TYPES:
        type = "insight"
    try:
        importance = max(1, min(5, int(importance)))
    except Exception:
        importance = 3
    try:
        depth = max(1, min(5, int(depth)))
    except Exception:
        depth = 3

    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "INSERT INTO pending_memories (content, type, importance, depth, tags, source, confidence, created_at, suggest_reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (content, type, importance, depth, tags.strip(), source, float(confidence), _now(), suggest_reason.strip()),
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def list_pending(limit: int = 50, include_rejected: bool = False) -> list[dict]:
    """返回待确认记忆。默认仅 pending，include_rejected=True 时包含 rejected。"""
    conn = sqlite3.connect(DB_PATH)
    if include_rejected:
        rows = conn.execute(
            "SELECT id, content, type, importance, depth, tags, source, confidence, created_at, status, suggest_reason "
            "FROM pending_memories ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, content, type, importance, depth, tags, source, confidence, created_at, status, suggest_reason "
            "FROM pending_memories WHERE status = 'pending' ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return [
        {
            "id": r[0], "content": r[1], "type": r[2],
            "importance": r[3], "depth": r[4], "tags": r[5],
            "source": r[6], "confidence": r[7], "created_at": r[8],
            "status": r[9] if len(r) > 9 and r[9] else "pending",
            "suggest_reason": r[10] if len(r) > 10 and r[10] else "",
        }
        for r in rows
    ]


def count_pending(include_rejected: bool = False) -> int:
    """返回待确认记忆数量。"""
    conn = sqlite3.connect(DB_PATH)
    if include_rejected:
        n = conn.execute("SELECT COUNT(*) FROM pending_memories").fetchone()[0]
    else:
        n = conn.execute("SELECT COUNT(*) FROM pending_memories WHERE status = 'pending'").fetchone()[0]
    conn.close()
    return n


def update_pending(pid: int, content: str) -> bool:
    """编辑一条待确认记忆的内容，返回是否更新成功。"""
    content = content.strip()
    if not content:
        return False
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "UPDATE pending_memories SET content = ? WHERE id = ?",
        (content, int(pid)),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def accept_pending(pid: int | str) -> list[int]:
    """
    接受待确认记忆，写入主 memories 表并从 pending 中删除。
    pid 可以是具体 ID 或 "all"。返回写入的 memory ID 列表。
    """
    conn = sqlite3.connect(DB_PATH)
    if str(pid) == "all":
        rows = conn.execute(
            "SELECT id, content, type, importance, depth, tags, source, confidence FROM pending_memories WHERE status = 'pending'"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, content, type, importance, depth, tags, source, confidence FROM pending_memories WHERE id = ? AND status = 'pending'",
            (int(pid),),
        ).fetchall()
    conn.close()

    if not rows:
        return []

    memory_ids = []
    accepted_pids = []
    for row in rows:
        p_id, content, type_, importance, depth, tags, source, confidence = row
        mid = save(content, tags=tags, type=type_, importance=importance, source=source, confidence=confidence, depth=depth)
        memory_ids.append(mid)
        accepted_pids.append(p_id)

    conn = sqlite3.connect(DB_PATH)
    if str(pid) == "all":
        conn.execute("DELETE FROM pending_memories WHERE status = 'pending'")
    else:
        conn.execute("DELETE FROM pending_memories WHERE id = ? AND status = 'pending'", (int(pid),))
    conn.commit()
    conn.close()

    return memory_ids


def reject_pending(pid: int | str) -> int:
    """
    软拒绝待确认记忆（status 改为 rejected）。pid 可以是具体 ID 或 "all"。返回更新数量。
    """
    conn = sqlite3.connect(DB_PATH)
    if str(pid) == "all":
        n = conn.execute("SELECT COUNT(*) FROM pending_memories WHERE status = 'pending'").fetchone()[0]
        conn.execute("UPDATE pending_memories SET status = 'rejected' WHERE status = 'pending'")
    else:
        cur = conn.execute(
            "UPDATE pending_memories SET status = 'rejected' WHERE id = ? AND status = 'pending'",
            (int(pid),),
        )
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
        "SELECT m.id, m.content, m.tags, m.type, m.importance, m.depth, m.confidence, m.valid_until, ml.strength "
        "FROM memory_links ml JOIN memories m ON ml.memory_id = m.id "
        "WHERE ml.theme_id = ? AND m.status = 'active' "
        "ORDER BY ml.strength DESC, m.importance DESC LIMIT ?",
        (theme_id, limit),
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "content": r[1], "tags": r[2], "type": r[3],
         "importance": r[4], "depth": _clamp_depth(r[5]), "confidence": r[6], "valid_until": r[7], "strength": r[8]}
        for r in rows
    ]


def get_memories_for_detection(limit: int = 50) -> list[dict]:
    """返回用于主题检测的核心记忆（importance >= 3，排除 reflection/context）。含 session_id。"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, content, tags, type, importance, depth, created_at, confidence, valid_until, session_id "
        "FROM memories WHERE status = 'active' AND importance >= 3 "
        "AND type NOT IN ('reflection', 'context') "
        "ORDER BY importance DESC, updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = _row_to_dict(r[:9], has_date=True)
        d["session_id"] = r[9] if len(r) > 9 else None
        result.append(d)
    return result


# ── Projects（多项目追踪）──────────────────────────────────────────────────────

def create_project(name: str, description: str = "") -> int:
    """创建项目，返回 ID。名称重复时返回已有 ID。"""
    name = name.strip()
    conn = sqlite3.connect(DB_PATH)
    existing = conn.execute(
        "SELECT id FROM projects WHERE name = ? LIMIT 1", (name,)
    ).fetchone()
    if existing:
        conn.close()
        return existing[0]
    cur = conn.execute(
        "INSERT INTO projects (name, description, status, created_at, updated_at) VALUES (?,?,?,?,?)",
        (name, description.strip(), "active", _now(), _now()),
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def list_projects(include_archived: bool = False) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    if include_archived:
        rows = conn.execute(
            "SELECT id, name, description, status, created_at, updated_at FROM projects "
            "ORDER BY status ASC, updated_at DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, name, description, status, created_at, updated_at FROM projects "
            "WHERE status = 'active' ORDER BY updated_at DESC"
        ).fetchall()
    conn.close()
    return [
        {"id": r[0], "name": r[1], "description": r[2],
         "status": r[3], "created_at": r[4], "updated_at": r[5]}
        for r in rows
    ]


def get_project(pid: int) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT id, name, description, status, created_at, updated_at FROM projects WHERE id = ?",
        (pid,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "name": row[1], "description": row[2],
            "status": row[3], "created_at": row[4], "updated_at": row[5]}


def get_project_by_name(name: str) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT id, name, description, status, created_at, updated_at FROM projects WHERE name = ?",
        (name.strip(),),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "name": row[1], "description": row[2],
            "status": row[3], "created_at": row[4], "updated_at": row[5]}


def archive_project(pid: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "UPDATE projects SET status = 'archived', updated_at = ? WHERE id = ? AND status = 'active'",
        (_now(), pid),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def log_project_event(project_id: int, event_type: str, content: str) -> int:
    """向项目写入一条事件记录，返回事件 ID。"""
    conn = sqlite3.connect(DB_PATH)
    # 同步更新 projects.updated_at
    conn.execute(
        "UPDATE projects SET updated_at = ? WHERE id = ?", (_now(), project_id)
    )
    cur = conn.execute(
        "INSERT INTO project_events (project_id, event_type, content, created_at) VALUES (?,?,?,?)",
        (project_id, event_type.strip(), content.strip(), _now()),
    )
    conn.commit()
    eid = cur.lastrowid
    conn.close()
    return eid


def get_project_events(project_id: int, limit: int = 20) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, event_type, content, created_at FROM project_events "
        "WHERE project_id = ? ORDER BY id DESC LIMIT ?",
        (project_id, limit),
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "event_type": r[1], "content": r[2], "created_at": r[3]}
        for r in rows
    ]


# ── Soul Proposals（SOUL.md 演化提议）────────────────────────────────────────

def add_soul_proposal(content: str, source: str = "reflect") -> int:
    """添加一条待审阅的 SOUL 演化提议，返回 ID。"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "INSERT INTO soul_proposals (content, source, status, created_at) VALUES (?,?,?,?)",
        (content.strip(), source, "pending", _now()),
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def list_soul_proposals(status: str = "pending") -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, content, source, status, created_at FROM soul_proposals "
        "WHERE status = ? ORDER BY id",
        (status,),
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "content": r[1], "source": r[2], "status": r[3], "created_at": r[4]}
        for r in rows
    ]


def count_soul_proposals() -> int:
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute(
        "SELECT COUNT(*) FROM soul_proposals WHERE status = 'pending'"
    ).fetchone()[0]
    conn.close()
    return n


def resolve_soul_proposal(pid: int | str, accepted: bool) -> list[int]:
    """将提议标记为 accepted 或 rejected，返回处理的 ID 列表。"""
    conn = sqlite3.connect(DB_PATH)
    status = "accepted" if accepted else "rejected"
    if str(pid) == "all":
        rows = conn.execute(
            "SELECT id FROM soul_proposals WHERE status = 'pending'"
        ).fetchall()
        ids = [r[0] for r in rows]
        conn.execute(
            "UPDATE soul_proposals SET status = ?, reviewed_at = ? WHERE status = 'pending'",
            (status, _now()),
        )
    else:
        conn.execute(
            "UPDATE soul_proposals SET status = ?, reviewed_at = ? WHERE id = ? AND status = 'pending'",
            (status, _now(), int(pid)),
        )
        ids = [int(pid)]
    conn.commit()
    conn.close()
    return ids


# ── Session ID 生成 ──────────────────────────────────────────────────────────────

def generate_session_id() -> str:
    """生成会话 ID：日期时间 + 短 UUID。"""
    short_uuid = str(uuid.uuid4())[:8]
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + short_uuid


# ── Importance Decay（v1.2 Phase 3）────────────────────────────────────────────

# 只对短中期记忆类型执行衰减，不影响身份/决策/偏好
_DECAY_TYPES = {"context", "state", "todo", "risk", "project"}
_NO_DECAY_TYPES = {"identity", "decision", "preference"}


def run_importance_decay() -> int:
    """
    对超期未使用的短中期记忆执行 importance -1 衰减。
    - context/state：超 30 天未使用 → importance -1
    - todo/risk/project：超 60 天未使用 → importance -1
    - 最低降到 1，不自动 archive，不自动删除。
    返回影响的记忆条数。
    """
    now = datetime.now()
    cutoff_30 = (now - timedelta(days=30)).isoformat(timespec="seconds")
    cutoff_60 = (now - timedelta(days=60)).isoformat(timespec="seconds")

    conn = sqlite3.connect(DB_PATH)
    affected = 0

    # context/state 30天
    for t in ("context", "state"):
        cur = conn.execute(
            """UPDATE memories SET importance = MAX(1, importance - 1), updated_at = ?
               WHERE type = ? AND status = 'active' AND importance > 1
               AND (last_used_at IS NULL OR last_used_at < ?)""",
            (_now(), t, cutoff_30),
        )
        affected += cur.rowcount

    # todo/risk/project 60天
    for t in ("todo", "risk", "project"):
        cur = conn.execute(
            """UPDATE memories SET importance = MAX(1, importance - 1), updated_at = ?
               WHERE type = ? AND status = 'active' AND importance > 1
               AND (last_used_at IS NULL OR last_used_at < ?)""",
            (_now(), t, cutoff_60),
        )
        affected += cur.rowcount

    conn.commit()
    conn.close()
    return affected


# ── P1: 记忆时间线 ────────────────────────────────────────────────────────────

import json
import textwrap

_GRACE_DAYS = 90  # >90 天未确认 → stale


def observed(mid: int) -> None:
    """记录该记忆被确认/引用，追加当前时间戳到 observed_at。"""
    now = _now()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT observed_at FROM memories WHERE id = ?", (mid,)).fetchone()
    if not row:
        conn.close()
        return
    try:
        history = json.loads(row[0]) if row[0] else []
    except Exception:
        history = []
    history.append(now)
    conn.execute(
        "UPDATE memories SET observed_at = ?, updated_at = ?, last_used_at = ? WHERE id = ?",
        (json.dumps(history, ensure_ascii=False), now, now, mid),
    )
    conn.commit()
    conn.close()


def freshness_check() -> list[dict]:
    """
    扫描所有 active 记忆，将 > _GRACE_DAYS 天未被确认的记忆标记为 stale。
    返回被标记的记忆列表（含 oldest_observed_at）。
    """
    cutoff = (datetime.now() - timedelta(days=_GRACE_DAYS)).isoformat(timespec="seconds")
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, content, observed_at, type FROM memories WHERE status = 'active'",
    ).fetchall()
    stale = []
    for r in rows:
        mid, content, obs_raw, mtype = r
        if mtype in ("identity", "preference", "decision"):
            continue  # 核心记忆不过期
        try:
            history = json.loads(obs_raw) if obs_raw and obs_raw != "[]" else []
        except Exception:
            history = []
        oldest = history[0] if history else None
        last = history[-1] if history else None
        if last is None or last < cutoff:
            conn.execute("UPDATE memories SET status = 'stale' WHERE id = ?", (mid,))
            stale.append({
                "id": mid, "content": content[:80], "type": mtype,
                "observations": len(history),
                "last_observed": last or "从未",
            })
    conn.commit()
    conn.close()
    return stale


def list_stale() -> list[dict]:
    """列出所有过期记忆。"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, content, type, importance, observed_at FROM memories WHERE status = 'stale'",
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "content": r[1], "type": r[2], "importance": r[3],
         "observed_at": r[4]}
        for r in rows
    ]


def refresh_memory(mid: int) -> bool:
    """手动刷新过期记忆为 active。"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "UPDATE memories SET status = 'active', updated_at = ? WHERE id = ? AND status = 'stale'",
        (_now(), mid),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


# ── P2: 矛盾检测 ───────────────────────────────────────────────────────────────

from difflib import SequenceMatcher
from collections import Counter


def _ngram_similarity(a: str, b: str, n: int = 2) -> float:
    """基于字符 n-gram 的 Jaccard 相似度。用于记忆去重。"""
    if len(a) < n or len(b) < n:
        return 0.0
    ng_a = Counter(a[i:i+n] for i in range(len(a) - n + 1))
    ng_b = Counter(b[i:i+n] for i in range(len(b) - n + 1))
    intersection = sum((ng_a & ng_b).values())
    union = sum((ng_a | ng_b).values())
    return intersection / union if union > 0 else 0.0


def _text_similarity(a: str, b: str) -> float:
    """综合字符级和 bigram 的文本相似度。对中文和英文都适用。"""
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.85
    # 字符级 Jaccard（单字集合交集）
    chars_a = set(a)
    chars_b = set(b)
    char_sim = len(chars_a & chars_b) / max(len(chars_a | chars_b), 1)
    # Bigram Jaccard
    bg_sim = _ngram_similarity(a, b, n=2)
    return char_sim * 0.3 + bg_sim * 0.7


# 中文停用字（在关键词提取时跳过）
_TOPIC_STOPCHARS: set[str] = {
    "用", "户", "希", "望", "要", "求", "认", "为", "觉", "得",
    "这", "个", "那", "个", "自", "己", "什", "么", "可", "以",
    "能", "够", "应", "该", "需", "已", "经", "还", "不", "但",
    "一", "些", "样", "些", "那", "比", "较", "非", "常", "很",
    "都", "也", "就", "再", "把", "被", "让", "给", "从", "在",
    "与", "和", "的", "了", "会", "对", "等", "或", "而", "及",
    "并", "中", "上", "下", "前", "后", "来", "去", "它", "他",
    "她", "其", "你", "我", "且", "虽", "更", "最", "所", "着",
    "却", "又", "走", "向", "做", "成", "为", "使", "进", "到",
    "化", "取", "期", "望", "念", "想", "法", "表", "方", "式",
}


def _topic_keywords(text: str) -> set[str]:
    """从中文文本中提取实质性话题关键词（2-3 字 ngram，跳过停用字）。
    同时保留英文单词 2-3 词短语，避免"Archer 是我的 AI"被提取为空。"""
    ngrams: set[str] = set()
    # 中文 ngram
    cleaned_cn = "".join(c for c in text if "\u4e00" <= c <= "\u9fff" and c not in _TOPIC_STOPCHARS)
    for n in (2, 3):
        for i in range(len(cleaned_cn) - n + 1):
            ngrams.add(cleaned_cn[i:i + n])
    # 英文 ngram（单词级别）
    import re
    _EN_STOP = {"the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
                "have", "has", "had", "do", "does", "did", "will", "would", "could",
                "should", "may", "might", "can", "shall", "to", "of", "in", "for",
                "on", "with", "at", "by", "from", "as", "into", "through", "during",
                "before", "after", "above", "below", "between", "under", "again",
                "further", "then", "once", "here", "there", "when", "where", "why",
                "how", "all", "both", "each", "few", "more", "most", "other", "some",
                "such", "no", "nor", "not", "only", "own", "same", "so", "than",
                "too", "very", "just", "about", "now", "it", "its", "this", "that",
                "these", "those", "and", "but", "or", "if", "while", "because",
                "until", "up", "out", "off", "over", "my", "your", "his", "her", "our", "their"}
    en_words = [w.lower() for w in re.findall(r'[a-zA-Z]{2,}', text) if w.lower() not in _EN_STOP]
    for n in (2, 3):
        for i in range(len(en_words) - n + 1):
            ngrams.add(" ".join(en_words[i:i + n]))
    return ngrams


def _keyword_overlap(a: str, b: str, min_shared: int = 3) -> bool:
    """两个文本是否共享足够多的实质性关键词 ngram。
    用于补充字符相似度对中文近义表述的漏检。"""
    kw_a = _topic_keywords(a)
    kw_b = _topic_keywords(b)
    shared = kw_a & kw_b
    return len(shared) >= min_shared


def is_duplicate_pending(content: str, threshold: float = 0.25) -> bool:
    """检查 content 是否与已有的 pending_memories 或 active memories 高度相似。
    返回 True 表示存在重复，不应再添加。"""
    content = content.strip()
    if len(content) < 10:
        return False  # 太短的不做模糊匹配
    conn = sqlite3.connect(DB_PATH)
    try:
        # 检查 pending_memories
        pending_rows = conn.execute(
            "SELECT content FROM pending_memories"
        ).fetchall()
        for r in pending_rows:
            if _text_similarity(content, r[0]) >= threshold:
                conn.close()
                return True
            if _keyword_overlap(content, r[0], min_shared=3):
                conn.close()
                return True
        # 检查 active memories（更严格阈值，避免误判）
        active_rows = conn.execute(
            "SELECT content FROM memories WHERE status = 'active' ORDER BY updated_at DESC LIMIT 150"
        ).fetchall()
        active_threshold = max(threshold, 0.40)
        for r in active_rows:
            if _text_similarity(content, r[0]) >= active_threshold:
                conn.close()
                return True
            if _keyword_overlap(content, r[0], min_shared=4):
                conn.close()
                return True
        conn.close()
        return False
    except Exception:
        conn.close()
        return False


def is_low_quality_memory(content: str, mtype: str = "insight") -> bool:
    """过滤低质量记忆。返回 True 表示应该丢弃。"""
    content = content.strip()
    # 太短
    if len(content) < 10:
        return True
    # 太长：超过 200 字可能是啰嗦话
    if len(content) > 200:
        return True
    # 纯事实性低价值短语（太泛了）
    low_value_patterns = [
        "好的", "明白了", "知道了", "嗯", "对", "是的",
        "可以的", "没问题", "就这样", "行", "好",
        "他说", "我说", "用户说", "你说",
    ]
    if any(content == p or content.startswith(p) and len(content) < 12 for p in low_value_patterns):
        return True
    # 无实质内容：只有代词和连接词
    filler_ratio = sum(1 for c in content if c in "的了我是在有这和那就也他她对它") / max(len(content), 1)
    if filler_ratio > 0.55 and len(content) < 30:
        return True
    # 重复相同字符（如 "好好好好好"）
    if len(content) > 4 and len(set(content)) == 1:
        return True
    return False


def _is_contradiction(a: str, b: str) -> bool:
    """
    判断两条记忆是否语义矛盾。
    纯规则：不依赖模型——基于否定词 + 相似度。
    高相似度 + 否定词 = 矛盾。
    """
    NEGATORS = ["不", "不再", "从不", "没", "没有", "否定", "取消", "放弃",
                "don't", "not", "never", "no longer", "stop", "quit"]
    a_neg = any(w in a for w in NEGATORS)
    b_neg = any(w in b for w in NEGATORS)
    # 一个肯定一个否定 + 文本相似 → 矛盾
    if a_neg == b_neg:
        return False
    sim = SequenceMatcher(None, a, b).ratio()
    return sim > 0.55


def contradiction_detect(new_mid: int, new_content: str) -> list[int]:
    """
    新记忆入库后调用。与所有 active 记忆比对，发现矛盾则记录到 contradictions 表。
    返回矛盾记忆 ID 列表。
    """
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, content FROM memories WHERE status = 'active' AND id != ?", (new_mid,),
    ).fetchall()
    conflicts = []
    for r in rows:
        if _is_contradiction(new_content, r[1]):
            try:
                a, b = sorted([new_mid, r[0]])
                conn.execute(
                    "INSERT INTO contradictions (memory_a, memory_b, description, status, created_at) "
                    "VALUES (?, ?, ?, 'open', ?)",
                    (a, b, f"{a} ↔ {b}", _now()),
                )
                conflicts.append(r[0])
            except Exception:
                pass  # UNIQUE 冲突：已存在，跳过
    conn.commit()
    conn.close()
    return conflicts


def list_contradictions() -> list[dict]:
    """列出所有未解决的矛盾。"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT c.id, c.memory_a, c.memory_b, c.description, c.status, c.created_at, "
        "ma.content, mb.content "
        "FROM contradictions c "
        "JOIN memories ma ON ma.id = c.memory_a "
        "JOIN memories mb ON mb.id = c.memory_b "
        "WHERE c.status = 'open' ORDER BY c.created_at DESC",
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "memory_a": r[1], "memory_b": r[2], "description": r[3],
         "status": r[4], "created_at": r[5],
         "content_a": r[6][:80], "content_b": r[7][:80]}
        for r in rows
    ]


def resolve_contradiction(cid: int, keep_memory: int) -> bool:
    """
    裁决矛盾：保留 keep_memory，归档另一边。
    """
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT memory_a, memory_b FROM contradictions WHERE id = ?", (cid,),
    ).fetchone()
    if not row:
        conn.close()
        return False
    discard = row[0] if row[1] == keep_memory else row[1]
    conn.execute("UPDATE contradictions SET status = 'resolved', resolved_at = ? WHERE id = ?",
                 (_now(), cid))
    conn.execute("UPDATE memories SET status = 'archived', archived_at = ? WHERE id = ?",
                 (_now(), discard))
    conn.commit()
    conn.close()
    return True


# ── P3: 记忆分类体系 ───────────────────────────────────────────────────────────

# 25 种 memory type → 5 大归组
MEMORY_GROUPS: dict[str, dict] = {
    "who_am_i": {
        "label": "我是谁",
        "icon": "heart",
        "types": ["identity", "value", "value_conflict", "self_narrative", "reflection_anchor"],
        "question": "我坚持什么？我在纠结什么？",
    },
    "how_i_work": {
        "label": "我怎么做事",
        "icon": "settings",
        "types": ["preference", "fact", "decision", "reflection"],
        "question": "什么方式让我效率最高？",
    },
    "emotion_world": {
        "label": "我的情绪模式",
        "icon": "waves",
        "types": ["emotion_pattern", "relationship_pattern", "context"],
        "question": "什么情境会触发我？",
    },
    "what_i_do": {
        "label": "我在做什么",
        "icon": "compass",
        "types": ["project", "project_mythology", "todo", "risk"],
        "question": "项目到哪了？为什么重要？",
    },
    "how_i_grow": {
        "label": "我在变",
        "icon": "trending_up",
        "types": ["growth_marker", "creative_identity", "insight", "life_theme"],
        "question": "相比之前，我变了什么？",
    },
}


def memory_group_for_type(mtype: str) -> str:
    """返回给定 type 所属的 group key。"""
    for key, group in MEMORY_GROUPS.items():
        if mtype in group["types"]:
            return key
    return "who_am_i"  # fallback


def count_by_groups() -> dict:
    """返回每个 group 的 active 记忆数量。"""
    conn = sqlite3.connect(DB_PATH)
    result = {}
    for key, group in MEMORY_GROUPS.items():
        placeholders = ",".join("?" * len(group["types"]))
        count = conn.execute(
            f"SELECT COUNT(*) FROM memories WHERE status = 'active' AND type IN ({placeholders})",
            group["types"],
        ).fetchone()[0]
        result[key] = count
    conn.close()
    return result


def memories_by_group(group_key: str, limit: int = 30) -> list[dict]:
    """返回指定 group 下的记忆列表。"""
    if group_key not in MEMORY_GROUPS:
        return []
    types = MEMORY_GROUPS[group_key]["types"]
    placeholders = ",".join("?" * len(types))
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        f"SELECT id, content, type, importance, depth, created_at, confidence "
        f"FROM memories WHERE status = 'active' AND type IN ({placeholders}) "
        f"ORDER BY importance DESC, updated_at DESC LIMIT ?",
        [*types, limit],
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "content": r[1], "type": r[2],
         "importance": r[3], "depth": r[4], "created_at": r[5], "confidence": r[6]}
        for r in rows
    ]


# ── P4: 记忆更新 ──────────────────────────────────────────────────────────────

def update_memory_content(mid: int, content: str) -> bool:
    """更新已有记忆的内容，保留原 type/importance/depth。返回是否成功。"""
    content = content.strip()
    if not content or len(content) < 10:
        return False
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "UPDATE memories SET content = ?, updated_at = ? WHERE id = ? AND status = 'active'",
        (content, _now(), mid),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    if ok:
        _try_embed(mid, content)
        observed(mid)
    return ok


def evolve_memory(mid: int, content: str, mtype: str | None = None,
                  importance: int | None = None, depth: int | None = None) -> bool:
    """演进记忆：更新内容，可选更新 type/importance/depth。
    旧内容存为标签中的历史。"""
    content = content.strip()
    if not content or len(content) < 10:
        return False
    conn = sqlite3.connect(DB_PATH)
    old = conn.execute(
        "SELECT content, type, importance, depth FROM memories WHERE id = ? AND status = 'active'",
        (mid,),
    ).fetchone()
    if not old:
        conn.close()
        return False
    old_content = old[0]
    new_type = mtype if mtype and mtype in MEMORY_TYPES else old[1]
    new_imp = max(1, min(5, int(importance))) if importance is not None else old[2]
    new_depth = _clamp_depth(depth) if depth is not None else old[3]
    # 把旧内容追加到 observed_at
    observed_at = _now()
    conn.execute(
        "UPDATE memories SET content = ?, type = ?, importance = ?, depth = ?, "
        "updated_at = ?, observed_at = ? WHERE id = ? AND status = 'active'",
        (content, new_type, new_imp, new_depth, _now(), observed_at, mid),
    )
    # 给旧记忆内容加个追溯标签
    if old_content != content:
        conn.execute(
            "UPDATE memories SET tags = CASE WHEN tags = '' THEN ? ELSE tags || ',' || ? END WHERE id = ?",
            (f"曾:{old_content[:40]}", f"曾:{old_content[:40]}", mid),
        )
    conn.commit()
    conn.close()
    _try_embed(mid, content)
    return True


def count_contradictions() -> int:
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM contradictions WHERE status = 'open'").fetchone()[0]
    conn.close()
    return n


def count_stale() -> int:
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM memories WHERE status = 'stale'").fetchone()[0]
    conn.close()
    return n


def recent_memories_since(since_days: int = 7) -> list[dict]:
    """返回最近 N 天内创建的活跃记忆。"""
    cutoff = (datetime.now() - timedelta(days=since_days)).isoformat(timespec="seconds")
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, content, type, importance, depth, created_at, confidence FROM memories "
        "WHERE status = 'active' AND created_at >= ? ORDER BY created_at DESC LIMIT 50",
        (cutoff,),
    ).fetchall()
    conn.close()
    return [
        {"id": r[0], "content": r[1], "type": r[2],
         "importance": r[3], "depth": r[4], "created_at": r[5], "confidence": r[6]}
        for r in rows
    ]
