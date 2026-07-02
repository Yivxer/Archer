"""Config write lock tests for desktop API persistence."""

from __future__ import annotations

import threading

from terminal.api import _routes as routes
from terminal.api._config import CONFIG_PATH, _load_config


def test_persist_current_expert_survives_parallel_writes(tmp_path, monkeypatch):
    config_path = tmp_path / "archer.toml"
    config_path.write_text('[persona]\ndefault_mode = "listener"\n', encoding="utf-8")
    monkeypatch.setattr("terminal.api._config.CONFIG_PATH", config_path)
    monkeypatch.setattr(routes, "CONFIG_PATH", config_path)

    errors: list[Exception] = []

    def writer(expert_id: str) -> None:
        try:
            routes._persist_current_expert(expert_id)
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=writer, args=(expert_id,))
        for expert_id in ("default", "counselor", "developer", "counselor", "parent-educator")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    cfg = _load_config()
    assert cfg.get("persona", {}).get("default_mode") == "listener"
    assert cfg.get("persona", {}).get("current_expert") in {
        "default",
        "counselor",
        "developer",
        "parent-educator",
    }
