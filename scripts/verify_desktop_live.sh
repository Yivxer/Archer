#!/usr/bin/env bash
# 本机桌面端冒烟验收：已安装的 .app、API token、/health /ready /status /modes /config/doctor
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="${ARCHER_APP_PATH:-/Applications/Archer.app}"
TOKEN_FILE="${ARCHER_TOKEN_FILE:-${HOME}/Library/Application Support/archer-desktop/security/desktop-api-token}"
API_BASE="${ARCHER_API_BASE:-http://127.0.0.1:8765}"
OPEN_APP="${VERIFY_OPEN_APP:-0}"
ASAR_BIN="${ARCHER_ASAR_BIN:-${ROOT}/client/desktop/node_modules/.bin/asar}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'
PASS=0
FAIL=0
START_MS="$(python3 -c 'import time; print(int(time.time() * 1000))')"
READY_MS=""
DOCTOR_MS=""

ok()   { echo -e "${GREEN}  ✓${NC} $1"; PASS=$((PASS + 1)); }
fail() { echo -e "${RED}  ✗${NC} $1"; FAIL=$((FAIL + 1)); }
warn() { echo -e "${YELLOW}  ⚠${NC} $1"; }
now_ms() { python3 -c 'import time; print(int(time.time() * 1000))'; }
json_get() {
  local expr="$1"
  python3 -c "import sys,json; d=json.load(sys.stdin); print(${expr})" 2>/dev/null || echo ''
}

echo "═══════════════════════════════════════════"
echo "  Archer 桌面本机验收"
echo "═══════════════════════════════════════════"

if [[ -d "$APP" ]]; then
  ok "已安装: $APP"
else
  fail "未找到 $APP（先运行 client/desktop 下 npm run build:mac:local）"
fi

APP_ASAR="${APP}/Contents/Resources/app.asar"
if [[ -f "$APP_ASAR" && -x "$ASAR_BIN" ]]; then
  TMP_DIR="$(mktemp -d)"
  RENDERER_REQUIRE_HITS=""
  while IFS= read -r asset; do
    asset="${asset#/}"
    (
      cd "$TMP_DIR"
      "$ASAR_BIN" extract-file "$APP_ASAR" "$asset" >/dev/null
    )
    extracted="$TMP_DIR/$(basename "$asset")"
    if [[ -f "$extracted" ]] && rg -n "require\\(" "$extracted" >/dev/null 2>&1; then
      RENDERER_REQUIRE_HITS="${RENDERER_REQUIRE_HITS}${asset}"$'\n'
    fi
  done < <("$ASAR_BIN" list "$APP_ASAR" | rg '^/out/renderer/assets/.*\.js$' || true)
  rm -rf "$TMP_DIR"
  if [[ -n "$RENDERER_REQUIRE_HITS" ]]; then
    fail "renderer bundle 含 CommonJS require，生产环境可能白屏: $(printf '%s' "$RENDERER_REQUIRE_HITS" | head -n 1)"
  else
    ok "renderer bundle sanity：未发现 require("
  fi
elif [[ -d "$ROOT/client/desktop/out/renderer" ]]; then
  if rg -n "require\\(" "$ROOT/client/desktop/out/renderer" >/dev/null 2>&1; then
    fail "本地 renderer 产物含 CommonJS require，生产环境可能白屏"
  else
    ok "renderer bundle sanity：未发现 require("
  fi
else
  warn "跳过 renderer bundle sanity（缺少 app.asar/asar 工具/本地产物）"
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
  # 本机回环请求不走代理（curl 默认会读 http_proxy 环境变量）
  CURL_OPTS=(-sf --noproxy '*' -H "Authorization: Bearer ${TOKEN}")
  if curl "${CURL_OPTS[@]}" "${API_BASE}/health" >/dev/null 2>&1; then
    ok "GET /health → 200"
  else
    warn "API 未响应；尝试启动 Archer.app（设置 VERIFY_OPEN_APP=1 可自动 open）"
    if [[ "$OPEN_APP" == "1" && -d "$APP" ]]; then
      open -a "$APP" || true
      for _ in 1 2 3 4 5 6 7 8 9 10; do
        sleep 2
        if curl "${CURL_OPTS[@]}" "${API_BASE}/health" >/dev/null 2>&1; then
          ok "启动应用后 /health → 200"
          break
        fi
      done
    fi
    if ! curl "${CURL_OPTS[@]}" "${API_BASE}/health" >/dev/null 2>&1; then
      fail "GET /health 失败（可手动: cd $ROOT && .venv/bin/python3 archer_api.py --token \"\$TOKEN\"）"
    fi
  fi

  if [[ "$(curl "${CURL_OPTS[@]}" "${API_BASE}/health" >/dev/null 2>&1; echo $?)" == "0" ]]; then
    READY_START_MS="$(now_ms)"
    READY_JSON="$(curl "${CURL_OPTS[@]}" "${API_BASE}/ready")"
    READY_MS="$(( $(now_ms) - READY_START_MS ))"
    READY="$(printf '%s' "$READY_JSON" | json_get "d.get('ready', d.get('ok', False))")"
    if [[ "$READY" == "True" || "$READY" == "true" ]]; then
      ok "GET /ready → ready"
      if [[ "$READY_MS" -gt 15000 ]]; then
        fail "API ready 超过 15000ms（${READY_MS}ms）"
      elif [[ "$READY_MS" -gt 5000 ]]; then
        warn "API ready 超过 5000ms（${READY_MS}ms）"
      fi
    else
      fail "GET /ready 未返回 ready=true"
    fi

    STATUS_JSON="$(curl "${CURL_OPTS[@]}" "${API_BASE}/status")"
    MODE="$(printf '%s' "$STATUS_JSON" | json_get "d.get('mode','')")"
    if [[ -n "$MODE" ]]; then
      ok "GET /status mode=${MODE}"
    else
      fail "GET /status 无法解析 mode"
    fi

    MODES_JSON="$(curl "${CURL_OPTS[@]}" "${API_BASE}/modes")"
    CURRENT="$(printf '%s' "$MODES_JSON" | json_get "d.get('current','')")"
    COUNT="$(printf '%s' "$MODES_JSON" | json_get "len(d.get('modes',[]))")"
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

    DOCTOR_START_MS="$(now_ms)"
    DOCTOR_JSON="$(curl "${CURL_OPTS[@]}" "${API_BASE}/config/doctor")"
    DOCTOR_MS="$(( $(now_ms) - DOCTOR_START_MS ))"
    DOCTOR_ERRORS="$(printf '%s' "$DOCTOR_JSON" | json_get "d.get('summary', {}).get('error', '')")"
    DOCTOR_HAS_ISSUES="$(printf '%s' "$DOCTOR_JSON" | json_get "isinstance(d.get('issues', None), list)")"
    if [[ -n "$DOCTOR_ERRORS" && "$DOCTOR_HAS_ISSUES" == "True" ]]; then
      if [[ "$DOCTOR_ERRORS" == "0" ]]; then
        ok "GET /config/doctor → 0 error"
      else
        warn "GET /config/doctor → ${DOCTOR_ERRORS} error(s)，请在设置页修复"
      fi
    else
      fail "GET /config/doctor 无法解析结构化自检结果"
    fi
  fi
fi

echo ""
TOTAL_MS="$(( $(now_ms) - START_MS ))"
echo "PROFILE: ready_ms=${READY_MS:-n/a} doctor_ms=${DOCTOR_MS:-n/a} total_ms=${TOTAL_MS}"
echo "═══════════════════════════════════════════"
echo -e "  ${GREEN}PASS${NC}: ${PASS}   ${RED}FAIL${NC}: ${FAIL}"
echo "═══════════════════════════════════════════"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
