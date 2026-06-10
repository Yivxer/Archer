#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUBLIC_DIR="$ROOT_DIR/public"
REMOTE="archer"
REMOTE_ROOT="/var/www/archer"
STAMP="$(date +%Y%m%d-%H%M%S)"

required_files=(
  "index.html"
  "archer.html"
  "soul.html"
  "privacy.html"
  "terms.html"
  "login.html"
  "auth.html"
)

required_assets=(
  "archer-favicon.svg"
  "archer-favicon-32.png"
  "archer-favicon-180.png"
  "og.png"
  "fonts/LXGWWenKai-Regular-subset.ttf"
  "fonts/comfortaa-400.woff2"
  "fonts/comfortaa-700.woff2"
  "assets/index.css"
  "assets/soul-profile.js"
  "assets/web-companion.js"
  "assets/generated/tokens.json"
  "assets/index.js"
  "assets/archer.css"
  "assets/archer.js"
)

for file in "${required_files[@]}"; do
  if [[ ! -f "$PUBLIC_DIR/$file" ]]; then
    echo "Missing required file: public/$file" >&2
    exit 1
  fi
done

for file in "${required_assets[@]}"; do
  if [[ ! -f "$PUBLIC_DIR/$file" ]]; then
    echo "Missing required asset: public/$file" >&2
    exit 1
  fi
done

echo "Backing up production to ${REMOTE_ROOT}.backup.${STAMP}"
ssh "$REMOTE" "cp -a '$REMOTE_ROOT' '${REMOTE_ROOT}.backup.${STAMP}'"

echo "Cleaning stale production files"
ssh "$REMOTE" "
  rm -f '$REMOTE_ROOT/build.html'
  rm -f '$REMOTE_ROOT/assets/img/archer-orbit.png' '$REMOTE_ROOT/assets/img/archer-wordmark.png' '$REMOTE_ROOT/assets/img/maple-leaf.png'
  rmdir '$REMOTE_ROOT/assets/img' 2>/dev/null || true
  mkdir -p '$REMOTE_ROOT/assets'
"

echo "Uploading files"
for file in "${required_files[@]}"; do
  scp "$PUBLIC_DIR/$file" "$REMOTE:$REMOTE_ROOT/$file"
done

for file in archer-favicon.svg archer-favicon-32.png archer-favicon-180.png og.png; do
  scp "$PUBLIC_DIR/$file" "$REMOTE:$REMOTE_ROOT/$file"
done

if [[ -d "$PUBLIC_DIR/fonts" ]]; then
  scp -r "$PUBLIC_DIR/fonts" "$REMOTE:$REMOTE_ROOT/"
fi

if [[ -d "$PUBLIC_DIR/assets" ]]; then
  scp -r "$PUBLIC_DIR/assets" "$REMOTE:$REMOTE_ROOT/"
fi

echo "Validating and reloading Nginx"
ssh "$REMOTE" "nginx -t && systemctl reload nginx"

echo "Done"
