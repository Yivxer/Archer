"""
P5.1 — Memory block_type + label tests
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _setup_tmp_db(tmp: str):
    import memory.store as store_mod
    store_mod.DB_PATH = Path(tmp) / "test.db"
    store_mod.init_db()
    return store_mod


def test_block_columns_exist():
    import sqlite3
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        conn = sqlite3.connect(store.DB_PATH)
        mem_cols = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}
        pend_cols = {row[1] for row in conn.execute("PRAGMA table_info(pending_memories)")}
        conn.close()
    for col in ("block_type", "label"):
        assert col in mem_cols, f"memories 缺少列: {col}"
        assert col in pend_cols, f"pending_memories 缺少列: {col}"


def test_infer_block_type_from_memory_type():
    from memory.store import infer_block_type
    assert infer_block_type("fact") == "human"
    assert infer_block_type("preference") == "preference"
    assert infer_block_type("project") == "decision"
    assert infer_block_type("reflection_anchor") == "event"
    assert infer_block_type("value") == "insight"
    assert infer_block_type("insight", "persona") == "persona"


def test_save_and_list_by_block_type():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        store.save("用户住在北京", type="fact", block_type="human", label="location")
        store.save("偏好简洁回复", type="preference", label="communication")
        human = store.list_by_block_type("human")
        pref = store.list_by_block_type("preference", label="communication")
        assert len(human) == 1
        assert human[0]["label"] == "location"
        assert len(pref) == 1
        assert pref[0]["block_type"] == "preference"


def test_search_filters_by_block_type():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        store.save("决策先写测试", type="decision", block_type="decision")
        store.save("洞察型内容测试条目", type="insight", block_type="insight")
        hits = store.search("测试", block_type="decision", limit=10)
        assert len(hits) == 1
        assert hits[0]["block_type"] == "decision"


def test_pending_preserves_block_fields():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        pid = store.add_pending(
            "待确认偏好记忆内容",
            type="preference",
            block_type="preference",
            label="writing_style",
        )
        pending = store.list_pending()
        item = next(p for p in pending if p["id"] == pid)
        assert item["block_type"] == "preference"
        assert item["label"] == "writing_style"

        mids = store.accept_pending(pid)
        assert len(mids) == 1
        rows = store.list_by_block_type("preference", label="writing_style")
        assert any(r["id"] == mids[0] for r in rows)


def test_extract_clean_memory_infers_block_type():
    from memory.extract import _clean_memory
    result = _clean_memory({
        "content": "用户偏好短句、少形容词",
        "type": "preference",
        "importance": 4,
        "depth": 2,
        "label": "writing_style",
        "obsidian_hint": "",
    })
    assert result is not None
    assert result["block_type"] == "preference"
    assert result["label"] == "writing_style"


def test_retrieve_filter_by_block_type():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        store.save("人类档案记忆内容测试", type="fact", block_type="human")
        store.save("洞察记忆内容测试条目", type="insight", block_type="insight")

        import memory.retrieve as ret_mod
        import memory.store as orig_store
        orig_db = orig_store.DB_PATH
        orig_store.DB_PATH = store.DB_PATH
        try:
            hits = ret_mod.filter_by_block_type("human", limit=10)
            assert len(hits) == 1
            assert hits[0]["block_type"] == "human"
        finally:
            orig_store.DB_PATH = orig_db


def test_memory_route_exposes_block_type():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        store.add_pending("待确认 block 记忆", type="fact", block_type="human", label="city")
        from terminal.api._routes import _memory
        items = _memory(limit=20)
        item = next(i for i in items if i["content"] == "待确认 block 记忆")
        assert item["blockType"] == "human"
        assert item["label"] == "city"


if __name__ == "__main__":
    tests = [
        test_block_columns_exist,
        test_infer_block_type_from_memory_type,
        test_save_and_list_by_block_type,
        test_search_filters_by_block_type,
        test_pending_preserves_block_fields,
        test_extract_clean_memory_infers_block_type,
        test_retrieve_filter_by_block_type,
        test_memory_route_exposes_block_type,
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
