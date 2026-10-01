"""Read-only health contract for Archer persona source files."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

PERSONA_SOURCE_FIELDS = (
    "soul_path",
    "memory_path",
    "covenant_path",
    "presence_path",
    "soul_profile_path",
)


def persona_source_status(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return metadata only; never read or modify persona source contents."""
    persona = config.get("persona", {})
    if not isinstance(persona, Mapping):
        persona = {}
    sources: dict[str, dict[str, Any]] = {}
    for field in PERSONA_SOURCE_FIELDS:
        raw = str(persona.get(field, "") or "").strip()
        path = Path(raw).expanduser() if raw else None
        exists = bool(path and path.is_file())
        readable = bool(exists and path and path.stat().st_mode & 0o444)
        sources[field] = {
            "configured": bool(raw),
            "exists": exists,
            "readable": readable,
            "modifiedAt": path.stat().st_mtime if readable and path else None,
        }
    missing = [field for field, item in sources.items() if not item["readable"]]
    return {
        "ready": not missing,
        # Readiness cannot prove that a source reached this turn's prompt.
        "injected": False,
        "missing": missing,
        "sources": sources,
    }
