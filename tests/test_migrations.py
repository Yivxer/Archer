from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from memory.migrations import (
    LATEST_SCHEMA_VERSION,
    Migration,
    MigrationError,
    run_migrations,
)
from core.runtime_context import create_runtime_context
from terminal.api.fastapi_app import create_app


def _schema_rows(db_path):
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT version, checksum, description, applied_at "
        "FROM schema_version ORDER BY version"
    ).fetchall()
    conn.close()
    return rows


@pytest.mark.integration
def test_empty_database_upgrades_to_latest_schema(tmp_path):
    db_path = tmp_path / "memory" / "archer.db"

    result = run_migrations(
        db_path,
        clock=lambda: datetime(2026, 7, 10, 13, 0, 0),
    )

    assert result.version == LATEST_SCHEMA_VERSION
    assert result.applied == [LATEST_SCHEMA_VERSION]
    rows = _schema_rows(db_path)
    assert rows[0][0] == LATEST_SCHEMA_VERSION
    assert rows[0][1]
    assert rows[0][2]
    assert rows[0][3] == "2026-07-10T13:00:00"

    conn = sqlite3.connect(db_path)
    assert conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='memories'"
    ).fetchone()[0] == 1
    conn.close()


@pytest.mark.integration
def test_existing_database_upgrades_without_losing_data(tmp_path):
    db_path = tmp_path / "archer.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
    conn.execute("INSERT INTO sentinel VALUES ('keep-me')")
    conn.commit()
    conn.close()

    result = run_migrations(db_path)

    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT value FROM sentinel").fetchone()[0] == "keep-me"
    conn.close()
    assert result.backup_path is not None
    assert result.backup_path.exists()


@pytest.mark.integration
def test_repeated_start_does_not_reapply_migrations_or_create_backup(tmp_path):
    db_path = tmp_path / "archer.db"
    first = run_migrations(db_path)
    second = run_migrations(db_path)

    assert first.applied == [LATEST_SCHEMA_VERSION]
    assert second.applied == []
    assert second.backup_path is None
    assert len(_schema_rows(db_path)) == 1


@pytest.mark.integration
def test_failed_migration_restores_backup_and_removes_partial_schema(tmp_path):
    db_path = tmp_path / "archer.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
    conn.execute("INSERT INTO sentinel VALUES ('original')")
    conn.commit()
    conn.close()

    def apply_partial(path):
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE partial_write (id INTEGER)")
        connection.commit()
        connection.close()

    def fail_after_partial(_path):
        raise RuntimeError("fault injection")

    migrations = (
        Migration.create(1, "partial", apply_partial),
        Migration.create(2, "fails", fail_after_partial),
    )

    with pytest.raises(MigrationError, match="fault injection"):
        run_migrations(db_path, migrations=migrations)

    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT value FROM sentinel").fetchone()[0] == "original"
    assert conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE name='partial_write'"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE name='schema_version'"
    ).fetchone()[0] == 0
    conn.close()


@pytest.mark.integration
def test_fastapi_startup_migrates_context_database_before_scheduler(tmp_path):
    db_path = tmp_path / "runtime" / "archer.db"
    context = create_runtime_context(
        db_path=db_path,
        clock=lambda: datetime(2026, 7, 10, 14, 0, 0),
    )
    app = create_app("test-token", runtime_context=context)

    with TestClient(app) as client:
        response = client.get("/ready")
        assert response.status_code == 200

    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT max(version) FROM schema_version").fetchone()[0] == LATEST_SCHEMA_VERSION
    assert conn.execute(
        "SELECT count(*) FROM scheduled_tasks "
        "WHERE skill_name='reflection_scheduler.scan_hypotheses'"
    ).fetchone()[0] == 1
    conn.close()
    assert (db_path.parent / "schedules.json").exists()
