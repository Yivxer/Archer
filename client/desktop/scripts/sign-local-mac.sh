#!/usr/bin/env bash
set -euo pipefail

# 本地 macOS 签名脚本。
#
# 优先使用可用的代码签名身份（Developer ID / 自签证书）并启用加固运行时；
# 若钥匙串里没有有效身份（例如自签证书私钥丢失、被重新生成导致 Team ID 不一致），
# 自动回退到 ad-hoc 签名，并且**不**启用加固运行时——否则 Library Validation 会因为
# 框架与主程序 Team ID 不一致而在启动时崩溃（dyld: different Team IDs）。

APP_PATH="${1:-release/mac-arm64/Archer.app}"
IDENTITY="${ARCHER_CODESIGN_IDENTITY:-0CABAF8B74E5FFBFABBD963EE16E05ABF6ABD8DC}"

if [[ ! -d "$APP_PATH" ]]; then
  echo "App not found: $APP_PATH" >&2
  exit 1
fi

# 判断指定身份是否是当前钥匙串里有效的代码签名身份。
identity_is_valid() {
  local id="$1"
  [[ -n "$id" ]] || return 1
  security find-identity -v -p codesigning 2>/dev/null | grep -qF "$id"
}

if identity_is_valid "$IDENTITY"; then
  echo "==> 使用签名身份: ${IDENTITY}（启用加固运行时）"
  codesign --force --deep --sign "$IDENTITY" --options runtime "$APP_PATH"
else
  echo "==> 未找到有效签名身份（${IDENTITY}），回退到 ad-hoc 签名（不启用加固运行时）" >&2
  echo "    如需正式签名，请设置 ARCHER_CODESIGN_IDENTITY 为有效的钥匙串身份。" >&2
  codesign --force --deep --sign - "$APP_PATH"
fi

echo "==> 验证签名"
codesign --verify --deep --strict --verbose=2 "$APP_PATH"
codesign -dv --verbose=2 "$APP_PATH" 2>&1 | grep -E "Authority=|Signature=|Identifier=" || true
