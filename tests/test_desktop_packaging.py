from pathlib import Path
import os
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_JSON = ROOT / "client/desktop/package.json"
INSTALL_SCRIPT = ROOT / "client/desktop/scripts/install-local-mac.sh"
HIDE_HELPERS_SCRIPT = ROOT / "client/desktop/scripts/hide-helper-apps-mac.sh"
VERIFY_SCRIPT = ROOT / "scripts/verify_desktop_live.sh"


def test_local_install_hides_electron_helper_apps():
    package_json = PACKAGE_JSON.read_text(encoding="utf-8")
    install_script = INSTALL_SCRIPT.read_text(encoding="utf-8")
    hide_script = HIDE_HELPERS_SCRIPT.read_text(encoding="utf-8")

    assert '"install:local": "bash scripts/install-local-mac.sh"' in package_json
    assert "hide-helper-apps-mac.sh" in install_script
    assert "lsregister" in hide_script
    assert "Archer\\ Helper*.app" in hide_script
    assert "PlistBuddy" not in hide_script


def test_local_install_backs_up_existing_app(tmp_path):
    app_path = tmp_path / "Applications" / "Archer.app"
    built_app = tmp_path / "release" / "mac-arm64" / "Archer.app"
    backup_dir = tmp_path / "backups"
    app_path.mkdir(parents=True)
    built_app.mkdir(parents=True)
    (app_path / "version.txt").write_text("old", encoding="utf-8")
    (built_app / "version.txt").write_text("new", encoding="utf-8")

    env = {
        **os.environ,
        "ARCHER_APP_PATH": str(app_path),
        "ARCHER_BUILT_APP": str(built_app),
        "ARCHER_INSTALL_BACKUP_DIR": str(backup_dir),
        "ARCHER_SKIP_HIDE_HELPERS": "1",
    }

    subprocess.run(["bash", str(INSTALL_SCRIPT)], cwd=INSTALL_SCRIPT.parent.parent, env=env, check=True)

    assert (app_path / "version.txt").read_text(encoding="utf-8") == "new"
    backups = sorted(backup_dir.glob("Archer.app.backup-*"))
    assert len(backups) == 1
    assert (backups[0] / "version.txt").read_text(encoding="utf-8") == "old"


def test_local_install_rolls_back_when_healthcheck_fails(tmp_path):
    app_path = tmp_path / "Applications" / "Archer.app"
    built_app = tmp_path / "release" / "mac-arm64" / "Archer.app"
    backup_dir = tmp_path / "backups"
    token_file = tmp_path / "desktop-api-token"
    app_path.mkdir(parents=True)
    built_app.mkdir(parents=True)
    (app_path / "version.txt").write_text("old", encoding="utf-8")
    (built_app / "version.txt").write_text("new", encoding="utf-8")
    token_file.write_text("test-token", encoding="utf-8")

    env = {
        **os.environ,
        "ARCHER_APP_PATH": str(app_path),
        "ARCHER_BUILT_APP": str(built_app),
        "ARCHER_INSTALL_BACKUP_DIR": str(backup_dir),
        "ARCHER_TOKEN_FILE": str(token_file),
        "ARCHER_API_BASE": "http://127.0.0.1:1",
        "ARCHER_INSTALL_HEALTHCHECK": "1",
        "ARCHER_HEALTHCHECK_ATTEMPTS": "1",
        "ARCHER_HEALTHCHECK_SLEEP": "0",
        "ARCHER_SKIP_HIDE_HELPERS": "1",
    }

    result = subprocess.run(
        ["bash", str(INSTALL_SCRIPT)],
        cwd=INSTALL_SCRIPT.parent.parent,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert (app_path / "version.txt").read_text(encoding="utf-8") == "old"


def test_verify_desktop_live_checks_ready_and_config_doctor(tmp_path):
    app_path = tmp_path / "Applications" / "Archer.app"
    token_file = tmp_path / "desktop-api-token"
    bin_dir = tmp_path / "bin"
    calls_file = tmp_path / "curl-calls.txt"
    app_path.mkdir(parents=True)
    token_file.write_text("test-token", encoding="utf-8")
    bin_dir.mkdir()
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
url="${@: -1}"
printf '%s\n' "$url" >> "$ARCHER_FAKE_CURL_CALLS"
case "$url" in
  */health) exit 0 ;;
  */ready) printf '{"ok":true,"ready":true}' ;;
  */status) printf '{"mode":"auto"}' ;;
  */modes) printf '{"current":"auto","modes":[1,2,3,4,5,6,7,8,9,10,11,12]}' ;;
  */config/doctor) printf '{"ok":true,"summary":{"error":0,"warn":0,"info":0},"issues":[]}' ;;
  *) printf '{}' ;;
esac
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "ARCHER_APP_PATH": str(app_path),
        "ARCHER_TOKEN_FILE": str(token_file),
        "ARCHER_FAKE_CURL_CALLS": str(calls_file),
    }

    result = subprocess.run(
        ["bash", str(VERIFY_SCRIPT)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    calls = calls_file.read_text(encoding="utf-8")
    assert "/ready" in calls
    assert "/config/doctor" in calls
    assert "PROFILE:" in result.stdout
    assert "ready_ms=" in result.stdout
    assert "doctor_ms=" in result.stdout


def test_verify_desktop_live_fails_on_renderer_commonjs_require(tmp_path):
    app_path = tmp_path / "Applications" / "Archer.app"
    resources_dir = app_path / "Contents" / "Resources"
    token_file = tmp_path / "desktop-api-token"
    bin_dir = tmp_path / "bin"
    calls_file = tmp_path / "curl-calls.txt"
    resources_dir.mkdir(parents=True)
    (resources_dir / "app.asar").write_text("fake archive", encoding="utf-8")
    token_file.write_text("test-token", encoding="utf-8")
    bin_dir.mkdir()

    fake_asar = bin_dir / "asar"
    fake_asar.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
cmd="$1"
case "$cmd" in
  list)
    printf '/out/renderer/assets/index-bad.js\\n'
    ;;
  extract-file)
    printf 'const value = require("./connectionState");\\n' > index-bad.js
    ;;
esac
""",
        encoding="utf-8",
    )
    fake_asar.chmod(0o755)

    fake_curl = bin_dir / "curl"
    fake_curl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
url="${@: -1}"
printf '%s\n' "$url" >> "$ARCHER_FAKE_CURL_CALLS"
case "$url" in
  */health) exit 0 ;;
  */ready) printf '{"ok":true,"ready":true}' ;;
  */status) printf '{"mode":"auto"}' ;;
  */modes) printf '{"current":"auto","modes":[1,2,3,4,5,6,7,8,9,10,11,12]}' ;;
  */config/doctor) printf '{"ok":true,"summary":{"error":0,"warn":0,"info":0},"issues":[]}' ;;
  *) printf '{}' ;;
esac
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "ARCHER_APP_PATH": str(app_path),
        "ARCHER_TOKEN_FILE": str(token_file),
        "ARCHER_ASAR_BIN": str(fake_asar),
        "ARCHER_FAKE_CURL_CALLS": str(calls_file),
    }

    result = subprocess.run(
        ["bash", str(VERIFY_SCRIPT)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "renderer bundle 含 CommonJS require" in result.stdout
