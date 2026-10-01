from __future__ import annotations

from pathlib import Path

import pytest

from core.config_contract import ConfigValidationError, validate_config
from core.persona_sources import persona_source_status


def test_persona_source_status_reports_missing_and_readable(tmp_path: Path) -> None:
    soul = tmp_path / "SOUL.md"
    soul.write_text("# soul", encoding="utf-8")
    status = persona_source_status({"persona": {"soul_path": str(soul)}})
    assert status["ready"] is False
    assert status["sources"]["soul_path"]["readable"] is True
    assert "memory_path" in status["missing"]


def test_readable_persona_files_do_not_prove_prompt_injection(tmp_path: Path) -> None:
    from core.persona_sources import PERSONA_SOURCE_FIELDS

    persona = {}
    for field in PERSONA_SOURCE_FIELDS:
        path = tmp_path / field
        path.write_text("readable but not assembled", encoding="utf-8")
        persona[field] = str(path)
    status = persona_source_status({"persona": persona})
    assert status["ready"] is True
    assert status["injected"] is False


def test_persona_path_must_be_non_empty_string() -> None:
    with pytest.raises(ConfigValidationError, match="persona.soul_path"):
        validate_config({"persona": {"soul_path": ""}})
