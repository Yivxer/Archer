"""
Step 7 — Patterns/Themes Graph Structure Tests
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _setup_tmp_db(tmp: str):
    import memory.store as store_mod
    store_mod.DB_PATH = Path(tmp) / "test.db"
    store_mod.init_db()
    return store_mod


# ── schema ─────────────────────────────────────────────────────────────────────

def test_themes_table_exists():
    import sqlite3
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        conn = sqlite3.connect(store.DB_PATH)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
    assert "themes" in tables
    assert "memory_links" in tables


# ── save_theme / list_themes ───────────────────────────────────────────────────

def test_save_theme_basic():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        tid = store.save_theme("拖延启动", "经常在行动前反复确认细节", "struggle")
        assert isinstance(tid, int) and tid > 0


def test_save_theme_deduplicates_and_increments():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        t1 = store.save_theme("工具研究", "深度探索新工具")
        t2 = store.save_theme("工具研究", "更新后的描述")
        assert t1 == t2
        themes = store.list_themes()
        match = next(t for t in themes if t["name"] == "工具研究")
        assert match["occurrence_count"] == 2


def test_list_themes_sorted_by_occurrence():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        store.save_theme("低频主题")
        store.save_theme("高频主题")
        store.save_theme("高频主题")
        store.save_theme("高频主题")
        themes = store.list_themes()
        assert themes[0]["name"] == "高频主题"


# ── link_memory_to_theme / get_theme_memories ──────────────────────────────────

def test_link_memory_to_theme():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        mid = store.save("反复研究新工具而不推进主任务", type="insight", importance=4)
        tid = store.save_theme("工具研究替代行动")
        store.link_memory_to_theme(mid, tid, strength=0.85)
        mems = store.get_theme_memories(tid)
        assert len(mems) == 1
        assert mems[0]["id"] == mid
        assert abs(mems[0]["strength"] - 0.85) < 1e-9


def test_link_memory_upsert():
    """同一 (memory_id, theme_id) 重复 link 时更新 strength。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        mid = store.save("反复研究新工具", type="insight", importance=4)
        tid = store.save_theme("工具研究")
        store.link_memory_to_theme(mid, tid, strength=0.5)
        store.link_memory_to_theme(mid, tid, strength=0.9)
        mems = store.get_theme_memories(tid)
        assert len(mems) == 1
        assert abs(mems[0]["strength"] - 0.9) < 1e-9


# ── get_memories_for_detection ─────────────────────────────────────────────────

def test_detection_excludes_reflection_and_context():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        store.save("复盘摘要", type="reflection", importance=5)
        store.save("临时上下文", type="context", importance=5)
        store.save("真正的决策记忆内容", type="decision", importance=4)
        mems = store.get_memories_for_detection()
        types = {m["type"] for m in mems}
        assert "reflection" not in types
        assert "context" not in types
        assert "decision" in types


def test_detection_excludes_low_importance():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        store.save("低重要度记忆", type="insight", importance=2)
        store.save("高重要度记忆内容", type="insight", importance=4)
        mems = store.get_memories_for_detection()
        contents = [m["content"] for m in mems]
        assert "低重要度记忆" not in contents


# ── detect_and_save (mock LLM) ─────────────────────────────────────────────────

_SAMPLE_DETECT_RESPONSE = """{
  "themes": [
    {
      "name": "工具研究模式",
      "description": "遇到复杂任务时转而研究工具和框架",
      "category": "behavior",
      "links": [
        {"memory_id": 1, "strength": 0.9},
        {"memory_id": 2, "strength": 0.7}
      ]
    }
  ]
}"""


def _mock_stream(text: str):
    def _gen(*args, **kwargs):
        yield text
    return _gen


def test_detect_and_save_creates_theme():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        for i in range(4):
            store.save(f"重复行为模式记忆 {i}", type="insight", importance=4)

        import memory.store as orig_store
        orig_db = orig_store.DB_PATH
        orig_store.DB_PATH = store.DB_PATH
        try:
            import memory.patterns as pat_mod
            with patch("memory.patterns.stream_chat", _mock_stream(_SAMPLE_DETECT_RESPONSE)):
                saved = pat_mod.detect_and_save()
        finally:
            orig_store.DB_PATH = orig_db

        themes = store.list_themes()
        assert any(t["name"] == "工具研究模式" for t in themes)


def test_detect_and_save_links_memories():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        m1 = store.save("工具研究记忆一号内容", type="insight", importance=4)
        m2 = store.save("工具研究记忆二号内容", type="insight", importance=4)
        store.save("工具研究记忆三号内容", type="insight", importance=4)

        # Build response with actual memory IDs
        response = f"""{{
  "themes": [
    {{
      "name": "工具研究测试",
      "description": "测试主题",
      "category": "behavior",
      "links": [
        {{"memory_id": {m1}, "strength": 0.9}},
        {{"memory_id": {m2}, "strength": 0.7}}
      ]
    }}
  ]
}}"""

        import memory.store as orig_store
        orig_db = orig_store.DB_PATH
        orig_store.DB_PATH = store.DB_PATH
        try:
            import memory.patterns as pat_mod
            with patch("memory.patterns.stream_chat", _mock_stream(response)):
                    saved = pat_mod.detect_and_save()
        finally:
            orig_store.DB_PATH = orig_db

        assert len(saved) == 1
        tid = saved[0]["id"]
        mems = store.get_theme_memories(tid)
        mem_ids = {m["id"] for m in mems}
        assert m1 in mem_ids
        assert m2 in mem_ids


def test_detect_returns_empty_on_too_few_memories():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        store.save("只有一条记忆", type="insight", importance=4)

        import memory.store as orig_store
        orig_db = orig_store.DB_PATH
        orig_store.DB_PATH = store.DB_PATH
        try:
            import memory.patterns as pat_mod
            result = pat_mod.detect_and_save()
        finally:
            orig_store.DB_PATH = orig_db

        assert result == []


# ── Runner ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_themes_table_exists,
        test_save_theme_basic,
        test_save_theme_deduplicates_and_increments,
        test_list_themes_sorted_by_occurrence,
        test_link_memory_to_theme,
        test_link_memory_upsert,
        test_detection_excludes_reflection_and_context,
        test_detection_excludes_low_importance,
        test_detect_and_save_links_memories,
        test_detect_returns_empty_on_too_few_memories,
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
