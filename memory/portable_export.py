"""Portable Soul + Memory exports and local rotating backups."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


EXPORT_FORMAT = "archer-portable-export"
EXPORT_VERSION = 1
DAILY_BACKUPS = 7
WEEKLY_BACKUPS = 4


@dataclass(frozen=True)
class PortableExportPaths:
    json_path: Path
    markdown_path: Path


def _read_text(path_value: object) -> str:
    path = Path(str(path_value or "")).expanduser()
    if not path_value or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_json(path_value: object) -> dict:
    raw = _read_text(path_value)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _table_rows(db_path: Path, table: str) -> list[dict]:
    if table not in {"memories", "pending_memories"}:
        raise ValueError(f"unsupported export table: {table}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
    return [dict(row) for row in rows]


def build_portable_export(
    db_path: Path,
    config: dict,
    *,
    now: datetime | None = None,
) -> dict:
    timestamp = now or datetime.now()
    persona = config.get("persona", {}) if isinstance(config.get("persona"), dict) else {}
    soul_files = {
        "SOUL.md": _read_text(persona.get("soul_path")),
        "MEMORY.md": _read_text(persona.get("memory_path")),
        "COVENANT.md": _read_text(persona.get("covenant_path")),
        "PRESENCE.md": _read_text(persona.get("presence_path")),
    }
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exportedAt": timestamp.isoformat(timespec="seconds"),
        "soul": {
            "profile": _read_json(persona.get("soul_profile_path")),
            "files": soul_files,
        },
        "memory": {
            "memories": _table_rows(db_path, "memories"),
            "pendingMemories": _table_rows(db_path, "pending_memories"),
        },
    }


def portable_export_markdown(export: dict) -> str:
    lines = [
        "# Archer 可移植导出",
        "",
        f"- 导出时间：{export.get('exportedAt', '')}",
        f"- 格式版本：{export.get('version', '')}",
    ]
    soul = export.get("soul", {})
    lines.extend(["", "## Soul Profile", "", "```json", json.dumps(soul.get("profile", {}), ensure_ascii=False, indent=2), "```"])
    for name, content in soul.get("files", {}).items():
        if content:
            lines.extend(["", f"## {name}", "", str(content).strip()])
    memory = export.get("memory", {})
    lines.extend(["", "## Memories", ""])
    for item in memory.get("memories", []):
        lines.append(f"- [{item.get('id', '')}] {item.get('content', '')}")
    lines.extend(["", "## Pending Memories", ""])
    for item in memory.get("pendingMemories", []):
        lines.append(f"- [{item.get('status', '')}] {item.get('content', '')}")
    return "\n".join(lines).rstrip() + "\n"


def _write_pair(export: dict, directory: Path, stem: str) -> PortableExportPaths:
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"{stem}.json"
    markdown_path = directory / f"{stem}.md"
    json_tmp = json_path.with_suffix(".json.tmp")
    markdown_tmp = markdown_path.with_suffix(".md.tmp")
    json_tmp.write_text(json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_tmp.write_text(portable_export_markdown(export), encoding="utf-8")
    json_tmp.replace(json_path)
    markdown_tmp.replace(markdown_path)
    return PortableExportPaths(json_path=json_path, markdown_path=markdown_path)


def write_portable_export(
    db_path: Path,
    config: dict,
    output_dir: Path,
    *,
    now: datetime | None = None,
) -> PortableExportPaths:
    timestamp = now or datetime.now()
    export = build_portable_export(db_path, config, now=timestamp)
    return _write_pair(export, output_dir, f"archer-portable-{timestamp:%Y%m%dT%H%M%S}")


def _prune(directory: Path, keep: int) -> None:
    snapshots = sorted(directory.glob("archer-portable-*.json"))
    for json_path in snapshots[:-keep]:
        json_path.unlink(missing_ok=True)
        json_path.with_suffix(".md").unlink(missing_ok=True)


def create_rotating_backup(
    db_path: Path,
    config: dict,
    backup_root: Path,
    *,
    now: datetime | None = None,
) -> dict[str, PortableExportPaths]:
    timestamp = now or datetime.now()
    export = build_portable_export(db_path, config, now=timestamp)
    daily = _write_pair(export, backup_root / "daily", f"archer-portable-{timestamp:%Y-%m-%d}")
    iso_year, iso_week, _ = timestamp.isocalendar()
    weekly = _write_pair(export, backup_root / "weekly", f"archer-portable-{iso_year}-W{iso_week:02d}")
    _prune(backup_root / "daily", DAILY_BACKUPS)
    _prune(backup_root / "weekly", WEEKLY_BACKUPS)
    return {"daily": daily, "weekly": weekly}
