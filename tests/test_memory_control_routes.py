from __future__ import annotations

from pathlib import Path
import sqlite3

import memory.store as store
from terminal.api.memory_routes import _archive_memory, _remember_memory


def test_explicit_remember_still_requires_review(tmp_path: Path) -> None:
    original = store.DB_PATH
    store.DB_PATH = tmp_path / "archer.db"
    try:
        store.init_db()
        result = _remember_memory({"content": "我恢复精力最有效的方式是跑步"})
        assert result["status"] == "pending"
        assert result["requiresReview"] is True
        assert store.count_pending() == 1
    finally:
        store.DB_PATH = original


def test_archive_is_soft_delete(tmp_path: Path) -> None:
    original = store.DB_PATH
    store.DB_PATH = tmp_path / "archer.db"
    try:
        store.init_db()
        memory_id = store.save("这是一条需要软归档的长期记忆")
        result = _archive_memory({"id": memory_id})
        assert result["status"] == "archived"
        conn = sqlite3.connect(store.DB_PATH)
        try:
            status = conn.execute("SELECT status FROM memories WHERE id=?", (memory_id,)).fetchone()[0]
        finally:
            conn.close()
        assert status == "archived"
    finally:
        store.DB_PATH = original
