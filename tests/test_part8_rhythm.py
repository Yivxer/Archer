from datetime import datetime, timedelta
import sqlite3

import pytest


def test_rhythm_returns_uniform_distribution_for_cold_start():
    from core.rhythm import HOURS_PER_WEEK, build_hourly_rhythm

    now = datetime(2026, 6, 25, 12, 0, 0)
    events = [
        now - timedelta(days=1),
        now - timedelta(days=3, hours=2),
        now - timedelta(days=8, hours=5),
    ]

    profile = build_hourly_rhythm(events, now=now)

    assert profile.status == "cold_start"
    assert profile.observed_days < 14
    assert len(profile.hourly_weights) == HOURS_PER_WEEK
    assert sum(profile.hourly_weights) == pytest.approx(1.0)
    assert profile.hourly_weights == pytest.approx([1 / HOURS_PER_WEEK] * HOURS_PER_WEEK)
    assert profile.confidence == 0.0


def test_rhythm_models_weekly_hour_preference_after_two_weeks():
    from core.rhythm import build_hourly_rhythm, hour_slot

    now = datetime(2026, 6, 25, 12, 0, 0)
    target_slot = hour_slot(datetime(2026, 6, 1, 9, 0, 0))
    events = [
        datetime(2026, 6, 1, 9, 0, 0),
        datetime(2026, 6, 8, 9, 15, 0),
        datetime(2026, 6, 15, 9, 30, 0),
        datetime(2026, 6, 22, 9, 45, 0),
        datetime(2026, 6, 4, 21, 0, 0),
    ]

    profile = build_hourly_rhythm(events, now=now)

    assert profile.status == "modeled"
    assert profile.observed_days >= 14
    assert profile.hourly_weights[target_slot] == max(profile.hourly_weights)
    assert profile.confidence > 0


def test_session_activity_stamps_are_loaded_from_session_filenames(tmp_path):
    from core.rhythm import load_session_activity_stamps

    (tmp_path / "20260601_090000.json").write_text("[]", encoding="utf-8")
    (tmp_path / "20260602_211500.json").write_text("[]", encoding="utf-8")
    (tmp_path / "bad.json").write_text("[]", encoding="utf-8")
    (tmp_path / "20260603_100000.txt").write_text("[]", encoding="utf-8")

    stamps = load_session_activity_stamps(tmp_path)

    assert stamps == [
        datetime(2026, 6, 1, 9, 0, 0),
        datetime(2026, 6, 2, 21, 15, 0),
    ]


def test_moment_detector_marks_late_night_as_rest():
    from core.moments import detect_moment

    moment = detect_moment(datetime(2026, 6, 25, 1, 30, 0))

    assert moment.kind == "rest"
    assert moment.reason == "quiet_hours"
    assert moment.score == 1.0


def test_moment_detector_marks_weekday_daytime_as_work():
    from core.moments import detect_moment

    moment = detect_moment(datetime(2026, 6, 25, 10, 0, 0))

    assert moment.kind == "work"
    assert moment.reason == "weekday_daytime"


def test_moment_detector_uses_rhythm_peak_for_deep_conversation_window():
    from core.moments import detect_moment
    from core.rhythm import build_hourly_rhythm

    profile = build_hourly_rhythm(
        [
            datetime(2026, 6, 1, 21, 0, 0),
            datetime(2026, 6, 8, 21, 15, 0),
            datetime(2026, 6, 15, 21, 30, 0),
            datetime(2026, 6, 22, 21, 45, 0),
            datetime(2026, 6, 4, 9, 0, 0),
        ],
        now=datetime(2026, 6, 25, 12, 0, 0),
    )

    moment = detect_moment(datetime(2026, 6, 22, 21, 0, 0), rhythm=profile)

    assert moment.kind == "deep_conversation"
    assert moment.reason == "rhythm_peak"
    assert moment.score > 0.5


def test_reflection_cycle_is_due_without_previous_reflection():
    from core.reflection_cycle import evaluate_reflection_cycle

    signal = evaluate_reflection_cycle([], now=datetime(2026, 6, 25, 12, 0, 0))

    assert signal.due is True
    assert signal.cycle == "weekly"
    assert signal.reason == "no_previous_reflection"


def test_reflection_cycle_waits_inside_weekly_gap():
    from core.reflection_cycle import evaluate_reflection_cycle

    signal = evaluate_reflection_cycle(
        [datetime(2026, 6, 23, 12, 0, 0)],
        now=datetime(2026, 6, 25, 12, 0, 0),
    )

    assert signal.due is False
    assert signal.reason == "within_cycle"
    assert signal.days_since_last == 2


def test_reflection_cycle_becomes_due_after_weekly_gap():
    from core.reflection_cycle import evaluate_reflection_cycle

    signal = evaluate_reflection_cycle(
        [datetime(2026, 6, 10, 12, 0, 0)],
        now=datetime(2026, 6, 25, 12, 0, 0),
    )

    assert signal.due is True
    assert signal.reason == "cycle_due"
    assert signal.days_since_last == 15


def test_reflection_stamps_load_from_memory_db(tmp_path):
    from core.reflection_cycle import load_reflection_stamps

    db_path = tmp_path / "archer.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            type TEXT DEFAULT 'insight',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO memories (content, type, created_at) VALUES (?, ?, ?)",
        ("复盘摘要", "reflection", "2026-06-10T12:00:00"),
    )
    conn.execute(
        "INSERT INTO memories (content, type, created_at) VALUES (?, ?, ?)",
        ("反思锚点", "reflection_anchor", "2026-06-20T21:30:00"),
    )
    conn.execute(
        "INSERT INTO memories (content, type, created_at) VALUES (?, ?, ?)",
        ("普通记忆", "insight", "2026-06-21T09:00:00"),
    )
    conn.commit()
    conn.close()

    stamps = load_reflection_stamps(db_path)

    assert stamps == [
        datetime(2026, 6, 10, 12, 0, 0),
        datetime(2026, 6, 20, 21, 30, 0),
    ]
