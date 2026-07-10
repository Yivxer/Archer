#!/usr/bin/env bash
# daily_journey_smoke.sh — launchd 每日 Journey Smoke 包装脚本
#
# 作用：被 ~/Library/LaunchAgents/com.archer.journey-smoke.plist 在每天 12:00 调用。
# 与 scripts/journey_smoke.sh 的区别：
#   1. 启动 Archer.app（如未运行）并等待 API 就绪
#   2. 无论成功/失败都追加一条记录到 logs/journey-smoke.log
#   3. 适配 launchd 的最小 PATH 环境
#
# 退出码：同 journey_smoke.sh（0=全过 / 1=前置不满足 / 2=有失败 / 3=有跳过）
#
# 手动触发（模拟 launchd）：
#   bash scripts/daily_journey_smoke.sh
# 或通过 launchctl：
#   launchctl start com.archer.journey-smoke

set -uo pipefail

# ── launchd 最小 PATH 补全 ──────────────────────────────────
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT/logs"
LOG_FILE="$LOG_DIR/journey-smoke.log"
TOKEN_FILE="${HOME}/Library/Application Support/archer-desktop/security/desktop-api-token"
API_BASE="http://127.0.0.1:8765"
ARCHER_APP="/Applications/Archer.app"
MAX_API_WAIT=90  # 秒；Archer 冷启动 + API 初始化通常 < 30s，给 3 倍余量

mkdir -p "$LOG_DIR"

# 时间戳工具
ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() {
  # 总是追加，不管成功失败
  echo "[$(ts)] $*" | tee -a "$LOG_FILE"
}

log "═══════════════════════════════════════════"
log "每日 Journey Smoke 开始（launchd 触发）"

# ── 1. 检查 token 文件 ──────────────────────────────────────
if [[ ! -f "$TOKEN_FILE" ]]; then
  log "FAIL: token 文件不存在: $TOKEN_FILE — Archer Desktop 可能未正确安装"
  log "═══════════════════════════════════════════"
  exit 1
fi
TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"

# ── 2. 确保 Archer.app 运行 ─────────────────────────────────
archer_running() {
  pgrep -f "Archer.app" >/dev/null 2>&1
}

api_ready() {
  curl -sf --noproxy '*' -H "Authorization: Bearer ${TOKEN}" \
    --max-time 10 "${API_BASE}/health" >/dev/null 2>&1
}

if ! archer_running; then
  log "Archer.app 未运行，执行 open ${ARCHER_APP}"
  open "$ARCHER_APP" 2>/dev/null || {
    log "FAIL: open ${ARCHER_APP} 失败"
    log "═══════════════════════════════════════════"
    exit 1
  }
else
  log "Archer.app 已在运行"
fi

# ── 3. 等待 API 就绪 ────────────────────────────────────────
if api_ready; then
  log "API 已就绪"
else
  log "API 未就绪，等待最多 ${MAX_API_WAIT}s ..."
  waited=0
  while ! api_ready; do
    sleep 3
    waited=$((waited + 3))
    if [[ $waited -ge $MAX_API_WAIT ]]; then
      log "FAIL: API 在 ${MAX_API_WAIT}s 内未就绪 — 放弃"
      log "═══════════════════════════════════════════"
      exit 1
    fi
  done
  log "API 就绪（等待了 ${waited}s）"
fi

# ── 4. 跑 journey smoke ─────────────────────────────────────
cd "$ROOT"

# journey_smoke.sh 会自动选 .venv/bin/python，但 launchd 环境下显式设置更稳妥
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  export PYTHON="$ROOT/.venv/bin/python"
fi

SMOKE_OUTPUT="$(./scripts/journey_smoke.sh --all 2>&1)"
SMOKE_EXIT=$?

# 把 smoke 输出追加到日志（缩进标记区分）
echo "$SMOKE_OUTPUT" >> "$LOG_FILE"

# ── 5. 记录结果 ─────────────────────────────────────────────
case $SMOKE_EXIT in
  0) RESULT="PASS 8/FAIL 0/SKIP 0 — 全绿" ;;
  1) RESULT="前置条件不满足（API/token 问题）" ;;
  2) RESULT="有 journey 失败" ;;
  3) RESULT="有 journey 跳过" ;;
  *) RESULT="未知退出码 $SMOKE_EXIT" ;;
esac

log "结果: ${RESULT} (exit=${SMOKE_EXIT})"
log "═══════════════════════════════════════════"
exit $SMOKE_EXIT
