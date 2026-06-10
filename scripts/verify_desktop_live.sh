#!/usr/bin/env bash
# 本机桌面端冒烟验收：已安装的 .app、API token、/health /status /modes
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="/Applications/Archer.app"
TOKEN_FILE="${HOME}/Library/Application Support/archer-desktop/security/desktop-api-token"
API_BASE="${ARCHER_API_BASE:-http://127.0.0.1:8765}"
OPEN_APP="${VERIFY_OPEN_APP:-0}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'
PASS=0
FAIL=0

ok()   { echo -e "${GREEN}  ✓${NC} $1"; PASS=$((PASS + 1)); }
fail() { echo -e "${RED}  ✗${NC} $1"; FAIL=$((FAIL + 1)); }
warn() { echo -e "${YELLOW}  ⚠${NC} $1"; }

echo "═══════════════════════════════════════════"
echo "  Archer 桌面本机验收"
echo "═══════════════════════════════════════════"

if [[ -d "$APP" ]]; then
  ok "已安装: $APP"
else
  fail "未找到 $APP（先运行 client/desktop 下 npm run build:mac:local）"
fi

if [[ -f "$TOKEN_FILE" ]]; then
  TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"
  if [[ -n "$TOKEN" ]]; then
    ok "桌面 API token 存在（${#TOKEN} 字符）"
  else
    fail "token 文件为空: $TOKEN_FILE"
    TOKEN=""
  fi
else
  fail "缺少 token 文件: $TOKEN_FILE"
  TOKEN=""
fi

if [[ -n "$TOKEN" ]]; then
  if curl -sf -H "Authorization: Bearer ${TOKEN}" "${API_BASE}/health" >/dev/null 2>&1; then
    ok "GET /health → 200"
  else
    warn "API 未响应；尝试启动 Archer.app（设置 VERIFY_OPEN_APP=1 可自动 open）"
    if [[ "$OPEN_APP" == "1" && -d "$APP" ]]; then
      open -a "$APP" || true
      for _ in 1 2 3 4 5 6 7 8 9 10; do
        sleep 2
        if curl -sf -H "Authorization: Bearer ${TOKEN}" "${API_BASE}/health" >/dev/null 2>&1; then
          ok "启动应用后 /health → 200"
          break
        fi
      done
    fi
    if ! curl -sf -H "Authorization: Bearer ${TOKEN}" "${API_BASE}/health" >/dev/null 2>&1; then
      fail "GET /health 失败（可手动: cd $ROOT && .venv/bin/python3 archer_api.py --token \"\$TOKEN\"）"
    fi
  fi

  if [[ "$(curl -sf -H "Authorization: Bearer ${TOKEN}" "${API_BASE}/health" >/dev/null 2>&1; echo $?)" == "0" ]]; then
    STATUS_JSON="$(curl -sf -H "Authorization: Bearer ${TOKEN}" "${API_BASE}/status")"
    MODE="$(printf '%s' "$STATUS_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('mode',''))" 2>/dev/null || echo '')"
    if [[ -n "$MODE" ]]; then
      ok "GET /status mode=${MODE}"
    else
      fail "GET /status 无法解析 mode"
    fi

    MODES_JSON="$(curl -sf -H "Authorization: Bearer ${TOKEN}" "${API_BASE}/modes")"
    CURRENT="$(printf '%s' "$MODES_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('current',''))" 2>/dev/null || echo '')"
    COUNT="$(printf '%s' "$MODES_JSON" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('modes',[])))" 2>/dev/null || echo 0)"
    if [[ -n "$CURRENT" && "$COUNT" -ge 12 ]]; then
      ok "GET /modes current=${CURRENT}，共 ${COUNT} 个姿态"
    else
      fail "GET /modes 异常（current=${CURRENT:-?} count=${COUNT}）"
    fi

    if [[ "$MODE" == "auto" && "$CURRENT" == "auto" ]]; then
      ok "姿态同步：status 与 modes 均为 auto"
    elif [[ -n "$MODE" && -n "$CURRENT" && "$MODE" == "$CURRENT" ]]; then
      ok "姿态同步：status.mode == modes.current (${MODE})"
    else
      warn "姿态字段不一致：status.mode=${MODE:-?} modes.current=${CURRENT:-?}"
    fi
  fi
fi

echo ""
echo "═══════════════════════════════════════════"
echo -e "  ${GREEN}PASS${NC}: ${PASS}   ${RED}FAIL${NC}: ${FAIL}"
echo "═══════════════════════════════════════════"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
