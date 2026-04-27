"""
sqlite-vec 向量存储：在 archer.db 中管理记忆嵌入向量。

表：memory_vecs（vec0 虚拟表）
  rowid = memory_id（与 memories.id 对应）

未安装 sqlite-vec 时所有写操作静默忽略，
search_similar() 返回空列表（retrieve.py 自动降级到 FTS）。
"""
from __future__ import annotations

import sqlite3
import struct
from pathlib import Path

from memory.store import DB_PATH
from memory.embedder import DIM


def _serialize(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _load_vec(conn: sqlite3.Connection) -> bool:
    """加载 sqlite-vec 扩展，失败时返回 False。"""
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception:
        return False


def init_vec_table(db_path: Path = DB_PATH) -> bool:
    """
    创建 memory_vecs 虚拟表（幂等）。
    sqlite-vec 未安装时返回 False。
    """
    try:
        conn = sqlite3.connect(db_path)
        if not _load_vec(conn):
            conn.close()
            return False
        conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_vecs USING vec0(
                embedding float[{DIM}]
            )
        """)
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def upsert(memory_id: int, embedding: list[float], db_path: Path = DB_PATH) -> bool:
    """插入或更新记忆的向量嵌入，返回是否成功。"""
    try:
        blob = _serialize(embedding)
        conn = sqlite3.connect(db_path)
        if not _load_vec(conn):
            conn.close()
            return False
        conn.execute("DELETE FROM memory_vecs WHERE rowid = ?", (memory_id,))
        conn.execute(
            "INSERT INTO memory_vecs(rowid, embedding) VALUES (?, ?)",
            (memory_id, blob),
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def search_similar(
    query_vec: list[float],
    limit: int = 10,
    db_path: Path = DB_PATH,
) -> list[tuple[int, float]]:
    """
    KNN 向量搜索，返回 [(memory_id, distance)]。
    distance 越小越相似（归一化向量下 ≈ 余弦距离）。
    失败时返回空列表（调用方降级到 FTS）。
    """
    try:
        blob = _serialize(query_vec)
        conn = sqlite3.connect(db_path)
        if not _load_vec(conn):
            conn.close()
            return []
        rows = conn.execute("""
            SELECT rowid, distance
            FROM memory_vecs
            WHERE embedding MATCH ?
            AND k = ?
        """, (blob, limit)).fetchall()
        conn.close()
        return [(int(r[0]), float(r[1])) for r in rows]
    except Exception:
        return []


def delete(memory_id: int, db_path: Path = DB_PATH) -> None:
    """删除记忆的向量嵌入（静默，不影响主流程）。"""
    try:
        conn = sqlite3.connect(db_path)
        if not _load_vec(conn):
            conn.close()
            return
        conn.execute("DELETE FROM memory_vecs WHERE rowid = ?", (memory_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass


def reindex_all(db_path: Path = DB_PATH) -> tuple[int, int]:
    """
    重建所有活跃记忆的向量索引。
    返回 (成功数, 总数)。
    """
    from memory.store import list_all
    from memory.embedder import encode

    mems = list_all(limit=99999)
    ok = 0
    for m in mems:
        try:
            emb = encode(m["content"])
            if upsert(m["id"], emb, db_path):
                ok += 1
        except Exception:
            pass
    return ok, len(mems)
