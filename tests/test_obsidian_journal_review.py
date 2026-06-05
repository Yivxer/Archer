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


def _insert_emotion(db_path: Path, emotion: str, score: float, created_at: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS session_emotions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, emotion TEXT, score REAL, created_at TEXT)"
    )
    conn.execute(
        "INSERT INTO session_emotions (session_id, emotion, score, created_at) VALUES (?, ?, ?, ?)",
        ("s1", emotion, score, created_at),
    )
    conn.commit()
    conn.close()


def test_journal_review_scans_recent_obsidian_notes_and_emotion_keywords(tmp_path):
    from memory.journal_review import build_journal_review

    vault = tmp_path / "vault"
    journal_dir = vault / "日记"
    journal_dir.mkdir(parents=True)
    (journal_dir / "2026-05-24.md").write_text(
        "# 2026-05-24\n\n今天有点焦虑，但推进 Archer 的时候很专注。晚上明显平静一些。",
        encoding="utf-8",
    )
    (journal_dir / "2026-04-01.md").write_text("这篇太旧，不进入 7 天窗口。", encoding="utf-8")
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "private.md").write_text("焦虑 焦虑 焦虑", encoding="utf-8")

    review = build_journal_review(
        vault_path=vault,
        db_path=tmp_path / "missing.db",
        days=7,
        now=datetime(2026, 5, 25, 12, 0, 0),
    )

    assert review["configured"] is True
    assert review["metrics"]["entries"] == 1
    assert review["metrics"]["characters"] > 20
    assert review["journal_emotions"]["焦虑"] == 1
    assert review["journal_emotions"]["专注"] == 1
    assert review["journal_emotions"]["平静"] == 1
    assert review["entries"][0]["path"] == "日记/2026-05-24.md"
    assert "## 日记信号" in review["markdown"]
    assert "2026-05-24.md" in review["markdown"]


def test_journal_review_merges_session_emotion_trend(tmp_path):
    from memory.journal_review import build_journal_review

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "2026-05-23.md").write_text("今天比较疲惫，但也有一点兴奋。", encoding="utf-8")
    db_path = _setup_db(tmp_path)
    _insert_emotion(db_path, "焦虑", 8.0, "2026-05-23T12:00:00")
    _insert_emotion(db_path, "焦虑", 6.0, "2026-05-24T12:00:00")
    _insert_emotion(db_path, "平静", 7.0, "2026-05-24T12:00:00")

    review = build_journal_review(
        vault_path=vault,
        db_path=db_path,
        days=7,
        now=datetime(2026, 5, 25, 12, 0, 0),
    )

    assert review["session_emotions"]["焦虑"][0]["avg_score"] == 8.0
    assert review["session_emotions"]["焦虑"][1]["avg_score"] == 6.0
    assert review["session_emotions"]["平静"][0]["avg_score"] == 7.0
    assert "焦虑：8.0 -> 6.0" in review["markdown"]


def test_journal_review_api_route(monkeypatch, tmp_path):
    from terminal.api import _routes as routes

    vault = tmp_path / "vault"
    vault.mkdir()
    recent = datetime.now() - timedelta(days=1)
    (vault / f"{recent:%Y-%m-%d}.md").write_text("今天焦虑减少，专注增加。", encoding="utf-8")
    db_path = _setup_db(tmp_path)

    monkeypatch.setattr("memory.store.DB_PATH", db_path)
    monkeypatch.setattr(routes, "_load_config", lambda: {"obsidian": {"vault_path": str(vault)}})

    status, payload = routes.payload_get("/journal-review?days=7")

    assert status == 200
    assert payload["configured"] is True
    assert payload["metrics"]["entries"] == 1
    assert payload["journal_emotions"]["焦虑"] == 1
