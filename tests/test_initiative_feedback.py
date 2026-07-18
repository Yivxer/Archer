from __future__ import annotations

import sqlite3
from datetime import datetime

from core.initiative_feedback import claim_review_candidate, exposure_report, record_interaction
from core.initiative_shadow import get_shadow_log, record_shadow_feedback, record_shadow_initiative
from core.presence import set_presence_state


NOW = datetime(2026, 7, 18, 12, 0, 0)


def _candidate(db_path, *, kind: str = "thread_resume", delivered: bool = False) -> int:
    return record_shadow_initiative(
        db_path=db_path,
        event_type="initiative_due",
        kind=kind,
        title="候选",
        message="继续上次的话题？",
        delivered=delivered,
        now=NOW,
    )


def test_claim_selects_only_reviewable_thread_resume_and_preserves_shadow(tmp_path):
    db_path = tmp_path / "archer.db"
    eligible_id = _candidate(db_path)
    _candidate(db_path, kind="reflection")
    _candidate(db_path, delivered=True)

    result = claim_review_candidate(db_path, surface="chat_workspace", now=NOW)

    assert result["reason"] == "candidate"
    assert result["item"]["id"] == eligible_id
    assert result["delivered"] is False
    assert get_shadow_log(db_path, eligible_id)["delivered"] is False


def test_claim_is_stable_for_day_and_does_not_cycle_after_feedback(tmp_path):
    db_path = tmp_path / "archer.db"
    older_id = _candidate(db_path)
    newer_id = _candidate(db_path)

    first = claim_review_candidate(db_path, surface="chat_workspace", now=NOW)
    repeated = claim_review_candidate(db_path, surface="chat_workspace", now=NOW)
    record_shadow_feedback(db_path=db_path, log_id=newer_id, feedback="acknowledged", now=NOW)
    reviewed = claim_review_candidate(db_path, surface="chat_workspace", now=NOW)

    assert first["item"]["id"] == newer_id
    assert repeated["item"]["id"] == newer_id
    assert reviewed["reason"] == "already_reviewed_today"
    assert reviewed["item"] is None
    assert get_shadow_log(db_path, older_id)["feedback"] == ""


def test_muted_presence_returns_no_candidate_or_exposure(tmp_path):
    db_path = tmp_path / "archer.db"
    _candidate(db_path)
    set_presence_state(db_path, "muted", now=NOW)

    result = claim_review_candidate(db_path, surface="chat_workspace", now=NOW)

    assert result["reason"] == "muted"
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM initiative_shadow_interactions").fetchone()[0] == 0
    conn.close()


def test_exposure_report_counts_feedback_and_controls_without_content(tmp_path):
    db_path = tmp_path / "archer.db"
    log_id = _candidate(db_path)
    claim_review_candidate(db_path, surface="chat_workspace", now=NOW)
    record_shadow_feedback(db_path=db_path, log_id=log_id, feedback="too_frequent", now=NOW)
    record_interaction(
        db_path,
        event_type="feedback",
        surface="chat_workspace",
        value="too_frequent",
        initiative_log_id=log_id,
        now=NOW,
    )
    record_interaction(
        db_path,
        event_type="mute",
        surface="chat_workspace",
        value="muted",
        now=NOW,
    )

    report = exposure_report(db_path, surface="chat_workspace", days=14, now=NOW)

    assert report["exposure_count"] == 1
    assert report["feedback_count"] == 1
    assert report["conversion_rate"] == 1.0
    assert report["too_frequent_rate"] == 1.0
    assert report["mute_count"] == 1
    columns = {row[1] for row in sqlite3.connect(db_path).execute("PRAGMA table_info(initiative_shadow_interactions)")}
    assert "message" not in columns
    assert "content" not in columns
