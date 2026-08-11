from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.checkpoint_store import latest_checkpoint, record_checkpoint
from core.obsidian_runtime import (
    begin_approved_write,
    complete_write,
    stage_obsidian_write,
)
from core.run_contract import RunCheckpoint, RunRecord, RunState
from core.run_store import create_run, get_run, transition_run
from core.runtime_context import create_runtime_context
from core.runtime_recovery import (
    RecoveryClassification,
    coordinate_startup_recovery,
)
from memory.migrations import run_migrations
from terminal.api.fastapi_app import create_app


def _create_uncertain_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, str, Path]:
    import core.obsidian_runtime as obsidian_runtime

    db_path = tmp_path / "archer.db"
    target = tmp_path / "note.md"
    target.write_text("verified body", encoding="utf-8")
    run_migrations(db_path)
    binding = stage_obsidian_write(
        db_path,
        objective="恢复时复核测试笔记",
        approval_fingerprint="approval-recovery",
        now="2026-07-25T12:00:00+08:00",
    )
    begin_approved_write(
        db_path,
        binding,
        actual_fingerprint="approval-recovery",
        now="2026-07-25T12:00:01+08:00",
    )
    with monkeypatch.context() as patch:
        patch.setattr(
            obsidian_runtime,
            "_content_matches",
            lambda *_args: (_ for _ in ()).throw(OSError("reader unavailable")),
        )
        complete_write(
            db_path,
            binding,
            args={"content": "verified body", "mode": "overwrite"},
            target_path=str(target),
            approval_fingerprint="approval-recovery",
            tool_call_id="tool-recovery",
            now="2026-07-25T12:00:02+08:00",
        )
    return db_path, binding.run_id, target


def test_startup_recovery_reverifies_existing_artifact_without_rewriting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from skills import obsidian_write

    db_path, run_id, target = _create_uncertain_write(tmp_path, monkeypatch)
    before = target.stat().st_mtime_ns
    monkeypatch.setattr(
        obsidian_write,
        "run_structured",
        lambda payload: (_ for _ in ()).throw(AssertionError("must not rewrite")),
    )

    report = coordinate_startup_recovery(
        db_path,
        now="2026-07-25T12:01:00+08:00",
    )

    item = report.items[0]
    assert item.classification is RecoveryClassification.RECOVERABLE
    assert item.attempted is True
    assert item.reason == "recovered"
    assert item.resulting_state is RunState.COMPLETED
    assert target.read_text(encoding="utf-8") == "verified body"
    assert target.stat().st_mtime_ns == before


def test_startup_recovery_keeps_waiting_approval_idle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.runtime_recovery as runtime_recovery

    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    binding = stage_obsidian_write(
        db_path,
        objective="等待人工批准",
        approval_fingerprint="approval-waiting",
        now="2026-07-25T12:00:00+08:00",
    )
    monkeypatch.setattr(
        runtime_recovery,
        "retry_obsidian_verification",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("waiting run must stay idle")
        ),
    )

    report = coordinate_startup_recovery(
        db_path,
        now="2026-07-25T12:01:00+08:00",
    )

    item = report.items[0]
    assert item.run_id == binding.run_id
    assert item.classification is RecoveryClassification.WAITING
    assert item.reason == "waiting_for_approval"
    assert item.attempted is False


def test_startup_recovery_keeps_waiting_user_idle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.runtime_recovery as runtime_recovery

    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    run = RunRecord(
        id="run-waiting-user",
        objective="等待用户补充目标",
        source="test",
        created_at="2026-07-25T12:00:00+08:00",
        updated_at="2026-07-25T12:00:00+08:00",
    )
    create_run(db_path, run, event_id="event-waiting-user-created")
    run = transition_run(
        db_path,
        run.id,
        RunState.UNDERSTANDING,
        expected_version=run.version,
        event_id="event-waiting-user-understanding",
        updated_at="2026-07-25T12:00:01+08:00",
    )
    transition_run(
        db_path,
        run.id,
        RunState.WAITING_USER,
        expected_version=run.version,
        event_id="event-waiting-user-paused",
        updated_at="2026-07-25T12:00:02+08:00",
    )
    monkeypatch.setattr(
        runtime_recovery,
        "retry_obsidian_verification",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("waiting run must stay idle")
        ),
    )

    report = coordinate_startup_recovery(
        db_path,
        now="2026-07-25T12:01:00+08:00",
    )

    item = report.items[0]
    assert item.classification is RecoveryClassification.WAITING
    assert item.reason == "waiting_for_user"
    assert item.attempted is False


def test_startup_recovery_rejects_stale_cursor_without_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.runtime_recovery as runtime_recovery

    db_path, run_id, _target = _create_uncertain_write(tmp_path, monkeypatch)
    run = get_run(db_path, run_id)
    checkpoint = latest_checkpoint(db_path, run_id)
    assert run is not None
    assert checkpoint is not None
    record_checkpoint(
        db_path,
        RunCheckpoint(
            id="checkpoint-unsupported-version",
            run_id=run_id,
            step_id=run.current_step_id,
            resume_state=RunState.VERIFYING,
            cursor=checkpoint.cursor,
            cursor_version=2,
            created_at="2026-07-25T12:00:03+08:00",
        ),
        expected_run_version=run.version,
        event_id="event-unsupported-version",
    )
    monkeypatch.setattr(
        runtime_recovery,
        "retry_obsidian_verification",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("stale cursor must not resume")
        ),
    )

    report = coordinate_startup_recovery(
        db_path,
        now="2026-07-25T12:01:00+08:00",
    )

    item = report.items[0]
    assert item.classification is RecoveryClassification.INVALID
    assert item.reason == "cursor_version_unsupported"
    assert item.attempted is False
    assert get_run(db_path, run_id).state is RunState.UNCERTAIN


def test_startup_recovery_keeps_snapshot_mismatch_visible(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "archer.db"
    run_migrations(db_path)
    run = RunRecord(
        id="run-tampered",
        objective="保持损坏 Run 可见",
        source="test",
        created_at="2026-07-25T12:00:00+08:00",
        updated_at="2026-07-25T12:00:00+08:00",
    )
    create_run(db_path, run, event_id="event-run-tampered")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE runtime_runs SET objective = 'tampered' WHERE id = ?",
            (run.id,),
        )
        conn.commit()
    finally:
        conn.close()

    report = coordinate_startup_recovery(
        db_path,
        now="2026-07-25T12:01:00+08:00",
    )

    assert report.scanned_runs[0].id == run.id
    assert report.items[0].classification is RecoveryClassification.INVALID
    assert report.items[0].reason == "snapshot_or_ledger_invalid"


def test_fastapi_startup_records_recovery_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from memory import embedder

    db_path, run_id, _target = _create_uncertain_write(tmp_path, monkeypatch)
    monkeypatch.setattr(embedder, "warmup", lambda: None)
    context = create_runtime_context(
        db_path=db_path,
        clock=lambda: datetime(2026, 7, 25, 12, 1, 0),
    )
    app = create_app("test-token", runtime_context=context)

    with TestClient(app):
        report = app.state.runtime_recovery_report

    assert report.items[0].run_id == run_id
    assert report.items[0].reason == "recovered"
    assert get_run(db_path, run_id).state is RunState.COMPLETED
