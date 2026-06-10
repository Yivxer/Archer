#!/usr/bin/env bash
# 从仓库根目录一键打包、签名并安装桌面端（避免在根目录误跑 npm）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/client/desktop"
exec npm run build:mac:local
