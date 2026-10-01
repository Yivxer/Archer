"""Exercise isolation against real file, SQLite and socket APIs in a child."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tomllib
from pathlib import Path

from scripts.verify_offline import prepare_config

ROOT = Path(__file__).resolve().parents[1]


def test_configuration_uses_only_synthetic_local_state(tmp_path: Path) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()
    shutil.copy2(ROOT / "templates/archer.example.toml", templates)
    prepare_config(tmp_path)
    config = tomllib.loads((tmp_path / "archer.toml").read_text())
    for section, fields in {
        "persona": ["soul_path", "memory_path", "covenant_path", "presence_path", "soul_profile_path"],
        "memory": ["db_path"], "paths": ["sessions_dir", "blog_dir"],
        "obsidian": ["vault_path"],
    }.items():
        assert all(Path(config[section][field]).is_relative_to(tmp_path) for field in fields)
    profiles = [config["api"], *config["model_profiles"].values()]
    assert all(profile["api_key_ref"] == "env:ARCHER_OFFLINE_EMPTY" for profile in profiles)
    assert all(profile["base_url"] == "http://127.0.0.1:9/v1" for profile in profiles)
    assert config["runtime"]["migration_modes"]["task_plan"] == "shadow"
    assert "脱敏测试" in Path(config["persona"]["soul_path"]).read_text()


def test_child_guard_preserves_private_state_and_blocks_real_api(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir()
    sentinel = private / "keep.txt"
    sentinel.write_text("existing user state")
    database = private / "user.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE baseline(value TEXT)")
        connection.execute("INSERT INTO baseline VALUES ('keep')")
    alias = tmp_path / "alias"
    alias.symlink_to(private, target_is_directory=True)
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    shutil.copy2(ROOT / "scripts/offline_test_guard.py", bootstrap)
    environment = os.environ.copy()
    environment.update(PYTHONPATH=str(bootstrap), ARCHER_OFFLINE_PROTECTED_ROOTS=json.dumps([str(private)]))
    code = '''
import os, pathlib, socket, sqlite3, sys
from offline_test_guard import install
install()
private, alias, safe = map(pathlib.Path, sys.argv[1:])
def refused(action):
    try:
        action()
    except PermissionError:
        return
    raise AssertionError("protected operation was allowed")
refused(lambda: (private / "keep.txt").write_text("overwritten"))
refused(lambda: (alias / "keep.txt").write_text("overwritten"))
refused(lambda: sqlite3.connect(private / "user.db"))
refused(lambda: sqlite3.connect("file:" + str(private / "user.db") + "?mode=ro", uri=True))
refused(lambda: os.replace(private / "keep.txt", safe / "moved.txt"))
for address in (("192.0.2.1", 443), ("127.0.0.1", 8765)):
    with socket.socket() as connection:
        refused(lambda: connection.connect(address))
with sqlite3.connect(safe / "safe.db") as connection:
    connection.execute("CREATE TABLE allowed(value TEXT)")
(safe / "safe.txt").write_text("isolated output")
print("protected operations refused; temporary state allowed")
'''
    result = subprocess.run(
        [sys.executable, "-c", code, str(private), str(alias), str(tmp_path)],
        env=environment, capture_output=True, text=True, check=True,
    )
    assert "temporary state allowed" in result.stdout
    assert sentinel.read_text() == "existing user state"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT value FROM baseline").fetchall() == [("keep",)]
    assert (tmp_path / "safe.txt").read_text() == "isolated output"
