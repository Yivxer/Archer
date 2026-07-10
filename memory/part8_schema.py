"""SQLite schema owned by Part 8 persistence."""
from __future__ import annotations

import sqlite3
from pathlib import Path


def init_initiative_shadow_table(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS initiative_sent_log (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type          TEXT    NOT NULL,
            kind                TEXT    NOT NULL,
            title               TEXT    DEFAULT '',
            message             TEXT    NOT NULL,
            delivered           INTEGER DEFAULT 0,
            decision_trace_json TEXT    DEFAULT '{}',
            created_at          TEXT    NOT NULL,
            feedback            TEXT    DEFAULT '',
            archived_at         TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_initiative_sent_log_created_at "
        "ON initiative_sent_log(created_at)"
    )
    conn.commit()
    conn.close()


def init_part8_threads_table(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS part8_threads (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id          TEXT    DEFAULT '',
            topic               TEXT    NOT NULL,
            prompt              TEXT    DEFAULT '',
            status              TEXT    DEFAULT 'open',
            last_seen_at        TEXT    NOT NULL,
            created_at          TEXT    NOT NULL,
            resume_logged_at    TEXT,
            closed_at           TEXT,
            archived_at         TEXT
        )
    """)
    try:
        conn.execute("ALTER TABLE part8_threads ADD COLUMN archived_at TEXT")
    except sqlite3.Error:
        pass
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_part8_threads_status_seen "
        "ON part8_threads(status, last_seen_at)"
    )
    conn.commit()
    conn.close()


def init_monologue_table(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS part8_monologues (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            source      TEXT    NOT NULL,
            thought     TEXT    NOT NULL,
            trigger     TEXT    DEFAULT '',
            delivered   INTEGER DEFAULT 0,
            trace_json  TEXT    DEFAULT '{}',
            created_at  TEXT    NOT NULL,
            archived_at TEXT
        )
    """)
    try:
        conn.execute("ALTER TABLE part8_monologues ADD COLUMN archived_at TEXT")
    except sqlite3.Error:
        pass
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_part8_monologues_created_at "
        "ON part8_monologues(created_at)"
    )
    conn.commit()
    conn.close()


def init_presence_table(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS part8_presence_state (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            state       TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL
        )
    """)
    conn.commit()
    conn.close()
