"""
Step 3 — Pending Memory Persistence Tests
验证 pending_memories 表的 CRUD 和崩溃持久性。
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _setup_db(tmp_dir: str):
    """初始化临时 DB，返回 store 模块（已指向临时路径）。"""
    import memory.store as store_mod
    store_mod.DB_PATH = Path(tmp_dir) / "test.db"
    store_mod.init_db()
    return store_mod


# ── 基础 CRUD ──────────────────────────────────────────────────────────────────

def test_add_and_list_pending():
    with tempfile.TemporaryDirectory() as tmp:
        s = _setup_db(tmp)
        pid = s.add_pending("待确认记忆内容", type="insight", importance=4, source="auto")
        assert isinstance(pid, int) and pid > 0

        pends = s.list_pending()
        assert len(pends) == 1
        assert pends[0]["id"] == pid
        assert pends[0]["content"] == "待确认记忆内容"
        assert pends[0]["importance"] == 4
        assert pends[0]["source"] == "auto"


def test_count_pending():
    with tempfile.TemporaryDirectory() as tmp:
        s = _setup_db(tmp)
        assert s.count_pending() == 0
        s.add_pending("第一条")
        s.add_pending("第二条")
        assert s.count_pending() == 2


def test_accept_single_pending():
    """接受单条 pending → 写入 memories，从 pending 删除。"""
    with tempfile.TemporaryDirectory() as tmp:
        s = _setup_db(tmp)
        pid = s.add_pending("单条接受", type="decision", importance=5)
        memory_ids = s.accept_pending(pid)

        assert len(memory_ids) == 1
        assert s.count_pending() == 0

        mems = s.list_all(10)
        assert any(m["id"] == memory_ids[0] for m in mems)
        accepted = next(m for m in mems if m["id"] == memory_ids[0])
        assert accepted["content"] == "单条接受"
        assert accepted["type"] == "decision"


def test_accept_all_pending():
    """接受全部 pending → 全部写入 memories。"""
    with tempfile.TemporaryDirectory() as tmp:
        s = _setup_db(tmp)
        s.add_pending("记忆A")
        s.add_pending("记忆B")
        s.add_pending("记忆C")

        ids = s.accept_pending("all")
        assert len(ids) == 3
        assert s.count_pending() == 0


def test_reject_single_pending():
    """拒绝单条 → 从 pending 删除，不写入 memories。"""
    with tempfile.TemporaryDirectory() as tmp:
        s = _setup_db(tmp)
        pid1 = s.add_pending("保留的")
        pid2 = s.add_pending("要丢弃的")

        n = s.reject_pending(pid2)
        assert n == 1
        assert s.count_pending() == 1
        remaining = s.list_pending()
        assert remaining[0]["id"] == pid1
        assert len(s.list_all(10)) == 0  # 没有写入 memories


def test_reject_all_pending():
    """拒绝全部 → 清空 pending，memories 不变。"""
    with tempfile.TemporaryDirectory() as tmp:
        s = _setup_db(tmp)
        s.add_pending("a")
        s.add_pending("b")

        n = s.reject_pending("all")
        assert n == 2
        assert s.count_pending() == 0
        assert len(s.list_all(10)) == 0


def test_accept_nonexistent_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        s = _setup_db(tmp)
        ids = s.accept_pending(999)
        assert ids == []


def test_update_pending_content():
    with tempfile.TemporaryDirectory() as tmp:
        s = _setup_db(tmp)
        pid = s.add_pending("旧内容")
        assert s.update_pending(pid, "新内容") is True
        pends = s.list_pending()
        assert pends[0]["content"] == "新内容"


def test_update_pending_empty_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        s = _setup_db(tmp)
        pid = s.add_pending("保留内容")
        assert s.update_pending(pid, "   ") is False
        pends = s.list_pending()
        assert pends[0]["content"] == "保留内容"


def test_reject_nonexistent_returns_zero():
    with tempfile.TemporaryDirectory() as tmp:
        s = _setup_db(tmp)
        n = s.reject_pending(999)
        assert n == 0


# ── 持久性：模拟崩溃 ───────────────────────────────────────────────────────────

def test_pending_survives_reimport():
    """
    写入 pending → 重新加载 store 模块（模拟进程重启）→ pending 仍存在。
    """
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "crash_test.db"

        # 第一次写入
        import memory.store as s1
        s1.DB_PATH = db_path
        s1.init_db()
        s1.add_pending("崩溃后应保留的记忆", importance=4)

        # 重新获取连接（模拟进程重启后重新打开 DB）
        import importlib
        importlib.reload(s1)
        s1.DB_PATH = db_path  # 重新指向同一 DB

        pends = s1.list_pending()
        assert len(pends) == 1, "进程重启后 pending 记忆应仍然存在"
        assert pends[0]["content"] == "崩溃后应保留的记忆"


# ── Runner ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_add_and_list_pending,
        test_count_pending,
        test_accept_single_pending,
        test_accept_all_pending,
        test_reject_single_pending,
        test_reject_all_pending,
        test_accept_nonexistent_returns_empty,
        test_update_pending_content,
        test_update_pending_empty_rejected,
        test_reject_nonexistent_returns_zero,
        test_pending_survives_reimport,
    ]

    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
