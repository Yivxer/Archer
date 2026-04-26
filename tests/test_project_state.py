"""
Step 9 — Project State Tests
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

def test_project_tables_exist():
    import sqlite3
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        conn = sqlite3.connect(store.DB_PATH)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
    assert "projects" in tables
    assert "project_events" in tables


# ── create_project ─────────────────────────────────────────────────────────────

def test_create_project_basic():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        pid = store.create_project("Archer", "终端智能体")
        assert isinstance(pid, int) and pid > 0


def test_create_project_deduplicates():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        p1 = store.create_project("云笺")
        p2 = store.create_project("云笺")
        assert p1 == p2
        assert len(store.list_projects()) == 1


def test_create_project_no_description():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        pid = store.create_project("MinimalProject")
        proj = store.get_project(pid)
        assert proj is not None
        assert proj["description"] == ""


# ── list_projects / get_project ────────────────────────────────────────────────

def test_list_projects_active_only():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        p1 = store.create_project("活跃项目")
        p2 = store.create_project("待归档")
        store.archive_project(p2)
        projs = store.list_projects()
        ids = {p["id"] for p in projs}
        assert p1 in ids
        assert p2 not in ids


def test_list_projects_include_archived():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        p1 = store.create_project("活跃")
        p2 = store.create_project("归档")
        store.archive_project(p2)
        projs = store.list_projects(include_archived=True)
        ids = {p["id"] for p in projs}
        assert p1 in ids
        assert p2 in ids


def test_get_project_by_name():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        pid = store.create_project("Archer", "AI终端")
        proj = store.get_project_by_name("Archer")
        assert proj is not None
        assert proj["id"] == pid
        assert proj["description"] == "AI终端"


def test_get_project_returns_none_for_missing():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        assert store.get_project(9999) is None
        assert store.get_project_by_name("不存在") is None


# ── archive_project ────────────────────────────────────────────────────────────

def test_archive_project():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        pid = store.create_project("要归档的项目")
        assert store.archive_project(pid) is True
        proj = store.get_project(pid)
        assert proj["status"] == "archived"


def test_archive_project_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        pid = store.create_project("归档两次")
        store.archive_project(pid)
        result = store.archive_project(pid)
        assert result is False  # 第二次归档返回 False


# ── log_project_event / get_project_events ────────────────────────────────────

def test_log_event_creates_record():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        pid = store.create_project("Archer")
        eid = store.log_project_event(pid, "note", "完成了 Step 9")
        assert isinstance(eid, int) and eid > 0
        events = store.get_project_events(pid)
        assert len(events) == 1
        assert events[0]["content"] == "完成了 Step 9"
        assert events[0]["event_type"] == "note"


def test_log_event_updates_project_updated_at():
    import time
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        pid = store.create_project("时间戳测试")
        proj_before = store.get_project(pid)
        time.sleep(0.01)
        store.log_project_event(pid, "note", "触发时间更新")
        proj_after = store.get_project(pid)
        assert proj_after["updated_at"] >= proj_before["updated_at"]


def test_get_project_events_ordered_newest_first():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        pid = store.create_project("顺序测试")
        store.log_project_event(pid, "note", "第一条")
        store.log_project_event(pid, "note", "第二条")
        store.log_project_event(pid, "reflect", "复盘")
        events = store.get_project_events(pid)
        assert events[0]["content"] == "复盘"  # 最新在前


def test_get_project_events_limit():
    with tempfile.TemporaryDirectory() as tmp:
        store = _setup_tmp_db(tmp)
        pid = store.create_project("限量测试")
        for i in range(10):
            store.log_project_event(pid, "note", f"事件{i}")
        events = store.get_project_events(pid, limit=3)
        assert len(events) == 3


# ── _active_project_id in archer.py ──────────────────────────────────────────

def test_archer_has_active_project_global():
    """archer.py 应有 _active_project_id 全局变量。"""
    import archer
    assert hasattr(archer, "_active_project_id")


# ── Runner ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_project_tables_exist,
        test_create_project_basic,
        test_create_project_deduplicates,
        test_create_project_no_description,
        test_list_projects_active_only,
        test_list_projects_include_archived,
        test_get_project_by_name,
        test_get_project_returns_none_for_missing,
        test_archive_project,
        test_archive_project_idempotent,
        test_log_event_creates_record,
        test_log_event_updates_project_updated_at,
        test_get_project_events_ordered_newest_first,
        test_get_project_events_limit,
        test_archer_has_active_project_global,
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
