#!/usr/bin/env bash
# 从仓库根目录运行桌面本机验收
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec bash "$ROOT/scripts/verify_desktop_live.sh"
