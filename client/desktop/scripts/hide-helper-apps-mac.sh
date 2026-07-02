#!/usr/bin/env bash
set -euo pipefail

APP_PATH="${1:-/Applications/Archer.app}"
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"

if [[ ! -d "$APP_PATH" ]]; then
  echo "App not found: $APP_PATH" >&2
  exit 1
fi

if [[ ! -x "$LSREGISTER" ]]; then
  echo "lsregister not found: $LSREGISTER" >&2
  exit 1
fi

shopt -s nullglob
helpers=("$APP_PATH"/Contents/Frameworks/Archer\ Helper*.app)

for helper in "${helpers[@]}"; do
  "$LSREGISTER" -u "$helper" >/dev/null 2>&1 || true
done

"$LSREGISTER" -gc >/dev/null 2>&1 || true

if command -v killall >/dev/null 2>&1; then
  killall Dock >/dev/null 2>&1 || true
fi

echo "Hidden ${#helpers[@]} Archer helper app registration(s)."
