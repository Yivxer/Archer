"""Daily shadow review claims and privacy-minimal interaction metrics."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from core.initiative_shadow import get_shadow_log, normalize_presence_state
from memory.part8_schema import init_initiative_shadow_interactions_table

InteractionEvent = Literal["exposure", "feedback", "mute", "unmute"]
VALID_SURFACES = {"chat_workspace", "today", "legacy"}


def normalize_surface(value: str | None, *, default: str = "legacy") -> str:
    surface = str(value or "").strip().lower()
    if not surface:
        return default
    if surface not in VALID_SURFACES:
        raise ValueError("unsupported initiative surface")
    return surface


def init_table(db_path: Path) -> None:
    init_initiative_shadow_interactions_table(db_path)


def record_interaction(
    db_path: Path,
    *,
    event_type: InteractionEvent,
    surface: str,
    value: str = "",
    initiative_log_id: int | None = None,
    now: datetime | None = None,
) -> None:
    init_table(db_path)
    stamp = now or datetime.now()
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO initiative_shadow_interactions
            (event_type, initiative_log_id, surface, value, exposure_date, created_at)
        VALUES (?, ?, ?, ?, NULL, ?)
        """,
        (
            event_type,
            initiative_log_id,
            normalize_surface(surface),
            str(value or "")[:80],
            stamp.isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    conn.close()


def claim_review_candidate(
    db_path: Path,
    *,
    surface: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Atomically claim at most one shadow candidate per surface and local day."""
    from core.initiative_shadow import init_table as init_shadow_table
    from core.presence import init_table as init_presence_table

    resolved_surface = normalize_surface(surface)
    stamp = now or datetime.now()
    exposure_date = stamp.date().isoformat()
    init_shadow_table(db_path)
    init_presence_table(db_path)
    init_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        presence_row = conn.execute(
            "SELECT state FROM part8_presence_state WHERE id=1"
        ).fetchone()
        presence = normalize_presence_state(presence_row[0] if presence_row else "idle")
        if presence == "muted":
            conn.commit()
            return _claim_result(resolved_surface, exposure_date, "muted")

        exposure = conn.execute(
            """
            SELECT initiative_log_id FROM initiative_shadow_interactions
            WHERE event_type='exposure' AND surface=? AND exposure_date=?
            """,
            (resolved_surface, exposure_date),
        ).fetchone()
        if exposure:
            log_id = int(exposure["initiative_log_id"])
            feedback_row = conn.execute(
                "SELECT feedback, archived_at FROM initiative_sent_log WHERE id=?",
                (log_id,),
            ).fetchone()
            conn.commit()
            if not feedback_row or feedback_row["archived_at"] or str(feedback_row["feedback"] or ""):
                return _claim_result(resolved_surface, exposure_date, "already_reviewed_today")
            return _claim_result(
                resolved_surface,
                exposure_date,
                "candidate",
                get_shadow_log(db_path, log_id),
            )

        candidate = conn.execute(
            """
            SELECT id FROM initiative_sent_log
            WHERE kind='thread_resume'
              AND delivered=0
              AND COALESCE(feedback, '')=''
              AND archived_at IS NULL
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        if not candidate:
            conn.commit()
            return _claim_result(resolved_surface, exposure_date, "no_candidate")
        log_id = int(candidate["id"])
        conn.execute(
            """
            INSERT INTO initiative_shadow_interactions
                (event_type, initiative_log_id, surface, value, exposure_date, created_at)
            VALUES ('exposure', ?, ?, '', ?, ?)
            """,
            (log_id, resolved_surface, exposure_date, stamp.isoformat(timespec="seconds")),
        )
        conn.commit()
        return _claim_result(
            resolved_surface,
            exposure_date,
            "candidate",
            get_shadow_log(db_path, log_id),
        )
    finally:
        conn.close()


def exposure_report(
    db_path: Path,
    *,
    surface: str,
    days: int = 14,
    now: datetime | None = None,
) -> dict[str, Any]:
    resolved_surface = normalize_surface(surface)
    resolved_days = max(1, min(int(days), 90))
    stamp = now or datetime.now()
    cutoff = (stamp.date() - timedelta(days=resolved_days - 1)).isoformat()
    init_table(db_path)
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS exposures,
            SUM(CASE WHEN COALESCE(l.feedback, '') <> '' THEN 1 ELSE 0 END) AS feedback_count,
            SUM(CASE WHEN l.feedback='acknowledged' THEN 1 ELSE 0 END) AS acknowledged_count,
            SUM(CASE WHEN l.feedback='too_frequent' THEN 1 ELSE 0 END) AS too_frequent_count
        FROM initiative_shadow_interactions i
        LEFT JOIN initiative_sent_log l ON l.id=i.initiative_log_id
        WHERE i.event_type='exposure' AND i.surface=? AND i.exposure_date>=?
        """,
        (resolved_surface, cutoff),
    ).fetchone()
    mute_row = conn.execute(
        """
        SELECT COUNT(*) FROM initiative_shadow_interactions
        WHERE event_type='mute' AND surface=? AND created_at>=?
        """,
        (resolved_surface, f"{cutoff}T00:00:00"),
    ).fetchone()
    conn.close()
    exposures = int(row[0] or 0)
    feedback_count = int(row[1] or 0)
    acknowledged = int(row[2] or 0)
    too_frequent = int(row[3] or 0)
    return {
        "surface": resolved_surface,
        "days": resolved_days,
        "exposure_count": exposures,
        "feedback_count": feedback_count,
        "conversion_rate": _ratio(feedback_count, exposures),
        "acknowledged_count": acknowledged,
        "recognition_rate": _ratio(acknowledged, feedback_count),
        "too_frequent_count": too_frequent,
        "too_frequent_rate": _ratio(too_frequent, feedback_count),
        "mute_count": int(mute_row[0] or 0),
    }


def _claim_result(
    surface: str,
    exposure_date: str,
    reason: str,
    item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "shadow": True,
        "delivered": False,
        "surface": surface,
        "exposure_date": exposure_date,
        "reason": reason,
        "item": item,
    }


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0
