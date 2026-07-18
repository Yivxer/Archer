from __future__ import annotations

import json
import sqlite3
import re
from datetime import datetime, timedelta
from pathlib import Path

STATUSES = ("active", "verified", "rejected", "dismissed")
MAX_OBSIDIAN_NOTE_CHARS = 12000
HYPOTHESIS_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:假设|Hypothesis)\s*[：:]\s*(?P<statement>.+?)\s*$",
    re.IGNORECASE,
)


def _now() -> datetime:
    return datetime.now()


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).isoformat(timespec="seconds")


def _conn(db_path: Path | None = None) -> sqlite3.Connection:
    import memory.store as _store

    conn = sqlite3.connect(db_path or _store.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_hypotheses_table(db_path: Path | None = None) -> None:
    conn = _conn(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hypotheses (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            title             TEXT    NOT NULL,
            statement         TEXT    NOT NULL,
            status            TEXT    DEFAULT 'active',
            source            TEXT    DEFAULT 'manual',
            trigger_type      TEXT    DEFAULT '',
            confidence        REAL    DEFAULT 0.7,
            evidence_json     TEXT    DEFAULT '[]',
            validate_after    TEXT    NOT NULL,
            created_at        TEXT    NOT NULL,
            updated_at        TEXT    NOT NULL,
            last_reviewed_at  TEXT,
            verified_at       TEXT,
            session_id        TEXT,
            verification_note TEXT    DEFAULT '',
            muted_until       TEXT
        )
    """)
    for ddl in [
        "ALTER TABLE hypotheses ADD COLUMN trigger_type TEXT DEFAULT ''",
        "ALTER TABLE hypotheses ADD COLUMN evidence_json TEXT DEFAULT '[]'",
        "ALTER TABLE hypotheses ADD COLUMN last_reviewed_at TEXT",
        "ALTER TABLE hypotheses ADD COLUMN verified_at TEXT",
        "ALTER TABLE hypotheses ADD COLUMN session_id TEXT",
        "ALTER TABLE hypotheses ADD COLUMN verification_note TEXT DEFAULT ''",
        "ALTER TABLE hypotheses ADD COLUMN muted_until TEXT",
    ]:
        try:
            conn.execute(ddl)
        except Exception:
            pass
    conn.commit()
    conn.close()


def create_hypothesis(
    title: str,
    statement: str,
    *,
    source: str = "manual",
    trigger_type: str = "",
    confidence: float = 0.7,
    validate_after_days: int = 14,
    session_id: str | None = None,
    now: datetime | None = None,
) -> int:
    title = title.strip()
    statement = statement.strip()
    if not title:
        raise ValueError("title is required")
    if not statement:
        raise ValueError("statement is required")
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except Exception:
        confidence = 0.7
    try:
        validate_after_days = max(1, int(validate_after_days))
    except Exception:
        validate_after_days = 14

    base = now or _now()
    validate_after = _stamp(base + timedelta(days=validate_after_days))
    created_at = _stamp(base)
    conn = _conn()
    cur = conn.execute(
        """INSERT INTO hypotheses
           (title, statement, status, source, trigger_type, confidence,
            evidence_json, validate_after, created_at, updated_at, session_id)
           VALUES (?, ?, 'active', ?, ?, ?, '[]', ?, ?, ?, ?)""",
        (title, statement, source.strip() or "manual", trigger_type.strip(),
         confidence, validate_after, created_at, created_at, session_id),
    )
    hid = cur.lastrowid
    conn.commit()
    conn.close()
    assert hid is not None, "INSERT 未返回 lastrowid"
    return int(hid)


def get_hypothesis(hypothesis_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM hypotheses WHERE id=?", (hypothesis_id,)).fetchone()
    conn.close()
    return _hydrate(row) if row else None


def list_hypotheses(*, status: str = "active", limit: int = 50) -> list[dict]:
    try:
        limit = max(1, min(int(limit), 200))
    except Exception:
        limit = 50
    conn = _conn()
    if status == "all":
        rows = conn.execute(
            "SELECT * FROM hypotheses ORDER BY updated_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    else:
        if status not in STATUSES:
            status = "active"
        rows = conn.execute(
            "SELECT * FROM hypotheses WHERE status=? ORDER BY updated_at DESC, id DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    conn.close()
    return [_hydrate(row) for row in rows]


def list_due_hypotheses(*, now: datetime | None = None, limit: int = 20) -> list[dict]:
    stamp = _stamp(now)
    conn = _conn()
    rows = conn.execute(
        """SELECT * FROM hypotheses
           WHERE status='active'
             AND validate_after <= ?
             AND (muted_until IS NULL OR muted_until = '' OR muted_until <= ?)
           ORDER BY validate_after ASC, id ASC
           LIMIT ?""",
        (stamp, stamp, limit),
    ).fetchall()
    conn.close()
    return [_hydrate(row) for row in rows]


def import_hypotheses_from_obsidian(
    vault_path: str | Path | None,
    *,
    days: int = 30,
    validate_after_days: int = 14,
    now: datetime | None = None,
    limit: int = 20,
) -> dict:
    vault = Path(vault_path).expanduser() if vault_path else None
    if not vault or not vault.exists() or not vault.is_dir():
        return {"ok": False, "configured": False, "imported": 0, "skipped": 0, "ids": []}

    base = now or _now()
    start = (base - timedelta(days=_clean_days(days))).replace(hour=0, minute=0, second=0, microsecond=0)
    existing = _existing_obsidian_statements()
    imported_ids: list[int] = []
    skipped = 0

    for match in _iter_obsidian_hypothesis_lines(vault, start=start, end=base):
        statement = match["statement"]
        if statement in existing:
            skipped += 1
            continue
        hid = create_hypothesis(
            _title_from_statement(statement),
            statement,
            source="obsidian_journal",
            trigger_type="journal_explicit",
            validate_after_days=validate_after_days,
            now=base,
        )
        add_evidence(
            hid,
            f"日记 {match['path']}：{statement}",
            source="obsidian_journal",
            now=base,
        )
        existing.add(statement)
        imported_ids.append(hid)
        if len(imported_ids) >= _clean_limit(limit):
            break

    return {
        "ok": True,
        "configured": True,
        "imported": len(imported_ids),
        "skipped": skipped,
        "ids": imported_ids,
    }


def add_evidence(
    hypothesis_id: int,
    content: str,
    *,
    source: str = "manual",
    now: datetime | None = None,
) -> bool:
    item = get_hypothesis(hypothesis_id)
    if item is None:
        return False
    content = content.strip()
    if not content:
        return False
    evidence = item["evidence"]
    evidence.append({
        "content": content,
        "source": source.strip() or "manual",
        "created_at": _stamp(now),
    })
    conn = _conn()
    cur = conn.execute(
        "UPDATE hypotheses SET evidence_json=?, updated_at=? WHERE id=?",
        (json.dumps(evidence, ensure_ascii=False), _stamp(now), hypothesis_id),
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def _iter_obsidian_hypothesis_lines(vault: Path, *, start: datetime, end: datetime) -> list[dict]:
    matches = []
    vault_real = vault.resolve()
    for path in sorted(vault.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(vault).parts):
            continue
        if path.is_symlink():
            continue
        try:
            resolved = path.resolve()
            resolved.relative_to(vault_real)
        except Exception:
            continue
        note_date = _note_date(path) or datetime.fromtimestamp(path.stat().st_mtime)
        if not (start <= note_date <= end):
            continue
        try:
            text = path.read_text(encoding="utf-8")[:MAX_OBSIDIAN_NOTE_CHARS]
        except Exception:
            continue
        for line in text.splitlines():
            match = HYPOTHESIS_LINE_RE.match(line)
            if not match:
                continue
            statement = match.group("statement").strip()
            if statement:
                matches.append({
                    "path": path.relative_to(vault).as_posix(),
                    "statement": statement,
                })
    return matches


def _existing_obsidian_statements() -> set[str]:
    conn = _conn()
    rows = conn.execute(
        "SELECT statement FROM hypotheses WHERE source='obsidian_journal'"
    ).fetchall()
    conn.close()
    return {str(row["statement"]) for row in rows}


def _title_from_statement(statement: str) -> str:
    clean = re.sub(r"\s+", " ", statement).strip()
    return clean[:32] or "Obsidian 日记假设"


def _note_date(path: Path) -> datetime | None:
    match = re.search(r"(20\d{2})[-_.年]?(0\d|1[0-2])[-_.月]?([0-2]\d|3[01])", path.stem)
    if not match:
        return None
    try:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _clean_days(value: object) -> int:
    try:
        days = int(str(value)) if not isinstance(value, (int, float)) else int(value)
    except Exception:
        days = 30
    return max(1, min(days, 365))


def _clean_limit(value: object) -> int:
    try:
        limit = int(str(value)) if not isinstance(value, (int, float)) else int(value)
    except Exception:
        limit = 20
    return max(1, min(limit, 100))


def verify_hypothesis(
    hypothesis_id: int,
    *,
    accepted: bool,
    note: str = "",
    now: datetime | None = None,
) -> bool:
    status = "verified" if accepted else "rejected"
    stamp = _stamp(now)
    conn = _conn()
    cur = conn.execute(
        """UPDATE hypotheses
           SET status=?, verified_at=?, last_reviewed_at=?, updated_at=?, verification_note=?
           WHERE id=?""",
        (status, stamp, stamp, stamp, note.strip(), hypothesis_id),
    )
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def _hydrate(row: sqlite3.Row) -> dict:
    item = dict(row)
    try:
        item["evidence"] = json.loads(item.get("evidence_json") or "[]")
    except Exception:
        item["evidence"] = []
    return item
