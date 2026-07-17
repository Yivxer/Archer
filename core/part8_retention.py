"""Frozen retention experiment for Part 8 shadow stores."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from memory.store import DB_PATH


@dataclass(frozen=True)
class Part8RetentionResult:
    monologues_archived: int
    threads_archived: int
    sent_logs_archived: int

    def to_dict(self) -> dict[str, int]:
        return {
            "monologuesArchived": self.monologues_archived,
            "threadsArchived": self.threads_archived,
            "sentLogsArchived": self.sent_logs_archived,
        }


def archive_part8_records(
    db_path: Path = DB_PATH,
    *,
    now: datetime | None = None,
    monologue_days: int = 30,
    thread_days: int = 180,
    sent_log_days: int = 180,
) -> Part8RetentionResult:
    """Archive old shadow records without deleting user memory."""
    from core.initiative_shadow import init_table as init_initiative_table
    from core.monologue import init_table as init_monologue_table
    from core.part8_threads import init_table as init_thread_table

    now = now or datetime.now()
    init_initiative_table(db_path)
    init_monologue_table(db_path)
    init_thread_table(db_path)
    _ensure_retention_columns(db_path)
    stamp = now.isoformat(timespec="seconds")

    conn = sqlite3.connect(db_path)
    monologue_cutoff = (now - timedelta(days=max(1, int(monologue_days)))).isoformat(timespec="seconds")
    thread_cutoff = (now - timedelta(days=max(1, int(thread_days)))).isoformat(timespec="seconds")
    sent_log_cutoff = (now - timedelta(days=max(1, int(sent_log_days)))).isoformat(timespec="seconds")

    monologues = conn.execute(
        """
        UPDATE part8_monologues
        SET archived_at=?
        WHERE archived_at IS NULL
          AND delivered=0
          AND created_at < ?
        """,
        (stamp, monologue_cutoff),
    ).rowcount
    threads = conn.execute(
        """
        UPDATE part8_threads
        SET status='archived', archived_at=?
        WHERE archived_at IS NULL
          AND last_seen_at < ?
          AND (status IN ('closed', 'stale') OR (status='open' AND resume_logged_at IS NOT NULL))
        """,
        (stamp, thread_cutoff),
    ).rowcount
    sent_logs = conn.execute(
        """
        UPDATE initiative_sent_log
        SET archived_at=?
        WHERE archived_at IS NULL
          AND created_at < ?
        """,
        (stamp, sent_log_cutoff),
    ).rowcount
    conn.commit()
    conn.close()
    return Part8RetentionResult(monologues, threads, sent_logs)


def _ensure_retention_columns(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    for ddl in [
        "ALTER TABLE part8_monologues ADD COLUMN archived_at TEXT",
        "ALTER TABLE part8_threads ADD COLUMN archived_at TEXT",
    ]:
        try:
            conn.execute(ddl)
        except sqlite3.Error:
            pass
    conn.commit()
    conn.close()
