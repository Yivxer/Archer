"""Keep API approval regression evidence out of the desktop user's audit log."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_tool_approval_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from terminal.api import _config

    monkeypatch.setattr(
        _config, "TOOL_APPROVAL_AUDIT_LOG_PATH", tmp_path / "tool-approval-audit.jsonl"
    )
