from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from core.runtime_context import create_runtime_context
from terminal.api.fastapi_app import create_app

from memory.portable_export import (
    build_portable_export,
    create_rotating_backup,
    write_portable_export,
)


def _fixture(tmp_path):
    db_path = tmp_path / "archer.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, content TEXT, status TEXT)")
    conn.execute("CREATE TABLE pending_memories (id INTEGER PRIMARY KEY, content TEXT, status TEXT)")
    conn.execute("INSERT INTO memories VALUES (1, '长期判断', 'active')")
    conn.execute("INSERT INTO pending_memories VALUES (2, '待确认线索', 'pending')")
    conn.commit()
    conn.close()

    soul_path = tmp_path / "SOUL.md"
    soul_path.write_text("# Soul\n\n人的判断。", encoding="utf-8")
    profile_path = tmp_path / "soul-profile.json"
    profile_path.write_text(json.dumps({"core_values": ["诚实"]}), encoding="utf-8")
    config = {
        "persona": {
            "soul_path": str(soul_path),
            "soul_profile_path": str(profile_path),
        },
    }
    return db_path, config


def test_portable_export_contains_soul_and_all_memory_states(tmp_path):
    db_path, config = _fixture(tmp_path)

    export = build_portable_export(
        db_path,
        config,
        now=datetime(2026, 7, 16, 9, 30),
    )

    assert export["format"] == "archer-portable-export"
    assert export["version"] == 1
    assert export["soul"]["profile"] == {"core_values": ["诚实"]}
    assert export["soul"]["files"]["SOUL.md"].startswith("# Soul")
    assert export["memory"]["memories"][0]["content"] == "长期判断"
    assert export["memory"]["pendingMemories"][0]["status"] == "pending"


def test_write_portable_export_creates_json_and_markdown(tmp_path):
    db_path, config = _fixture(tmp_path)

    result = write_portable_export(
        db_path,
        config,
        tmp_path / "exports",
        now=datetime(2026, 7, 16, 9, 30),
    )

    assert result.json_path.is_file()
    assert result.markdown_path.is_file()
    assert json.loads(result.json_path.read_text(encoding="utf-8"))["version"] == 1
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "# Archer 可移植导出" in markdown
    assert "长期判断" in markdown


def test_rotating_backup_keeps_seven_daily_and_four_weekly_pairs(tmp_path):
    db_path, config = _fixture(tmp_path)
    backup_root = tmp_path / "backups"
    start = datetime(2026, 5, 1, 9, 0)

    for offset in range(50):
        create_rotating_backup(
            db_path,
            config,
            backup_root,
            now=start + timedelta(days=offset),
        )

    assert len(list((backup_root / "daily").glob("*.json"))) == 7
    assert len(list((backup_root / "daily").glob("*.md"))) == 7
    assert len(list((backup_root / "weekly").glob("*.json"))) == 4
    assert len(list((backup_root / "weekly").glob("*.md"))) == 4


def test_fastapi_startup_backs_up_and_manual_export_returns_paths(tmp_path):
    soul_path = tmp_path / "SOUL.md"
    soul_path.write_text("# Soul", encoding="utf-8")
    context = create_runtime_context(
        db_path=tmp_path / "archer.db",
        config={"persona": {"soul_path": str(soul_path)}},
        clock=lambda: datetime(2026, 7, 16, 9, 30),
    )
    app = create_app("test-token", runtime_context=context)

    with TestClient(app) as client:
        response = client.post(
            "/exports/portable",
            headers={"Authorization": "Bearer test-token"},
            json={},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["contractVersion"] == 1
    assert (tmp_path / "backups" / "portable" / "daily" / "archer-portable-2026-07-16.json").is_file()
    assert (tmp_path / "exports" / "portable" / body["jsonPath"].split("/")[-1]).is_file()
    assert (tmp_path / "exports" / "portable" / body["markdownPath"].split("/")[-1]).is_file()
