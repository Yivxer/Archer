#!/usr/bin/env bash
# L5.2 — Journey smoke runner
#
# 用法:
#   ./scripts/journey_smoke.sh --case 0       # 跑单条 journey
#   ./scripts/journey_smoke.sh --case 5
#   ./scripts/journey_smoke.sh --all          # 跑全部 8 条 (0-7)
#   ./scripts/journey_smoke.sh --list         # 列出所有 case
#
# 退出码:
#   0  全部通过
#   1  前置条件不满足 (API 未就绪 / token 缺失)
#   2  有 journey 失败
#   3  清理失败 (警告但不阻塞 -- 仍返回 0 如果 journey 本身通过)
#
# 失败时输出: 哪一步失败、trace_id、最近事件、replay_trace.py 命令
# 契约: Archer 稳定性框架 §八 (L5.1 journey 步骤)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_BASE="${ARCHER_API_BASE:-http://127.0.0.1:8765}"
TOKEN_FILE="${ARCHER_TOKEN_FILE:-${HOME}/Library/Application Support/archer-desktop/security/desktop-api-token}"
TS="$(date +%s)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PASS=0
FAIL=0
SKIP=0

ok()     { echo -e "${GREEN}  ✓${NC} $1"; PASS=$((PASS + 1)); }
fail()   { echo -e "${RED}  ✗${NC} $1"; FAIL=$((FAIL + 1)); }
warn()   { echo -e "${YELLOW}  ⚠${NC} $1"; }
skip()   { echo -e "${CYAN}  ⊘${NC} $1 (skipped)"; SKIP=$((SKIP + 1)); }
info()   { echo -e "${CYAN}  ℹ${NC} $1"; }

# ── 前置条件检查 ────────────────────────────────────────────
check_prereqs() {
  echo ""
  echo "═══════════════════════════════════════════"
  echo "  Archer Journey Smoke — 前置检查"
  echo "═══════════════════════════════════════════"

  if [[ ! -f "$TOKEN_FILE" ]]; then
    fail "token 文件不存在: $TOKEN_FILE"
    return 1
  fi
  TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"
  if [[ -z "$TOKEN" ]]; then
    fail "token 为空"
    return 1
  fi
  ok "API token 存在"

  CURL_OPTS=(-sf --noproxy '*' -H "Authorization: Bearer ${TOKEN}" --max-time 10)

  if ! curl "${CURL_OPTS[@]}" "${API_BASE}/health" >/dev/null 2>&1; then
    fail "GET /health 失败 — API 未就绪"
    return 1
  fi
  ok "GET /health → 200"

  READY_JSON="$(curl "${CURL_OPTS[@]}" "${API_BASE}/ready" 2>/dev/null || echo '{}')"
  READY="$(printf '%s' "$READY_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('ready', d.get('ok', False)))" 2>/dev/null || echo 'False')"
  if [[ "$READY" == "True" || "$READY" == "true" ]]; then
    ok "GET /ready → ready"
  else
    fail "GET /ready 未就绪"
    return 1
  fi

  # 导出 TOKEN/CURL_OPTS 供 case 函数使用
  export ARCHER_TOKEN="$TOKEN"
  export ARCHER_CURL_TOKEN="$TOKEN"
  export ARCHER_API_BASE="$API_BASE"
  return 0
}

# ── 辅助函数 ────────────────────────────────────────────────
# curl_api <method> <path> [json_body]
curl_api() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  local opts=(-s --noproxy '*' -H "Authorization: Bearer ${ARCHER_TOKEN}" -X "$method" --max-time 30)
  if [[ -n "$body" ]]; then
    opts+=(-H "Content-Type: application/json" -d "$body")
  fi
  curl "${opts[@]}" "${API_BASE}${path}"
}

# curl_stream <path> [json_body] — 流式 SSE，输出到 stdout
curl_stream() {
  local path="$1"
  local body="${2:-}"
  local opts=(-s --noproxy '*' -H "Authorization: Bearer ${ARCHER_TOKEN}" --max-time 120)
  if [[ -n "$body" ]]; then
    opts+=(-H "Content-Type: application/json" -d "$body")
  fi
  curl "${opts[@]}" "${API_BASE}${path}"
}

# extract_trace_id <sse_output> — 从 SSE 输出提取第一个 traceId
extract_trace_id() {
  python3 -c "
import sys, json, re
text = sys.stdin.read()
# SSE 事件格式: data: {...}\n\n
# traceId 可能嵌套在 statusEvent / runtimeContextEvent / 顶层
for match in re.finditer(r'data: (.+?)(?:\n\n|\n\$|\$)', text):
    try:
        event = json.loads(match.group(1))
        # 顶层 traceId
        if event.get('traceId'):
            print(event['traceId'])
            sys.exit(0)
        # 嵌套在 *Event 子对象里
        for k, v in event.items():
            if isinstance(v, dict) and v.get('traceId'):
                print(v['traceId'])
                sys.exit(0)
    except: pass
print('')
" 2>/dev/null
}

# replay_hint <trace_id> — 输出 replay 命令建议
replay_hint() {
  local trace_id="$1"
  if [[ -n "$trace_id" ]]; then
    echo ""
    echo -e "${YELLOW}  🔍 trace_id=${trace_id}${NC}"
    echo -e "${YELLOW}  回放命令: python3 ${ROOT}/scripts/replay_trace.py ${trace_id} --file <eventLog.json>${NC}"
  fi
}

# ── Journey 0: 终端 REPL smoke ─────────────────────────────
journey_0() {
  echo ""
  echo "── Journey 0: 终端 REPL smoke ──────────────────"
  # archer.py 当前是交互式 REPL，不支持 --non-interactive/--prompt
  # 需 expect 脚本或给 archer.py 加非交互模式才能验证，暂跳过
  skip "终端 REPL 需 expect 脚本或非交互模式支持（archer.py 当前仅交互式）"
  return 3
}

# ── Journey 1: 新对话 → 回复 → 恢复 ────────────────────────
journey_1() {
  echo ""
  echo "── Journey 1: 新对话 → 回复 → 恢复 ──────────────"
  local sid="journey1-${TS}"
  local sse
  sse="$(curl_stream /chat/stream "{\"messages\":[{\"role\":\"user\",\"content\":\"测试对话1\"}],\"session_id\":\"${sid}\"}" 2>&1)" || true

  if echo "$sse" | grep -qE '"type":[[:space:]]*"(token|done)"'; then
    ok "SSE 流含文本回复"
  else
    fail "SSE 流无文本回复"
    replay_hint "$(echo "$sse" | extract_trace_id)"
    return 2
  fi

  local saved saved_id
  saved="$(curl_api POST /sessions "{\"messages\":[{\"role\":\"user\",\"text\":\"测试对话1\"},{\"role\":\"assistant\",\"text\":\"回复\"}]}" 2>&1)" || true
  # 从返回 JSON 提取 id（服务端生成，格式如 20260704_120145）
  saved_id="$(echo "$saved" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null || echo '')"
  if [[ -n "$saved_id" ]]; then
    ok "session 保存成功 (id=${saved_id})"
  else
    fail "session 保存失败: ${saved}"
    return 2
  fi

  local detail
  detail="$(curl_api GET "/sessions/${saved_id}" 2>&1)" || true
  if echo "$detail" | grep -q "messages"; then
    ok "session 恢复成功"
  else
    fail "session 恢复失败: ${detail}"
    return 2
  fi
  return 0
}

# ── Journey 2: .md 附件 → 上下文 → 模型引用 ────────────────
journey_2() {
  echo ""
  echo "── Journey 2: .md 附件 → 上下文 → 引用 ──────────"
  local marker="JOURNEY2_MARKER_${TS}"
  local tmpfile="/tmp/journey2-test-${TS}.md"
  echo "# 测试附件\n\n唯一标记：${marker}" > "$tmpfile"

  local sse
  sse="$(curl_stream /chat/stream "{\"messages\":[{\"role\":\"user\",\"content\":\"请引用附件中的标记\"}],\"session_id\":\"journey2-${TS}\",\"fileRefs\":[{\"path\":\"${tmpfile}\"}]}" 2>&1)" || true

  if echo "$sse" | grep -q "file.reference"; then
    ok "附件被引用 (file.reference 事件)"
  else
    fail "无 file.reference 事件"
    replay_hint "$(echo "$sse" | extract_trace_id)"
    rm -f "$tmpfile"
    return 2
  fi

  if echo "$sse" | grep -q "$marker"; then
    ok "模型引用了附件标记"
  else
    warn "模型未引用附件标记（可能模型行为，非 bug）"
  fi

  rm -f "$tmpfile"
  ok "清理临时文件"
  return 0
}

# ── Journey 3: Obsidian focus 感知 ─────────────────────────
journey_3() {
  echo ""
  echo "── Journey 3: Obsidian focus 感知 ───────────────"
  local doctor
  doctor="$(curl_api GET /config/doctor 2>&1)" || true
  if echo "$doctor" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('summary',{}).get('error',1)==0 else 1)" 2>/dev/null; then
    ok "doctor 无 error"
  else
    skip "doctor 有 error 或 vault 未配置"
    return 3
  fi

  local focus
  focus="$(curl_api GET /obsidian/focus 2>&1)" || true
  if echo "$focus" | grep -q "path\|note"; then
    ok "focus 感知正常"
  else
    fail "focus 感知失败"
    return 2
  fi

  local sse
  sse="$(curl_stream /chat/stream "{\"messages\":[{\"role\":\"user\",\"content\":\"我刚才在看什么笔记？\"}],\"session_id\":\"journey3-${TS}\"}" 2>&1)" || true
  if echo "$sse" | grep -q "runtime.context"; then
    ok "runtime.context 事件存在"
  else
    warn "无 runtime.context 事件（可能无 focus）"
  fi
  return 0
}

# ── Journey 4: Obsidian 写入 ───────────────────────────────
journey_4() {
  echo ""
  echo "── Journey 4: Obsidian 写入全链路 ───────────────"
  local doctor
  doctor="$(curl_api GET /config/doctor 2>&1)" || true
  if ! echo "$doctor" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('summary',{}).get('error',1)==0 else 1)" 2>/dev/null; then
    skip "doctor 有 error 或 vault 未配置"
    return 3
  fi

  local sse
  sse="$(curl_stream /chat/stream "{\"messages\":[{\"role\":\"user\",\"content\":\"在 journey4-test-${TS}.md 写入：测试内容 ${TS}\"}],\"session_id\":\"journey4-${TS}\"}" 2>&1)" || true

  if echo "$sse" | grep -q "obsidian_write"; then
    ok "obsidian_write 工具被触发"
  else
    fail "obsidian_write 未被触发"
    replay_hint "$(echo "$sse" | extract_trace_id)"
    return 2
  fi

  # obsidian_write 属于 write-vault 权限，需要用户在 UI 点 approval 确认
  # 脚本无法自动完成 approval，所以检查 tool_event 产生即算通过
  # （tool.result 需人工 approval 后才有，不作为硬性检查）
  if echo "$sse" | grep -q "tool_event"; then
    ok "tool_event 事件存在（approval 需用户在 UI 确认）"
  else
    fail "无 tool_event"
    replay_hint "$(echo "$sse" | extract_trace_id)"
    return 2
  fi
  return 0
}

# ── Journey 5: 博客发布 ────────────────────────────────────
journey_5() {
  echo ""
  echo "── Journey 5: 博客发布 ──────────────────────────"
  local doctor
  doctor="$(curl_api GET /config/doctor 2>&1)" || true
  if ! echo "$doctor" | python3 -c "import sys,json; d=json.load(sys.stdin); issues=d.get('issues',[]); sys.exit(0 if not any('hugo' in str(i).lower() for i in issues) else 1)" 2>/dev/null; then
    skip "hugo_blog 配置有问题"
    return 3
  fi

  local sse
  sse="$(curl_stream /chat/stream "{\"messages\":[{\"role\":\"user\",\"content\":\"发布一篇测试博客 journey5-test-${TS}\"}],\"session_id\":\"journey5-${TS}\"}" 2>&1)" || true

  if echo "$sse" | grep -q "hugo_blog"; then
    ok "hugo_blog 工具被触发"
  else
    fail "hugo_blog 未被触发"
    replay_hint "$(echo "$sse" | extract_trace_id)"
    return 2
  fi
  ok "Journey 5 基础检查通过（完整发布需手动 approval + HTTP 200 验证）"
  return 0
}

# ── Journey 6: 工具确认 → Trace ────────────────────────────
journey_6() {
  echo ""
  echo "── Journey 6: 工具确认 → Trace 可查 ─────────────"
  # 用纯闲聊 prompt 避免触发工具 approval 卡 semaphore
  # 验证 trace_id 全程贯通 + 流正常结束（工具 approval 需用户在 UI 确认，不在此 journey 验证）
  local sse
  sse="$(curl_stream /chat/stream "{\"messages\":[{\"role\":\"user\",\"content\":\"journey6 简短回复一下\"}],\"session_id\":\"journey6-${TS}\"}" 2>&1)" || true

  local trace_id
  trace_id="$(echo "$sse" | extract_trace_id)"
  if [[ -n "$trace_id" ]]; then
    ok "trace_id 存在: ${trace_id}"
  else
    fail "无 trace_id"
    return 2
  fi

  if echo "$sse" | grep -q "tool_event"; then
    ok "tool 事件存在"
  else
    warn "无 tool 事件（闲聊不触发工具，符合预期）"
  fi

  if echo "$sse" | grep -qE '"type":[[:space:]]*"(token|done)"'; then
    ok "流正常结束"
  else
    fail "流未正常结束"
    replay_hint "$trace_id"
    return 2
  fi
  return 0
}

# ── Journey 7: 连续话题 ────────────────────────────────────
journey_7() {
  echo ""
  echo "── Journey 7: 连续话题 smoke ────────────────────"
  local sid="journey7-${TS}"

  for i in 1 2 3; do
    local sse
    sse="$(curl_stream /chat/stream "{\"messages\":[{\"role\":\"user\",\"content\":\"继续话题 (第${i}轮)\"}],\"session_id\":\"${sid}\"}" 2>&1)" || true
    if echo "$sse" | grep -qE '"type":[[:space:]]*"(token|done)"'; then
      ok "第 ${i} 轮有回复"
    else
      fail "第 ${i} 轮无回复"
      replay_hint "$(echo "$sse" | extract_trace_id)"
      return 2
    fi
  done

  # chat/stream 不自动保存 session，session 保存能力已在 journey 1 验证
  # 这里只验证连续对话流畅性 + threads 列表可读
  local threads
  threads="$(curl_api GET /threads 2>&1)" || true
  local thread_count
  thread_count="$(echo "$threads" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('threads',[])))" 2>/dev/null || echo '?')"
  info "当前 threads 数量: ${thread_count}"
  ok "Journey 7 基础检查通过（连续 3 轮对话流畅）"
  return 0
}

# ── 主入口 ─────────────────────────────────────────────────
ALL_CASES=(0 1 2 3 4 5 6 7)

case_name() {
  case "$1" in
    0) echo "终端 REPL smoke" ;;
    1) echo "新对话→回复→恢复" ;;
    2) echo ".md 附件→上下文→引用" ;;
    3) echo "Obsidian focus 感知" ;;
    4) echo "Obsidian 写入全链路" ;;
    5) echo "博客发布" ;;
    6) echo "工具确认→Trace 可查" ;;
    7) echo "连续话题 smoke" ;;
    *) echo "未知" ;;
  esac
}

run_case() {
  local case_num="$1"
  local func="journey_${case_num}"
  echo ""
  echo "╔═══════════════════════════════════════════"
  echo "║ Journey ${case_num}: $(case_name "$case_num")"
  echo "╚═══════════════════════════════════════════"
  if declare -F "$func" >/dev/null 2>&1; then
    "$func"
    return $?
  else
    fail "Journey ${case_num} 未实现"
    return 2
  fi
}

# 解析参数
ACTION=""
CASE_NUM=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)  ACTION="all"; shift ;;
    --list) ACTION="list"; shift ;;
    --case) ACTION="case"; CASE_NUM="$2"; shift 2 ;;
    *)      echo "未知参数: $1"; exit 1 ;;
  esac
done

if [[ "$ACTION" == "list" ]]; then
  echo "可用 journey cases:"
  for c in "${ALL_CASES[@]}"; do
    echo "  --case ${c}  $(case_name "$c")"
  done
  echo "  --all        跑全部 8 条"
  exit 0
fi

if [[ "$ACTION" == "case" && -z "$CASE_NUM" ]]; then
  echo "错误: --case 需要指定编号 (0-7)"
  exit 1
fi

# 前置检查
if ! check_prereqs; then
  echo ""
  echo -e "${RED}前置条件不满足，无法运行 journey smoke${NC}"
  exit 1
fi

# 执行
CASES_TO_RUN=()
if [[ "$ACTION" == "all" ]]; then
  CASES_TO_RUN=("${ALL_CASES[@]}")
elif [[ "$ACTION" == "case" ]]; then
  CASES_TO_RUN=("$CASE_NUM")
else
  echo "用法: $0 --all | --case <0-7> | --list"
  exit 1
fi

CASE_PASS=0
CASE_FAIL=0
CASE_SKIP=0
FAILED_CASES=()

for case_num in "${CASES_TO_RUN[@]}"; do
  if run_case "$case_num"; then
    CASE_PASS=$((CASE_PASS + 1))
  else
    local_rc=$?
    if [[ $local_rc -eq 3 ]]; then
      CASE_SKIP=$((CASE_SKIP + 1))
    else
      CASE_FAIL=$((CASE_FAIL + 1))
      FAILED_CASES+=("$case_num")
    fi
  fi
done

# 汇总
echo ""
echo "═══════════════════════════════════════════"
echo "  Journey Smoke 汇总"
echo "═══════════════════════════════════════════"
echo -e "  ${GREEN}PASS${NC}: ${CASE_PASS}   ${RED}FAIL${NC}: ${CASE_FAIL}   ${CYAN}SKIP${NC}: ${CASE_SKIP}"
if [[ ${#FAILED_CASES[@]} -gt 0 ]]; then
  echo -e "  ${RED}失败 cases:${NC} ${FAILED_CASES[*]}"
fi
echo "═══════════════════════════════════════════"

if [[ $CASE_FAIL -gt 0 ]]; then
  exit 2
fi
exit 0
