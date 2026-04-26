"""
Step 6 — Memory Schema Lifecycle Fields Tests
"""
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _setup_tmp_db(tmp: str):
    import memory.store as store_mod
    store_mod.DB_PATH = Path(tmp) / "test.db"
    store_mod.init_db()
    return store_mod


# ── schema presence ────────────────────────────────────────────────────────────

def test_new_columns_exist():
    """memories 表包含 scope/confidence/last_used_at/valid_until 列。"""
    import sqlite3
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        conn = sqlite3.connect(store.DB_PATH)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}
        conn.close()
    for col in ("scope", "confidence", "last_used_at", "valid_until"):
        assert col in cols, f"缺少列: {col}"


def test_pending_confidence_column_exists():
    """pending_memories 表包含 confidence 列。"""
    import sqlite3
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        conn = sqlite3.connect(store.DB_PATH)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(pending_memories)")}
        conn.close()
    assert "confidence" in cols


# ── save / retrieve lifecycle fields ──────────────────────────────────────────

def test_save_with_confidence():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        mid = store.save("测试记忆内容", confidence=0.9, scope="user")
        rows = store.list_all(10)
        m = next(r for r in rows if r["id"] == mid)
        assert abs(m["confidence"] - 0.9) < 1e-9


def test_save_default_confidence():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        mid = store.save("默认置信度记忆")
        rows = store.list_all(10)
        m = next(r for r in rows if r["id"] == mid)
        assert abs(m["confidence"] - 0.8) < 1e-9


def test_save_with_valid_until():
    future = (datetime.now() + timedelta(days=7)).isoformat(timespec="seconds")
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        mid = store.save("有效期记忆", valid_until=future)
        rows = store.list_all(10)
        m = next(r for r in rows if r["id"] == mid)
        assert m["valid_until"] == future


def test_update_last_used():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        mid = store.save("用于追踪使用时间的记忆")
        store.update_last_used(mid)
        import sqlite3
        conn = sqlite3.connect(store.DB_PATH)
        row = conn.execute("SELECT last_used_at FROM memories WHERE id = ?", (mid,)).fetchone()
        conn.close()
        assert row[0] is not None, "last_used_at 应在 update_last_used 后被设置"


# ── add_pending confidence ─────────────────────────────────────────────────────

def test_add_pending_carries_confidence():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        store.add_pending("候选记忆", confidence=0.65)
        pends = store.list_pending()
        assert len(pends) == 1
        assert abs(pends[0]["confidence"] - 0.65) < 1e-9


def test_accept_pending_carries_confidence():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        pid = store.add_pending("确认后置信度", confidence=0.75)
        mids = store.accept_pending(pid)
        assert len(mids) == 1
        import sqlite3
        conn = sqlite3.connect(store.DB_PATH)
        row = conn.execute("SELECT confidence FROM memories WHERE id = ?", (mids[0],)).fetchone()
        conn.close()
        assert abs(row[0] - 0.75) < 1e-9


# ── retrieve: filter reflection + expired ─────────────────────────────────────

def test_retrieve_filters_reflection_type():
    """for_context 不返回 reflection 类型记忆。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        store.save("复盘摘要，不应注入", type="reflection", importance=5)
        store.save("正常记忆，应注入", type="insight", importance=5)

        import memory.retrieve as ret_mod
        import memory.store as orig_store
        # 让 retrieve 使用我们的测试 DB
        orig_db = orig_store.DB_PATH
        orig_store.DB_PATH = store.DB_PATH
        try:
            core, related = ret_mod.for_context("正常记忆")
        finally:
            orig_store.DB_PATH = orig_db

        all_ids = {m["id"] for m in core + related}
        import sqlite3
        conn = sqlite3.connect(store.DB_PATH)
        reflection_ids = {
            r[0] for r in conn.execute(
                "SELECT id FROM memories WHERE type = 'reflection'"
            )
        }
        conn.close()
        assert not (all_ids & reflection_ids), "reflection 类型记忆不应出现在检索结果中"


def test_retrieve_skips_expired():
    """for_context 不返回 valid_until 已过期的记忆。"""
    past = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
    future = (datetime.now() + timedelta(days=7)).isoformat(timespec="seconds")
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        store.save("过期记忆内容测试", type="insight", importance=5, valid_until=past)
        store.save("有效记忆内容测试", type="insight", importance=5, valid_until=future)

        import memory.retrieve as ret_mod
        import memory.store as orig_store
        orig_db = orig_store.DB_PATH
        orig_store.DB_PATH = store.DB_PATH
        try:
            core, related = ret_mod.for_context("记忆内容测试")
        finally:
            orig_store.DB_PATH = orig_db

        contents = [m["content"] for m in core + related]
        assert "过期记忆内容测试" not in contents
        assert "有效记忆内容测试" in contents


def test_retrieve_updates_last_used():
    """for_context 调用后 last_used_at 被更新。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        mid = store.save("追踪使用时间的记忆内容", type="insight", importance=5)

        import memory.retrieve as ret_mod
        import memory.store as orig_store
        orig_db = orig_store.DB_PATH
        orig_store.DB_PATH = store.DB_PATH
        try:
            ret_mod.for_context("追踪使用时间的记忆内容")
        finally:
            orig_store.DB_PATH = orig_db

        import sqlite3
        conn = sqlite3.connect(store.DB_PATH)
        row = conn.execute("SELECT last_used_at FROM memories WHERE id = ?", (mid,)).fetchone()
        conn.close()
        assert row[0] is not None


# ── extract: confidence 字段 ───────────────────────────────────────────────────

def test_extract_clean_memory_has_confidence():
    """_clean_memory 返回的记忆包含 confidence=0.7。"""
    from memory.extract import _clean_memory
    m = {"content": "自动提炼的记忆内容", "type": "insight", "importance": 3, "obsidian_hint": ""}
    result = _clean_memory(m)
    assert result is not None
    assert "confidence" in result
    assert abs(result["confidence"] - 0.7) < 1e-9


# ── Runner ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_new_columns_exist,
        test_pending_confidence_column_exists,
        test_save_with_confidence,
        test_save_default_confidence,
        test_save_with_valid_until,
        test_update_last_used,
        test_add_pending_carries_confidence,
        test_accept_pending_carries_confidence,
        test_retrieve_filters_reflection_type,
        test_retrieve_skips_expired,
        test_retrieve_updates_last_used,
        test_extract_clean_memory_has_confidence,
    ]

    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
            passed += 1
        except Exception as e:
            import traceback
            print(f"  [FAIL] {t.__name__}: {e}")
            traceback.print_exc()
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
