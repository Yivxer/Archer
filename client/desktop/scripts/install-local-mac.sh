#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="${ARCHER_APP_PATH:-/Applications/Archer.app}"
BUILT_APP="${ARCHER_BUILT_APP:-release/mac-arm64/Archer.app}"
BACKUP_DIR="${ARCHER_INSTALL_BACKUP_DIR:-$(dirname "$APP_PATH")/.archer-backups}"
TOKEN_FILE="${ARCHER_TOKEN_FILE:-${HOME}/Library/Application Support/archer-desktop/security/desktop-api-token}"
API_BASE="${ARCHER_API_BASE:-http://127.0.0.1:8765}"
HEALTHCHECK="${ARCHER_INSTALL_HEALTHCHECK:-0}"
HEALTHCHECK_ATTEMPTS="${ARCHER_HEALTHCHECK_ATTEMPTS:-5}"
HEALTHCHECK_SLEEP="${ARCHER_HEALTHCHECK_SLEEP:-1}"
BACKUP_PATH=""

if [[ ! -d "$BUILT_APP" ]]; then
  echo "Built app not found: $BUILT_APP" >&2
  exit 1
fi

rollback_install() {
  if [[ -n "$BACKUP_PATH" && -d "$BACKUP_PATH" ]]; then
    echo "Rolling back to previous Archer.app: $BACKUP_PATH" >&2
    rm -rf "$APP_PATH"
    cp -R "$BACKUP_PATH" "$APP_PATH"
  fi
}

prune_backups() {
  if [[ -d "$BACKUP_DIR" ]]; then
    find "$BACKUP_DIR" -maxdepth 1 -type d -name 'Archer.app.backup-*' \
      | sort -r \
      | tail -n +4 \
      | while IFS= read -r old_backup; do
          rm -rf "$old_backup"
        done
  fi
}

healthcheck_installed_app() {
  if [[ "$HEALTHCHECK" != "1" ]]; then
    return 0
  fi
  if [[ ! -f "$TOKEN_FILE" ]]; then
    echo "Healthcheck token not found: $TOKEN_FILE" >&2
    return 1
  fi
  local token
  token="$(tr -d '[:space:]' < "$TOKEN_FILE")"
  if [[ -z "$token" ]]; then
    echo "Healthcheck token is empty: $TOKEN_FILE" >&2
    return 1
  fi
  local attempt
  for ((attempt = 1; attempt <= HEALTHCHECK_ATTEMPTS; attempt++)); do
    if curl -sf --noproxy '*' -H "Authorization: Bearer ${token}" "${API_BASE}/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$HEALTHCHECK_SLEEP"
  done
  echo "Installed Archer.app healthcheck failed: ${API_BASE}/health" >&2
  return 1
}

if [[ -d "$APP_PATH" ]]; then
  mkdir -p "$BACKUP_DIR"
  BACKUP_PATH="$BACKUP_DIR/Archer.app.backup-$(date +%Y%m%d-%H%M%S)"
  cp -R "$APP_PATH" "$BACKUP_PATH"
  echo "Backed up existing Archer.app to: $BACKUP_PATH"
fi

rm -rf "$APP_PATH"
if ! cp -R "$BUILT_APP" "$APP_PATH"; then
  rollback_install
  exit 1
fi

if [[ "${ARCHER_SKIP_HIDE_HELPERS:-0}" != "1" ]]; then
  if ! bash "$SCRIPT_DIR/hide-helper-apps-mac.sh" "$APP_PATH"; then
    rollback_install
    exit 1
  fi
fi

if ! healthcheck_installed_app; then
  rollback_install
  exit 1
fi

prune_backups
echo "Installed Archer.app to: $APP_PATH"
