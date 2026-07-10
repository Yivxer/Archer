"""Schema composition for Archer's SQLite database."""
from __future__ import annotations

import sqlite3
from pathlib import Path

def initialize_schema(db_path: str | Path):
    resolved_db_path = Path(db_path).expanduser()
    resolved_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved_db_path)
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
    try:
        conn.execute("ALTER TABLE pending_memories ADD COLUMN session_summary TEXT DEFAULT ''")
    except Exception:
        pass
    for ddl in [
        "ALTER TABLE memories ADD COLUMN block_type TEXT DEFAULT 'insight'",
        "ALTER TABLE memories ADD COLUMN label TEXT DEFAULT ''",
        "ALTER TABLE pending_memories ADD COLUMN block_type TEXT DEFAULT 'insight'",
        "ALTER TABLE pending_memories ADD COLUMN label TEXT DEFAULT ''",
    ]:
        try:
            conn.execute(ddl)
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
    init_critiques_table(resolved_db_path)
    # v1.3 Phase 1: 技能缺口追踪表
    from memory.skill_gap import init_skill_gap_table
    init_skill_gap_table(resolved_db_path)
    from memory.workflow_crystal import init_table as init_crystal_table
    init_crystal_table(resolved_db_path)
    from memory.feedback import init_table as init_feedback_table
    init_feedback_table(resolved_db_path)
    from memory.hypothesis_tracker import init_hypotheses_table
    init_hypotheses_table(resolved_db_path)
    from memory.part8_schema import (
        init_initiative_shadow_table,
        init_monologue_table,
        init_part8_threads_table,
        init_presence_table,
    )
    init_initiative_shadow_table(resolved_db_path)
    init_part8_threads_table(resolved_db_path)
    init_monologue_table(resolved_db_path)
    init_presence_table(resolved_db_path)
    # v1.4: Work item 任务追踪表
    from memory.work import init_work_table
    init_work_table(resolved_db_path)
    # v1.5: Sub-task 子代理任务表
    from memory.subtask import init_subtask_table
    init_subtask_table(resolved_db_path)
    # v1.5: P1/P2 记忆矛盾追踪
    conn = sqlite3.connect(resolved_db_path)
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
    init_emotion_table(resolved_db_path)
