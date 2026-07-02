"""
A7 — 主动触达建议测试
"""
import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _setup_db(tmp: str) -> Path:
    import memory.store as store

    db_path = Path(tmp) / "archer.db"
    store.DB_PATH = db_path
    store.init_db()
    return db_path


def test_deep_session_gap_creates_touch_item():
    from core.proactive import scan_proactive_touch

    with tempfile.TemporaryDirectory() as tmp:
        db_path = _setup_db(tmp)
        sessions_dir = Path(tmp) / "sessions"
        sessions_dir.mkdir()
        old_session = sessions_dir / "20260401_120000.json"
        old_session.write_text(
            json.dumps(
                [
                    {"role": "user", "content": f"深度问题 {idx}"}
                    if idx % 2 == 0 else {"role": "assistant", "content": "回应"}
                    for idx in range(18)
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        items = scan_proactive_touch(
            db_path=db_path,
            sessions_dir=sessions_dir,
            now=datetime(2026, 5, 25, 12, 0, 0),
            cfg={"proactive": {"deep_session_days": 7, "deep_session_turns": 6}},
        )

        assert any(item["kind"] == "deep_session_review" for item in items)


def test_deep_memory_unreviewed_creates_touch_item():
    from core.proactive import scan_proactive_touch

    with tempfile.TemporaryDirectory() as tmp:
        db_path = _setup_db(tmp)
        conn = sqlite3.connect(db_path)
        old = (datetime(2026, 4, 1, 12, 0, 0)).isoformat(timespec="seconds")
        conn.execute(
            "INSERT INTO memories (content, tags, type, importance, status, source, created_at, updated_at, observed_at) "
            "VALUES (?, '', 'reflection_anchor', 5, 'active', 'test', ?, ?, '[]')",
            ("Archer 不是工具，是灵魂伴生体。", old, old),
        )
        conn.commit()
        conn.close()

        items = scan_proactive_touch(
            db_path=db_path,
            sessions_dir=Path(tmp) / "sessions",
            now=datetime(2026, 5, 25, 12, 0, 0),
            cfg={"proactive": {"deep_memory_days": 30}},
        )

        assert any(item["kind"] == "deep_memory_review" for item in items)


def test_high_recent_anxiety_creates_touch_item():
    from core.proactive import scan_proactive_touch

    with tempfile.TemporaryDirectory() as tmp:
        db_path = _setup_db(tmp)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS session_emotions ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, emotion TEXT, score REAL, created_at TEXT)"
        )
        conn.execute(
            "INSERT INTO session_emotions (session_id, emotion, score, created_at) VALUES "
            "('s1', '焦虑', 8.5, '2026-05-24T12:00:00'), "
            "('s2', '焦虑', 7.5, '2026-05-25T12:00:00')"
        )
        conn.commit()
        conn.close()

        items = scan_proactive_touch(
            db_path=db_path,
            sessions_dir=Path(tmp) / "sessions",
            now=datetime(2026, 5, 25, 12, 0, 0),
            cfg={"proactive": {"anxiety_days": 7, "anxiety_score": 7}},
        )

        assert any(item["kind"] == "anxiety_checkin" for item in items)


def test_due_hypothesis_creates_review_touch_item():
    from core.proactive import scan_proactive_touch
    from memory.hypothesis_tracker import create_hypothesis

    with tempfile.TemporaryDirectory() as tmp:
        db_path = _setup_db(tmp)
        create_hypothesis(
            "运动后情绪更稳定",
            "连续三天力量训练后，晚间焦虑会下降。",
            validate_after_days=1,
            now=datetime(2026, 5, 20, 12, 0, 0),
        )

        items = scan_proactive_touch(
            db_path=db_path,
            sessions_dir=Path(tmp) / "sessions",
            now=datetime(2026, 5, 25, 12, 0, 0),
            cfg={"proactive": {"hypothesis_due": True}},
        )

        item = next(item for item in items if item["kind"] == "hypothesis_review")
        assert item["severity"] == "medium"
        assert item["action"] == "验证假设"
        assert item["target"] == "Memory"


def test_muted_due_hypothesis_does_not_create_touch_item():
    from core.proactive import scan_proactive_touch
    from memory.hypothesis_tracker import create_hypothesis

    with tempfile.TemporaryDirectory() as tmp:
        db_path = _setup_db(tmp)
        hid = create_hypothesis(
            "睡眠影响表达",
            "睡眠不足会让表达更急。",
            validate_after_days=1,
            now=datetime(2026, 5, 20, 12, 0, 0),
        )
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE hypotheses SET muted_until=? WHERE id=?",
            ("2026-05-26T12:00:00", hid),
        )
        conn.commit()
        conn.close()

        items = scan_proactive_touch(
            db_path=db_path,
            sessions_dir=Path(tmp) / "sessions",
            now=datetime(2026, 5, 25, 12, 0, 0),
            cfg={"proactive": {"hypothesis_due": True}},
        )

        assert not any(item["kind"] == "hypothesis_review" for item in items)


def test_proactive_touch_api_route(monkeypatch, tmp_path):
    from terminal.api import _routes as routes
    from memory.hypothesis_tracker import create_hypothesis

    monkeypatch.setattr("memory.store.DB_PATH", tmp_path / "archer.db")
    monkeypatch.setattr("core.session.SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(routes, "_load_config", lambda: {"proactive": {"enabled": True, "hypothesis_due": True}})
    import memory.store as store
    store.init_db()
    create_hypothesis(
        "到期假设",
        "这条应该进入主动触达。",
        validate_after_days=1,
        now=datetime.now() - timedelta(days=3),
    )

    status, payload = routes.payload_get("/proactive-touch")

    assert status == 200
    assert payload["enabled"] is True
    assert isinstance(payload["items"], list)
    assert any(item["kind"] == "hypothesis_review" for item in payload["items"])
