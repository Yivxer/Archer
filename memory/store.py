import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "archer.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            content    TEXT    NOT NULL,
            tags       TEXT    DEFAULT '',
            importance INTEGER DEFAULT 3,
            source     TEXT    DEFAULT '',
            created_at TEXT    NOT NULL,
            updated_at TEXT    NOT NULL
        )
    """)
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
    conn.commit()
    conn.close()

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")

def save(content: str, tags: str = "", importance: int = 3, source: str = "") -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "INSERT INTO memories (content, tags, importance, source, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (content, tags, importance, source, _now(), _now()),
    )
    conn.commit()
    mid = cur.lastrowid
    conn.close()
    return mid

def list_all(limit: int = 50) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, content, tags, importance, created_at FROM memories "
        "ORDER BY importance DESC, updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [{"id": r[0], "content": r[1], "tags": r[2], "importance": r[3], "created_at": r[4]} for r in rows]

def search(keyword: str, limit: int = 10) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            "SELECT m.id, m.content, m.tags, m.importance, m.created_at "
            "FROM memories_fts f JOIN memories m ON f.rowid = m.id "
            "WHERE memories_fts MATCH ? "
            "ORDER BY m.importance DESC, rank LIMIT ?",
            (keyword, limit),
        ).fetchall()
    except Exception:
        like = f"%{keyword}%"
        rows = conn.execute(
            "SELECT id, content, tags, importance, created_at FROM memories "
            "WHERE content LIKE ? OR tags LIKE ? ORDER BY importance DESC LIMIT ?",
            (like, like, limit),
        ).fetchall()
    conn.close()
    return [{"id": r[0], "content": r[1], "tags": r[2], "importance": r[3], "created_at": r[4]} for r in rows]

def delete(mid: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM memories WHERE id = ?", (mid,))
    conn.commit()
    conn.close()

def recent(limit: int = 5) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, content, tags, importance FROM memories "
        "ORDER BY importance DESC, updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [{"id": r[0], "content": r[1], "tags": r[2], "importance": r[3]} for r in rows]
