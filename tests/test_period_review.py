import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _setup_db(tmp_path: Path) -> Path:
    import memory.store as store

    db_path = tmp_path / "archer.db"
    store.DB_PATH = db_path
    store.init_db()
    return db_path


def _insert_memory(db_path: Path, content: str, memory_type: str, created_at: str, importance: int = 3, depth: int = 3) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO memories (content, tags, type, importance, depth, status, source, created_at, updated_at, observed_at) "
        "VALUES (?, '', ?, ?, ?, 'active', 'test', ?, ?, '[]')",
        (content, memory_type, importance, depth, created_at, created_at),
    )
    conn.commit()
    conn.close()


def _write_session(sessions_dir: Path, name: str, user_messages: list[str]) -> None:
    messages = []
    for message in user_messages:
        messages.append({"role": "user", "content": message})
        messages.append({"role": "assistant", "content": "收到"})
    (sessions_dir / name).write_text(json.dumps(messages, ensure_ascii=False), encoding="utf-8")


def test_weekly_review_collects_sessions_memories_and_growth_markers(tmp_path):
    from memory.period_review import build_period_review

    db_path = _setup_db(tmp_path)
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    _write_session(sessions_dir, "20260524_120000.json", ["推进 Archer Soul 页面", "继续做周报"])
    _write_session(sessions_dir, "20260401_120000.json", ["旧会话不应进入周报"])
    _insert_memory(db_path, "Archer Soul 页面完成结构化展示", "project_mythology", "2026-05-24T12:00:00", 5)
    _insert_memory(db_path, "开始更重视阶段性复盘", "growth_marker", "2026-05-23T12:00:00", 4)
    _insert_memory(db_path, "四月旧记忆", "life_theme", "2026-04-01T12:00:00", 5)

    review = build_period_review(
        db_path=db_path,
        sessions_dir=sessions_dir,
        period="weekly",
        now=datetime(2026, 5, 25, 12, 0, 0),
    )

    assert review["period"] == "weekly"
    assert review["metrics"]["sessions"] == 1
    assert review["metrics"]["user_turns"] == 2
    assert review["metrics"]["memories"] == 2
    assert review["metrics"]["deep_memories"] == 2
    assert review["growth_markers"] == ["开始更重视阶段性复盘"]
    assert review["themes"][0]["type"] in {"growth_marker", "project_mythology"}
    assert "## 本期信号" in review["markdown"]
    assert "Archer Soul 页面完成结构化展示" in review["markdown"]


def test_monthly_and_life_stage_windows_are_larger(tmp_path):
    from memory.period_review import build_period_review

    db_path = _setup_db(tmp_path)
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    _write_session(sessions_dir, "20260501_120000.json", ["月初推进"])
    _insert_memory(db_path, "月内项目进展", "project_mythology", "2026-05-01T12:00:00")
    _insert_memory(db_path, "阶段主题仍然有效", "life_theme", "2026-03-05T12:00:00")

    monthly = build_period_review(
        db_path=db_path,
        sessions_dir=sessions_dir,
        period="monthly",
        now=datetime(2026, 5, 25, 12, 0, 0),
    )
    life_stage = build_period_review(
        db_path=db_path,
        sessions_dir=sessions_dir,
        period="life_stage",
        now=datetime(2026, 5, 25, 12, 0, 0),
    )

    assert monthly["window"]["days"] == 30
    assert life_stage["window"]["days"] == 90
    assert monthly["metrics"]["memories"] == 1
    assert life_stage["metrics"]["memories"] == 2


def test_period_review_counts_depth_four_plus_as_deep(tmp_path):
    from memory.period_review import build_period_review

    db_path = _setup_db(tmp_path)
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    _insert_memory(db_path, "一个普通类型但很深的记忆", "fact", "2026-05-24T12:00:00", importance=2, depth=5)

    review = build_period_review(
        db_path=db_path,
        sessions_dir=sessions_dir,
        period="weekly",
        now=datetime(2026, 5, 25, 12, 0, 0),
    )

    assert review["metrics"]["deep_memories"] == 1


def test_period_review_api_route(monkeypatch, tmp_path):
    from terminal.api import _routes as routes

    db_path = _setup_db(tmp_path)
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    recent = datetime.now() - timedelta(days=1)
    _write_session(sessions_dir, f"{recent:%Y%m%d_%H%M%S}.json", ["写一份复盘"])
    _insert_memory(db_path, "复盘功能开始成型", "growth_marker", recent.isoformat(timespec="seconds"))

    monkeypatch.setattr("memory.store.DB_PATH", db_path)
    monkeypatch.setattr("core.session.SESSIONS_DIR", sessions_dir)

    status, payload = routes.payload_get("/reviews?period=weekly")

    assert status == 200
    assert payload["period"] == "weekly"
    assert payload["metrics"]["sessions"] == 1
    assert "markdown" in payload
