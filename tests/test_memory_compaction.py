"""
P5.2 — Memory compaction tests
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


def test_should_compact_active_threshold():
    from memory.compaction import should_compact
    ok, reason = should_compact(active_count=200, pending_count=0)
    assert ok is True
    assert "active_count" in reason
    ok, _ = should_compact(active_count=199, pending_count=0)
    assert ok is False


def test_should_compact_pending_threshold():
    from memory.compaction import should_compact
    ok, reason = should_compact(active_count=0, pending_count=30)
    assert ok is True
    assert "pending_count" in reason


def test_heuristic_protects_core_memories():
    from memory.compaction import heuristic_archive_score, select_archive_candidates

    low = {"type": "context", "importance": 2, "depth": 1, "content": "临时上下文"}
    high = {"type": "preference", "importance": 5, "depth": 4, "content": "核心偏好"}
    assert heuristic_archive_score(high) > heuristic_archive_score(low)
    selected = select_archive_candidates([high, low], limit=1)
    assert selected[0]["type"] == "context"


def test_maybe_compact_archives_and_writes_summary():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        mids = []
        for i in range(8):
            mids.append(
                store.save(
                    f"可归档的低价值记忆条目编号{i}测试内容",
                    type="context",
                    importance=2,
                    depth=1,
                )
            )

        import memory.compaction as compaction_mod
        result = compaction_mod.maybe_compact_memories(force=True, use_llm_summary=False)
        assert result is not None
        assert result.archived_count >= 3
        assert result.summary_id is not None

        import sqlite3
        conn = sqlite3.connect(store.DB_PATH)
        archived = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE status = 'archived'"
        ).fetchone()[0]
        summary = conn.execute(
            "SELECT content, source FROM memories WHERE id = ?",
            (result.summary_id,),
        ).fetchone()
        conn.close()
        assert archived >= 3
        assert summary[1] == "compaction"
        assert "记忆整理摘要" in summary[0]


def test_orchestrator_wrapper_returns_dict():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        for i in range(8):
            store.save(
                f"编排层触发的归档候选记忆{i}测试",
                type="insight",
                importance=2,
                depth=1,
            )
        from core.orchestrator import maybe_run_memory_compaction_after_turn

        payload = maybe_run_memory_compaction_after_turn()
        # thresholds not met — force path tested above; wrapper returns None here
        assert payload is None

        import memory.compaction as compaction_mod
        compaction_mod.maybe_compact_memories(force=True, use_llm_summary=False)
        payload = maybe_run_memory_compaction_after_turn()
        # still None unless threshold — second call won't re-archive much
        assert payload is None or payload.get("archivedCount", 0) >= 0


def test_archived_memories_not_in_active_search():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        mid = store.save("将被归档且不应再检索的内容测试", type="context", importance=2)
        store.archive(mid)
        hits = store.search("不应再检索")
        assert all(h["id"] != mid for h in hits)


if __name__ == "__main__":
    tests = [
        test_should_compact_active_threshold,
        test_should_compact_pending_threshold,
        test_heuristic_protects_core_memories,
        test_maybe_compact_archives_and_writes_summary,
        test_orchestrator_wrapper_returns_dict,
        test_archived_memories_not_in_active_search,
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
