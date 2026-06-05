#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="$ROOT_DIR/client/desktop"
RELEASE_DIR="$DESKTOP_DIR/release"
APP_NAME="Archer.app"
INSTALL_DIR="/Applications"
MODE="install"
YES="0"
OPEN_APP="0"

usage() {
  cat <<USAGE
Usage: ./install-client.sh [--install|--build-only|--open-release] [--yes] [--open-app]

Options:
  --install       Build the macOS DMG and install Archer.app to /Applications. Default.
  --build-only    Only build the DMG; do not install.
  --open-release  Build the DMG and open the release folder.
  --yes           Replace an existing /Applications/Archer.app without asking.
  --open-app      Open /Applications/Archer.app after install.
  -h, --help      Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install) MODE="install" ;;
    --build-only) MODE="build-only" ;;
    --open-release) MODE="open-release" ;;
    --yes|-y) YES="1" ;;
    --open-app) OPEN_APP="1" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

if [[ ! -d "$DESKTOP_DIR" ]]; then
  echo "Desktop client folder not found: $DESKTOP_DIR" >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required but was not found." >&2
  exit 1
fi

cd "$DESKTOP_DIR"
CLIENT_VERSION="$(node -p "require('./package.json').version" 2>/dev/null || echo unknown)"

echo "Archer Desktop $CLIENT_VERSION"
echo "Project: $ROOT_DIR"
if command -v git >/dev/null 2>&1 && git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo
  echo "Git status before packaging:"
  GIT_STATUS="$(git -C "$ROOT_DIR" status --short)"
  if [[ -z "$GIT_STATUS" ]]; then
    echo "  clean"
  else
    printf '%s\n' "$GIT_STATUS" | sed 's/^/  /'
  fi
  echo
fi

if [[ ! -d node_modules ]]; then
  echo "Installing desktop dependencies..."
  npm install
fi

echo "Building Archer desktop client..."
npm run build:mac

DMG_PATH="$RELEASE_DIR/Archer-$CLIENT_VERSION-arm64.dmg"
if [[ ! -f "$DMG_PATH" ]]; then
  DMG_PATH="$(find "$RELEASE_DIR" -maxdepth 1 -name "*.dmg" -type f -print | sort -Vr | head -n 1)"
fi
if [[ -z "$DMG_PATH" ]]; then
  echo "No DMG produced in $RELEASE_DIR" >&2
  exit 1
fi

echo "Built: $DMG_PATH"

case "$MODE" in
  build-only)
    echo
    echo "Build complete."
    echo "Version: $CLIENT_VERSION"
    echo "DMG: $DMG_PATH"
    exit 0
    ;;
  open-release)
    open "$RELEASE_DIR"
    echo
    echo "Release folder opened."
    echo "Version: $CLIENT_VERSION"
    echo "Folder: $RELEASE_DIR"
    exit 0
    ;;
esac

MOUNT_DIR="$(mktemp -d /tmp/archer-dmg.XXXXXX)"
cleanup() {
  hdiutil detach "$MOUNT_DIR" -quiet >/dev/null 2>&1 || true
  rmdir "$MOUNT_DIR" >/dev/null 2>&1 || true
}
trap cleanup EXIT

hdiutil attach "$DMG_PATH" -mountpoint "$MOUNT_DIR" -nobrowse -quiet
APP_SRC="$(find "$MOUNT_DIR" -maxdepth 2 -name "$APP_NAME" -type d -print | head -n 1)"
if [[ -z "$APP_SRC" ]]; then
  echo "$APP_NAME not found inside DMG." >&2
  exit 1
fi

APP_DEST="$INSTALL_DIR/$APP_NAME"
if [[ -e "$APP_DEST" && "$YES" != "1" ]]; then
  printf "Replace existing %s? [y/N] " "$APP_DEST"
  read -r answer
  case "$answer" in
    y|Y|yes|YES) ;;
    *) echo "Install cancelled."; exit 0 ;;
  esac
fi

if [[ -e "$APP_DEST" ]]; then
  rm -rf "$APP_DEST"
fi

ditto "$APP_SRC" "$APP_DEST"
echo "Installed: $APP_DEST"

if [[ "$OPEN_APP" == "1" ]]; then
  open "$APP_DEST"
fi

echo
echo "Archer Desktop is ready."
echo "Version: $CLIENT_VERSION"
echo "App: $APP_DEST"
echo "Next: open Archer from Applications, or run './install-client.sh --open-app --yes' next time."
