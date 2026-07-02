#!/usr/bin/env bash
# Install the local Archer Sensor Obsidian plugin into the configured vault.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_DIR="${ROOT}/integrations/obsidian-archer-sensor"
DEFAULT_VAULT="${HOME}/Library/Mobile Documents/iCloud~md~obsidian/Documents/个人知识管理系统"
VAULT_PATH="${ARCHER_OBSIDIAN_VAULT:-${DEFAULT_VAULT}}"
TARGET_DIR="${VAULT_PATH}/.obsidian/plugins/archer-sensor"
TOKEN_FILE="${ARCHER_DESKTOP_TOKEN_FILE:-${HOME}/Library/Application Support/archer-desktop/security/desktop-api-token}"
API_BASE="${ARCHER_API_BASE:-http://127.0.0.1:8765}"
WRITE_SETTINGS="${ARCHER_SENSOR_WRITE_SETTINGS:-1}"
ENABLE_PLUGIN="${ARCHER_SENSOR_ENABLE_PLUGIN:-1}"

if [[ ! -d "${SOURCE_DIR}" ]]; then
  echo "Missing plugin source: ${SOURCE_DIR}" >&2
  exit 1
fi

if [[ ! -d "${VAULT_PATH}/.obsidian" ]]; then
  echo "Missing Obsidian vault or .obsidian folder: ${VAULT_PATH}" >&2
  exit 1
fi

mkdir -p "${TARGET_DIR}"
install -m 0644 "${SOURCE_DIR}/manifest.json" "${TARGET_DIR}/manifest.json"
install -m 0644 "${SOURCE_DIR}/main.js" "${TARGET_DIR}/main.js"
install -m 0644 "${SOURCE_DIR}/README.md" "${TARGET_DIR}/README.md"

if [[ "${WRITE_SETTINGS}" == "1" ]]; then
  TOKEN=""
  if [[ -f "${TOKEN_FILE}" ]]; then
    TOKEN="$(tr -d '[:space:]' < "${TOKEN_FILE}")"
  fi

  python3 - "$TARGET_DIR/data.json" "$API_BASE" "$TOKEN" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
endpoint = sys.argv[2].rstrip("/")
token = sys.argv[3]

existing = {}
if target.exists():
    try:
        existing = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        existing = {}

settings = {
    "endpoint": endpoint,
    "token": token,
    "sendOnFileOpen": existing.get("sendOnFileOpen", True),
    "includeSelection": existing.get("includeSelection", True),
    "contentPreviewChars": int(existing.get("contentPreviewChars", 2000) or 2000),
    "debounceMs": int(existing.get("debounceMs", 1200) or 1200),
}
target.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
target.chmod(0o600)
PY
fi

if [[ "${ENABLE_PLUGIN}" == "1" ]]; then
  python3 - "${VAULT_PATH}/.obsidian/community-plugins.json" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
plugin_id = "archer-sensor"

plugins = []
if target.exists():
    try:
        parsed = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(parsed, list):
            plugins = [str(item) for item in parsed]
    except Exception:
        plugins = []

if plugin_id not in plugins:
    plugins.append(plugin_id)
target.write_text(json.dumps(plugins, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
fi

echo "Installed Archer Sensor to:"
echo "  ${TARGET_DIR}"
if [[ "${WRITE_SETTINGS}" == "1" ]]; then
  echo "Settings written:"
  echo "  ${TARGET_DIR}/data.json"
fi
if [[ "${ENABLE_PLUGIN}" == "1" ]]; then
  echo "Plugin enabled in:"
  echo "  ${VAULT_PATH}/.obsidian/community-plugins.json"
fi
echo ""
echo "Next in Obsidian:"
echo "  Reload Obsidian if the plugin is not visible yet"
echo "  Command Palette -> Archer Sensor: Send current note focus to Archer"
