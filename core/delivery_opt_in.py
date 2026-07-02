"""Part 8 explicit opt-in state for initiative delivery.

Opt-in is only one delivery-gate input. Recording consent here never enables
real delivery by itself.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from memory.store import DB_PATH


@dataclass(frozen=True)
class DeliveryOptInState:
    enabled: bool
    updated_at: str | None
    reason: str

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "updatedAt": self.updated_at,
            "reason": self.reason,
        }


def init_table(db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS initiative_delivery_opt_in (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            enabled     INTEGER DEFAULT 0,
            reason      TEXT    DEFAULT '',
            updated_at  TEXT    NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def get_delivery_opt_in(db_path: Path = DB_PATH) -> DeliveryOptInState:
    init_table(db_path)
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT enabled, updated_at, reason FROM initiative_delivery_opt_in WHERE id=1"
    ).fetchone()
    conn.close()
    if not row:
        return DeliveryOptInState(enabled=False, updated_at=None, reason="not_set")
    return DeliveryOptInState(enabled=bool(row[0]), updated_at=row[1], reason=row[2] or "")


def set_delivery_opt_in(
    db_path: Path = DB_PATH,
    *,
    enabled: bool,
    reason: str = "",
    now: datetime | None = None,
) -> DeliveryOptInState:
    init_table(db_path)
    stamp = (now or datetime.now()).isoformat(timespec="seconds")
    clean_reason = reason.strip()[:240]
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO initiative_delivery_opt_in (id, enabled, reason, updated_at)
        VALUES (1, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            enabled=excluded.enabled,
            reason=excluded.reason,
            updated_at=excluded.updated_at
        """,
        (1 if enabled else 0, clean_reason, stamp),
    )
    conn.commit()
    conn.close()
    return get_delivery_opt_in(db_path)
