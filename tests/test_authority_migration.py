from __future__ import annotations

import sqlite3

import pytest

from core.authority_migration import (
    AuthorityMigrationError,
    AuthorityVerdict,
    MigrationMode,
    authority_cutover_allowed,
    build_authority_comparison,
    list_authority_comparisons,
    record_authority_comparison,
    resolve_migration_mode,
)
from core.run_contract import RunRecord
from core.run_store import create_run
from memory.migrations import run_migrations

NOW = "2026-07-31T12:00:00+08:00"


def _database(tmp_path):
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    create_run(
        db_path,
        RunRecord(
            id="run-authority-1",
            objective="compare authority",
            source="shadow.task_plan",
            created_at=NOW,
            updated_at=NOW,
        ),
        event_id="event-run-authority-created",
    )
    return db_path


def _receipt(*, verdict=AuthorityVerdict.ALIGNED, runtime_state="waiting_user"):
    return build_authority_comparison(
        run_id="run-authority-1",
        domain="task_plan",
        legacy_id="plan-1",
        mode=MigrationMode.SHADOW,
        legacy_snapshot={"status": "proposed", "steps": [1, 2]},
        runtime_snapshot={"state": runtime_state, "steps": [1, 2]},
        verdict=verdict,
        reason=f"task_plan_{verdict.value}",
        recorded_at=NOW,
    )


def test_migration_mode_defaults_to_shadow_and_rejects_unknown_values() -> None:
    assert resolve_migration_mode({}, "task_plan") is MigrationMode.SHADOW
    assert resolve_migration_mode(
        {"runtime": {"migration_modes": {"task_plan": "authoritative"}}},
        "task_plan",
    ) is MigrationMode.AUTHORITATIVE
    with pytest.raises(AuthorityMigrationError, match="unsupported"):
        resolve_migration_mode(
            {"runtime": {"migration_modes": {"task_plan": "live"}}},
            "task_plan",
        )
    with pytest.raises(AuthorityMigrationError, match="unknown authority domain"):
        resolve_migration_mode({}, "unknown")


def test_comparison_receipt_is_append_only_idempotent_and_body_free(tmp_path) -> None:
    db_path = _database(tmp_path)
    first = record_authority_comparison(db_path, _receipt())
    replay_request = build_authority_comparison(
        run_id="run-authority-1",
        domain="task_plan",
        legacy_id="plan-1",
        mode=MigrationMode.SHADOW,
        legacy_snapshot={"status": "proposed", "steps": [1, 2]},
        runtime_snapshot={"state": "waiting_user", "steps": [1, 2]},
        verdict=AuthorityVerdict.ALIGNED,
        reason="task_plan_aligned",
        recorded_at="2026-07-31T12:01:00+08:00",
    )
    replay = record_authority_comparison(db_path, replay_request)

    assert replay == first
    assert len(list_authority_comparisons(db_path, domain="task_plan")) == 1
    serialized = first.to_dict()
    assert "steps" not in serialized
    assert len(str(serialized["legacySnapshotFingerprint"])) == 64

    conn = sqlite3.connect(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE runtime_authority_comparisons SET verdict = 'drifted'"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM runtime_authority_comparisons")
    conn.close()


def test_cutover_uses_latest_receipt_per_legacy_identity(tmp_path) -> None:
    db_path = _database(tmp_path)
    aligned = record_authority_comparison(db_path, _receipt())
    drifted = record_authority_comparison(
        db_path,
        _receipt(
            verdict=AuthorityVerdict.DRIFTED,
            runtime_state="planning",
        ),
    )

    assert authority_cutover_allowed([]) is False
    assert authority_cutover_allowed([aligned]) is True
    assert authority_cutover_allowed([aligned, drifted]) is False
