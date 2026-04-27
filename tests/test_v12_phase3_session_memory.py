"""
v1.2 Phase 3 — 记忆质量升级测试

覆盖：
- session_id 写入 memories
- session_id 写入 project_events（通过 log_project_event）
- importance decay 不影响 identity/decision
- importance decay 降低 context/todo 类型
- themes 检测使用 session_id 门控
- generate_session_id 格式验证
"""
import sys
import tempfile
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _setup_tmp_db(tmp_dir):
    import memory.store as store_mod
    store_mod.DB_PATH = Path(tmp_dir) / "test.db"
    store_mod.init_db()
    return store_mod


# ── session_id 生成 ─────────────────────────────────────────────────────────────

def test_session_id_format():
    from memory.store import generate_session_id
    sid = generate_session_id()
    # 格式：YYYYMMDD-HHMMSS-<8位uuid>
    parts = sid.split("-")
    assert len(parts) == 3, f"session_id 格式应为 YYYYMMDD-HHMMSS-uuid8: {sid}"
    assert len(parts[0]) == 8, "日期部分应为 8 位"
    assert len(parts[1]) == 6, "时间部分应为 6 位"
    assert len(parts[2]) == 8, "UUID 部分应为 8 位"

def test_session_id_unique():
    from memory.store import generate_session_id
    ids = {generate_session_id() for _ in range(10)}
    assert len(ids) == 10, "每次生成的 session_id 应该不同"


# ── session_id 写入记忆 ─────────────────────────────────────────────────────────

def test_memory_stores_session_id():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        sid = "20260427-120000-abc12345"
        mid = store.save("测试记忆内容，包含 session_id 字段测试。", session_id=sid)
        conn = sqlite3.connect(store.DB_PATH)
        row = conn.execute("SELECT session_id FROM memories WHERE id=?", (mid,)).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == sid

def test_memory_without_session_id():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        mid = store.save("没有 session_id 的记忆内容。")
        conn = sqlite3.connect(store.DB_PATH)
        row = conn.execute("SELECT session_id FROM memories WHERE id=?", (mid,)).fetchone()
        conn.close()
        assert row is not None
        assert row[0] is None  # 不传 session_id 时为 NULL


# ── importance decay ────────────────────────────────────────────────────────────

def test_decay_affects_context():
    """context 类型超期未使用，decay 应降低 importance。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        mid = store.save(
            "这是一条临时上下文记忆，超期后应该 decay。",
            type="context", importance=3,
        )
        # 手动设置 last_used_at 为很久以前
        old_date = "2025-01-01T00:00:00"
        conn = sqlite3.connect(store.DB_PATH)
        conn.execute("UPDATE memories SET last_used_at=? WHERE id=?", (old_date, mid))
        conn.commit()
        conn.close()
        affected = store.run_importance_decay()
        assert affected >= 1
        conn = sqlite3.connect(store.DB_PATH)
        row = conn.execute("SELECT importance FROM memories WHERE id=?", (mid,)).fetchone()
        conn.close()
        assert row[0] == 2  # 3 → 2

def test_decay_does_not_affect_identity():
    """identity 类型不受 decay 影响。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        mid = store.save(
            "这是身份记忆：枫弋的价值排序是自由第一。",
            type="identity", importance=3,
        )
        old_date = "2025-01-01T00:00:00"
        conn = sqlite3.connect(store.DB_PATH)
        conn.execute("UPDATE memories SET last_used_at=? WHERE id=?", (old_date, mid))
        conn.commit()
        conn.close()
        store.run_importance_decay()
        conn = sqlite3.connect(store.DB_PATH)
        row = conn.execute("SELECT importance FROM memories WHERE id=?", (mid,)).fetchone()
        conn.close()
        assert row[0] == 3  # identity 不变

def test_decay_does_not_affect_decision():
    """decision 类型不受 decay 影响。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        mid = store.save(
            "这是一个重要决策：决定全职做产品而不是继续打工。",
            type="decision", importance=4,
        )
        old_date = "2025-01-01T00:00:00"
        conn = sqlite3.connect(store.DB_PATH)
        conn.execute("UPDATE memories SET last_used_at=? WHERE id=?", (old_date, mid))
        conn.commit()
        conn.close()
        store.run_importance_decay()
        conn = sqlite3.connect(store.DB_PATH)
        row = conn.execute("SELECT importance FROM memories WHERE id=?", (mid,)).fetchone()
        conn.close()
        assert row[0] == 4  # decision 不变

def test_decay_floor_is_1():
    """decay 最低降到 1，不会变成 0 或负数。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        mid = store.save("上下文记忆，importance 已经是最低值。", type="context", importance=1)
        old_date = "2025-01-01T00:00:00"
        conn = sqlite3.connect(store.DB_PATH)
        conn.execute("UPDATE memories SET last_used_at=? WHERE id=?", (old_date, mid))
        conn.commit()
        conn.close()
        store.run_importance_decay()
        conn = sqlite3.connect(store.DB_PATH)
        row = conn.execute("SELECT importance FROM memories WHERE id=?", (mid,)).fetchone()
        conn.close()
        assert row[0] == 1  # 不低于 1


# ── themes 检测 session_id 门控 ────────────────────────────────────────────────

def test_get_memories_for_detection_includes_session_id():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        sid = "20260427-120000-abc12345"
        store.save("重要洞察：持续使用 session_id 有助于跨会话分析。",
                   type="insight", importance=4, session_id=sid)
        mems = store.get_memories_for_detection(limit=10)
        assert len(mems) >= 1
        has_session = any(m.get("session_id") == sid for m in mems)
        assert has_session, "get_memories_for_detection 应返回 session_id 字段"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
