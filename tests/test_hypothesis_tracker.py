import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


def _setup_tmp_db(tmp_path: Path):
    import memory.store as store

    store.DB_PATH = tmp_path / "hypotheses.db"
    store.init_db()
    return store


def test_init_db_creates_hypotheses_table(tmp_path):
    store = _setup_tmp_db(tmp_path)

    conn = sqlite3.connect(store.DB_PATH)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(hypotheses)")}
    conn.close()

    for col in (
        "id",
        "title",
        "statement",
        "status",
        "confidence",
        "evidence_json",
        "validate_after",
        "session_id",
    ):
        assert col in cols


def test_create_and_get_hypothesis(tmp_path):
    _setup_tmp_db(tmp_path)
    from memory.hypothesis_tracker import create_hypothesis, get_hypothesis

    now = datetime(2026, 6, 21, 10, 0, 0)
    hid = create_hypothesis(
        title="运动后情绪更稳定",
        statement="连续三天力量训练后，晚间焦虑会下降。",
        source="manual",
        trigger_type="reflection",
        confidence=0.72,
        validate_after_days=3,
        session_id="20260621_100000",
        now=now,
    )

    item = get_hypothesis(hid)

    assert item is not None
    assert item["title"] == "运动后情绪更稳定"
    assert item["status"] == "active"
    assert item["confidence"] == 0.72
    assert item["validate_after"] == (now + timedelta(days=3)).isoformat(timespec="seconds")
    assert item["session_id"] == "20260621_100000"
    assert item["evidence"] == []


def test_due_hypotheses_only_returns_active_items_after_validate_after(tmp_path):
    _setup_tmp_db(tmp_path)
    from memory.hypothesis_tracker import create_hypothesis, list_due_hypotheses, verify_hypothesis

    now = datetime(2026, 6, 21, 10, 0, 0)
    due_id = create_hypothesis("到期假设", "这条应该被提醒。", validate_after_days=1, now=now)
    create_hypothesis("未到期假设", "这条还不该提醒。", validate_after_days=7, now=now)
    verified_id = create_hypothesis("已验证假设", "这条状态不该再提醒。", validate_after_days=1, now=now)
    verify_hypothesis(verified_id, accepted=True, now=now + timedelta(days=2))

    due = list_due_hypotheses(now=now + timedelta(days=2))

    assert [item["id"] for item in due] == [due_id]


def test_add_evidence_and_verify_hypothesis(tmp_path):
    _setup_tmp_db(tmp_path)
    from memory.hypothesis_tracker import add_evidence, create_hypothesis, get_hypothesis, verify_hypothesis

    now = datetime(2026, 6, 21, 10, 0, 0)
    hid = create_hypothesis("睡眠影响表达", "睡眠不足会让表达更急。", now=now)

    add_evidence(hid, "连续两天睡少后，回复更短更急。", source="journal", now=now + timedelta(days=1))
    ok = verify_hypothesis(
        hid,
        accepted=False,
        note="证据不足，可能只是当天任务压力。",
        now=now + timedelta(days=3),
    )
    item = get_hypothesis(hid)

    assert ok is True
    assert item is not None
    assert item["status"] == "rejected"
    assert item["verified_at"] == (now + timedelta(days=3)).isoformat(timespec="seconds")
    assert item["verification_note"] == "证据不足，可能只是当天任务压力。"
    assert item["evidence"] == [
        {
            "content": "连续两天睡少后，回复更短更急。",
            "source": "journal",
            "created_at": (now + timedelta(days=1)).isoformat(timespec="seconds"),
        }
    ]


def test_import_explicit_hypotheses_from_obsidian_journal(tmp_path):
    _setup_tmp_db(tmp_path)
    from memory.hypothesis_tracker import get_hypothesis, import_hypotheses_from_obsidian

    vault = tmp_path / "vault"
    journal_dir = vault / "日记"
    journal_dir.mkdir(parents=True)
    (journal_dir / "2026-06-20.md").write_text(
        "# 2026-06-20\n\n"
        "今天训练后状态更稳。\n"
        "- 假设：如果连续三天力量训练，晚间焦虑会下降。\n"
        "- 普通记录：这行不应该进入 hypotheses。\n",
        encoding="utf-8",
    )

    result = import_hypotheses_from_obsidian(
        vault,
        days=7,
        now=datetime(2026, 6, 21, 10, 0, 0),
    )

    assert result["imported"] == 1
    assert result["skipped"] == 0
    item = get_hypothesis(result["ids"][0])
    assert item is not None
    assert item["source"] == "obsidian_journal"
    assert item["trigger_type"] == "journal_explicit"
    assert item["statement"] == "如果连续三天力量训练，晚间焦虑会下降。"
    assert item["evidence"][0]["content"] == "日记 日记/2026-06-20.md：如果连续三天力量训练，晚间焦虑会下降。"


def test_import_obsidian_hypotheses_is_idempotent_by_statement(tmp_path):
    _setup_tmp_db(tmp_path)
    from memory.hypothesis_tracker import import_hypotheses_from_obsidian, list_hypotheses

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "2026-06-20.md").write_text(
        "Hypothesis: Morning writing before chat makes plans clearer.\n",
        encoding="utf-8",
    )

    now = datetime(2026, 6, 21, 10, 0, 0)
    first = import_hypotheses_from_obsidian(vault, days=7, now=now)
    second = import_hypotheses_from_obsidian(vault, days=7, now=now)

    assert first["imported"] == 1
    assert second["imported"] == 0
    assert second["skipped"] == 1
    assert len(list_hypotheses(status="all")) == 1
