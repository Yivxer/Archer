"""
Step 10 — SOUL Evolution Tests

测试重点：
1. soul_proposals 表 schema
2. add/list/count/resolve soul proposals
3. should_propose 过滤逻辑
4. propose_from_memories / propose_from_obsidian_hints
5. accept：追加写入文件，永不覆写原有内容
6. reject：只更新 status，不动文件
7. 永不自动写入（accept 必须显式调用）
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


# ── schema ─────────────────────────────────────────────────────────────────────

def test_soul_proposals_table_exists():
    import sqlite3
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        conn = sqlite3.connect(store.DB_PATH)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
    assert "soul_proposals" in tables


# ── CRUD ───────────────────────────────────────────────────────────────────────

def test_add_soul_proposal():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        pid = store.add_soul_proposal("我在重建期中学会了接受不确定性", source="reflect")
        assert isinstance(pid, int) and pid > 0


def test_list_soul_proposals_pending():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        store.add_soul_proposal("提议A", source="reflect")
        store.add_soul_proposal("提议B", source="extract")
        proposals = store.list_soul_proposals("pending")
        assert len(proposals) == 2
        assert all(p["status"] == "pending" for p in proposals)


def test_count_soul_proposals():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        assert store.count_soul_proposals() == 0
        store.add_soul_proposal("提议1")
        store.add_soul_proposal("提议2")
        assert store.count_soul_proposals() == 2


def test_resolve_accept_single():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        pid = store.add_soul_proposal("单条接受测试")
        ids = store.resolve_soul_proposal(pid, accepted=True)
        assert pid in ids
        remaining = store.list_soul_proposals("pending")
        assert not remaining
        accepted = store.list_soul_proposals("accepted")
        assert len(accepted) == 1


def test_resolve_reject_all():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        store.add_soul_proposal("提议X")
        store.add_soul_proposal("提议Y")
        ids = store.resolve_soul_proposal("all", accepted=False)
        assert len(ids) == 2
        assert store.count_soul_proposals() == 0
        rejected = store.list_soul_proposals("rejected")
        assert len(rejected) == 2


# ── should_propose ─────────────────────────────────────────────────────────────

def test_should_propose_identity_high_importance():
    from memory.soul import should_propose
    m = {"type": "identity", "importance": 5, "content": "核心身份变化"}
    assert should_propose(m) is True


def test_should_propose_identity_low_importance():
    from memory.soul import should_propose
    m = {"type": "identity", "importance": 3, "content": "低重要度身份"}
    assert should_propose(m) is False


def test_should_propose_obsidian_hint_soul():
    from memory.soul import should_propose
    m = {"type": "insight", "importance": 2, "content": "任意内容", "obsidian_hint": "SOUL.md"}
    assert should_propose(m) is True


def test_should_propose_regular_insight():
    from memory.soul import should_propose
    m = {"type": "insight", "importance": 3, "content": "普通洞察"}
    assert should_propose(m) is False


def test_should_propose_decision_high_importance():
    from memory.soul import should_propose
    m = {"type": "decision", "importance": 4, "content": "重大决策"}
    assert should_propose(m) is True


# ── propose_from_memories ──────────────────────────────────────────────────────

def test_propose_from_memories_filters_correctly():
    import memory.store as store_mod
    from memory.soul import propose_from_memories

    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        orig_db = store_mod.DB_PATH
        store_mod.DB_PATH = store.DB_PATH
        try:
            mems = [
                {"type": "identity", "importance": 5, "content": "核心价值观变化"},
                {"type": "insight",  "importance": 3, "content": "普通洞察"},
                {"type": "decision", "importance": 4, "content": "重大决策记录"},
            ]
            ids = propose_from_memories(mems, source="test")
        finally:
            store_mod.DB_PATH = orig_db

        # identity(5) 和 decision(4) 应生成提议，insight(3) 不应
        assert len(ids) == 2
        proposals = store.list_soul_proposals("pending")
        contents = {p["content"] for p in proposals}
        assert "核心价值观变化" in contents
        assert "重大决策记录" in contents
        assert "普通洞察" not in contents


# ── propose_from_obsidian_hints ────────────────────────────────────────────────

def test_propose_from_obsidian_hints():
    import memory.store as store_mod
    from memory.soul import propose_from_obsidian_hints

    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        orig_db = store_mod.DB_PATH
        store_mod.DB_PATH = store.DB_PATH
        try:
            hints = [
                {"file": "SOUL.md",   "content": "价值观演化描述"},
                {"file": "MEMORY.md", "content": "目标状态更新"},
            ]
            ids = propose_from_obsidian_hints(hints, source="extract")
        finally:
            store_mod.DB_PATH = orig_db

        # 只有 SOUL.md 的 hint 应生成提议
        assert len(ids) == 1
        proposals = store.list_soul_proposals("pending")
        assert proposals[0]["content"] == "价值观演化描述"


# ── accept：追加写入，不覆写 ──────────────────────────────────────────────────

def test_accept_appends_to_soul_md():
    import memory.store as store_mod
    from memory.soul import accept

    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        soul_file = Path(tmp) / "SOUL.md"
        original_content = "# 灵魂档案\n\n这是原始内容。\n"
        soul_file.write_text(original_content, encoding="utf-8")

        orig_db = store_mod.DB_PATH
        store_mod.DB_PATH = store.DB_PATH
        try:
            pid = store.add_soul_proposal("学会了放手是一种力量")
            ids, written = accept(pid, str(soul_file))
        finally:
            store_mod.DB_PATH = orig_db

        assert len(ids) == 1
        assert len(written) == 1

        final_text = soul_file.read_text(encoding="utf-8")
        # 原始内容必须完整保留
        assert original_content in final_text
        # 新内容追加在后面
        assert "学会了放手是一种力量" in final_text
        assert "## 演化记录" in final_text
        # 追加在原始内容之后
        assert final_text.index(original_content) < final_text.index("## 演化记录")


def test_accept_all_appends_multiple():
    import memory.store as store_mod
    from memory.soul import accept

    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        soul_file = Path(tmp) / "SOUL.md"
        soul_file.write_text("# SOUL\n原始内容\n", encoding="utf-8")

        orig_db = store_mod.DB_PATH
        store_mod.DB_PATH = store.DB_PATH
        try:
            store.add_soul_proposal("演化A")
            store.add_soul_proposal("演化B")
            ids, written = accept("all", str(soul_file))
        finally:
            store_mod.DB_PATH = orig_db

        assert len(ids) == 2
        text = soul_file.read_text(encoding="utf-8")
        assert "演化A" in text
        assert "演化B" in text
        assert text.count("## 演化记录") == 2


def test_accept_missing_soul_path_returns_empty():
    import memory.store as store_mod
    from memory.soul import accept

    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        orig_db = store_mod.DB_PATH
        store_mod.DB_PATH = store.DB_PATH
        try:
            pid = store.add_soul_proposal("某提议")
            ids, written = accept(pid, "/不存在/的路径/SOUL.md")
        finally:
            store_mod.DB_PATH = orig_db

        assert ids == []
        assert written == []
        # 提议应仍在 pending
        assert store.count_soul_proposals() == 1


# ── reject：只更新 status ──────────────────────────────────────────────────────

def test_reject_does_not_modify_file():
    import memory.store as store_mod
    from memory.soul import reject

    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        soul_file = Path(tmp) / "SOUL.md"
        soul_file.write_text("原始内容\n", encoding="utf-8")

        orig_db = store_mod.DB_PATH
        store_mod.DB_PATH = store.DB_PATH
        try:
            pid = store.add_soul_proposal("要丢弃的提议")
            reject(pid)
        finally:
            store_mod.DB_PATH = orig_db

        assert soul_file.read_text(encoding="utf-8") == "原始内容\n"
        assert store.count_soul_proposals() == 0


# ── Runner ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_soul_proposals_table_exists,
        test_add_soul_proposal,
        test_list_soul_proposals_pending,
        test_count_soul_proposals,
        test_resolve_accept_single,
        test_resolve_reject_all,
        test_should_propose_identity_high_importance,
        test_should_propose_identity_low_importance,
        test_should_propose_obsidian_hint_soul,
        test_should_propose_regular_insight,
        test_should_propose_decision_high_importance,
        test_propose_from_memories_filters_correctly,
        test_propose_from_obsidian_hints,
        test_accept_appends_to_soul_md,
        test_accept_all_appends_multiple,
        test_accept_missing_soul_path_returns_empty,
        test_reject_does_not_modify_file,
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
