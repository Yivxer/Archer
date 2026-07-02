from datetime import datetime, timedelta


def test_part8_retention_archives_old_shadow_material_without_deleting(tmp_path):
    from core.initiative_shadow import record_shadow_initiative
    from core.monologue import record_monologue
    from core.part8_retention import archive_part8_records
    from core.part8_threads import record_unclosed_thread, scan_thread_resume_candidates

    db = tmp_path / "archer.db"
    old = datetime(2026, 1, 1, 9, 0, 0)
    now = datetime(2026, 6, 27, 9, 0, 0)
    record_monologue(db_path=db, source="rules", thought="旧独白", now=old)
    record_shadow_initiative(
        db_path=db,
        event_type="initiative_due",
        kind="thread_resume",
        title="旧候选",
        message="shadow only",
        now=old,
    )
    record_unclosed_thread(db_path=db, topic="旧线索", last_seen_at=old - timedelta(days=1))
    scan_thread_resume_candidates(db_path=db, now=old + timedelta(days=2))

    result = archive_part8_records(
        db,
        now=now,
        monologue_days=30,
        thread_days=30,
        sent_log_days=30,
    )

    assert result.monologues_archived == 1
    assert result.threads_archived == 1
    assert result.sent_logs_archived == 2
