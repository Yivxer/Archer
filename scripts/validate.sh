#!/usr/bin/env bash
# validate.sh — Archer 三端验证脚本
# 用法: ./scripts/validate.sh [--terminal] [--desktop] [--web] [--all]
# 默认: --all

set -euo pipefail
cd "$(dirname "$0")/.."

# 优先使用项目 venv 中的 Python
if [ -f ".venv/bin/python3" ]; then
  PYTHON=".venv/bin/python3"
elif command -v python3 &>/dev/null; then
  PYTHON="python3"
else
  PYTHON=""
fi

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

ok()   { echo -e "${GREEN}  ✓${NC} $1"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}  ✗${NC} $1"; FAIL=$((FAIL+1)); }
warn() { echo -e "${YELLOW}  ⚠${NC} $1"; WARN=$((WARN+1)); }

# ── 参数解析 ──────────────────────────────────────────────
RUN_TERMINAL=false
RUN_DESKTOP=false
RUN_WEB=false

if [ $# -eq 0 ]; then
  RUN_TERMINAL=true; RUN_DESKTOP=true; RUN_WEB=true
else
  for arg in "$@"; do
    case "$arg" in
      --terminal) RUN_TERMINAL=true ;;
      --desktop) RUN_DESKTOP=true ;;
      --web)     RUN_WEB=true ;;
      --all)     RUN_TERMINAL=true; RUN_DESKTOP=true; RUN_WEB=true ;;
      *)         echo "未知参数: $arg"; exit 1 ;;
    esac
  done
fi

echo "═══════════════════════════════════════════"
echo "  Archer 三端验证"
echo "═══════════════════════════════════════════"
echo ""

# ══════════════════════════════════════════════════════════
# 1. 终端验证
# ══════════════════════════════════════════════════════════
if [ "$RUN_TERMINAL" = true ]; then
  echo "── 终端（Python） ──"

  # 1a. Python 可用
  if [ -n "$PYTHON" ]; then
    ok "Python 可用: $($PYTHON --version 2>&1)"
  else
    fail "Python 未找到（无系统 python3 且无 .venv）"
  fi

  # 1b. 核心模块导入
  IMPORT_OK=true
  for mod in \
    "terminal.state" \
    "terminal.ui" \
    "terminal.commands.registry" \
    "terminal.api._config" \
    "terminal.api._security" \
    "terminal.api._routes" \
    "terminal.api._tools" \
    "memory.store" \
    "memory.soul"
  do
    if $PYTHON -c "import $mod" 2>/dev/null; then
      ok "import $mod"
    else
      fail "import $mod"
      IMPORT_OK=false
    fi
  done

  # 1c. 命令注册
  if [ "$IMPORT_OK" = true ]; then
    CMD_COUNT=$($PYTHON -c "from terminal.commands.registry import registered_commands; print(len(registered_commands()))" 2>/dev/null || echo "0")
    if [ "$CMD_COUNT" -ge 25 ]; then
      ok "命令注册: ${CMD_COUNT} 个命令"
    else
      fail "命令注册: 仅 ${CMD_COUNT} 个（期望 ≥25）"
    fi
  else
    warn "跳过命令注册检查（导入失败）"
  fi

  # 1d. API 路由函数可用
  if [ "$IMPORT_OK" = true ]; then
    ROUTE_OK=$($PYTHON -c "
from terminal.api._routes import payload_get, payload_post
print('ok')
" 2>/dev/null || echo "fail")
    if [ "$ROUTE_OK" = "ok" ]; then
      ok "API 路由分发函数可用"
    else
      fail "API 路由分发函数不可用"
    fi
  fi

  # 1e. 安全模块
  SEC_OK=$($PYTHON -c "
from terminal.api._security import constant_time_compare, TokenBucketRateLimiter
print('ok')
" 2>/dev/null || echo "fail")
  if [ "$SEC_OK" = "ok" ]; then
    ok "安全模块（timing-safe + rate limiter）"
  else
    fail "安全模块不可用"
  fi

  # 1f. 私有配置边界
  if $PYTHON scripts/check_private_boundary.py --check >/dev/null 2>&1; then
    ok "私有配置与公开模板边界"
  else
    fail "私有配置边界检查失败（运行 python3 scripts/check_private_boundary.py --check）"
  fi

  echo ""
fi

# ══════════════════════════════════════════════════════════
# 2. Desktop 验证
# ══════════════════════════════════════════════════════════
if [ "$RUN_DESKTOP" = true ]; then
  echo "── 桌面客户端（Electron） ──"

  DESKTOP_DIR="client/desktop"
  if [ -d "$DESKTOP_DIR" ]; then
    ok "Desktop 项目目录存在"

    # 2a. package.json
    if [ -f "$DESKTOP_DIR/package.json" ]; then
      ok "package.json 存在"
    else
      fail "package.json 缺失"
    fi

    # 2b. node_modules
    if [ -d "$DESKTOP_DIR/node_modules" ]; then
      ok "node_modules 已安装"
    else
      warn "node_modules 未安装（需先 npm install）"
    fi

    # 2c. 关键源文件
    for f in \
      "src/renderer/src/main.tsx" \
      "src/renderer/src/types.ts" \
      "src/renderer/src/adapters/localArcher.ts" \
      "src/renderer/src/tokens.css" \
      "src/renderer/src/generated/tokens.ts"
    do
      if [ -f "$DESKTOP_DIR/$f" ]; then
        ok "源文件: $f"
      else
        fail "源文件缺失: $f"
      fi
    done

    # 2d. CSS 模块
    CSS_MODS=$(ls "$DESKTOP_DIR"/src/renderer/src/styles/*.css 2>/dev/null | wc -l | tr -d ' ')
    if [ "$CSS_MODS" -ge 7 ]; then
      ok "CSS 模块: ${CSS_MODS} 个文件"
    else
      fail "CSS 模块: 仅 ${CSS_MODS} 个（期望 ≥7）"
    fi

    if [ -n "$PYTHON" ] && $PYTHON scripts/generate_tokens.py --check >/dev/null 2>&1; then
      ok "Design tokens 生成产物同步"
    else
      fail "Design tokens 生成产物不同步（运行 python3 scripts/generate_tokens.py）"
    fi

    # 2e. 构建（仅在 node_modules 存在时）
    if [ -d "$DESKTOP_DIR/node_modules" ]; then
      echo "  执行 electron-vite build..."
      if (cd "$DESKTOP_DIR" && npx electron-vite build 2>&1 | tail -1 | grep -q "built in"); then
        ok "electron-vite build 成功"
      elif (cd "$DESKTOP_DIR" && npx electron-vite build >/dev/null 2>&1); then
        ok "electron-vite build 成功"
      else
        # 尝试获取更详细的错误
        BUILD_OUTPUT=$(cd "$DESKTOP_DIR" && npx electron-vite build 2>&1 | tail -5)
        fail "electron-vite build 失败: $BUILD_OUTPUT"
      fi
    else
      warn "跳过 build 检查（node_modules 未安装）"
    fi
  else
    fail "Desktop 项目目录不存在: $DESKTOP_DIR"
  fi

  echo ""
fi

# ══════════════════════════════════════════════════════════
# 3. Web 验证
# ══════════════════════════════════════════════════════════
if [ "$RUN_WEB" = true ]; then
  echo "── 网页端 ──"

  WEB_DIR="web/public"

  if [ -d "$WEB_DIR" ]; then
    ok "Web 项目目录存在"

    # 3a. 核心 HTML 文件
    for f in index.html archer.html soul.html; do
      if [ -f "$WEB_DIR/$f" ]; then
        ok "HTML: $f ($(wc -l < "$WEB_DIR/$f" | tr -d ' ') 行)"
      else
        fail "HTML 缺失: $f"
      fi
    done

    # 3b. 必需的 CSS/JS 资产
    for f in \
      "assets/index.css" \
      "assets/index.js" \
      "assets/generated/tokens.json" \
      "assets/archer.css" \
      "assets/archer.js"
    do
      if [ -f "$WEB_DIR/$f" ]; then
        SIZE=$(wc -c < "$WEB_DIR/$f" | tr -d ' ')
        ok "资产: $f (${SIZE}B)"
      else
        fail "资产缺失: $f"
      fi
    done

    # 3c. 字体文件
    for f in \
      "fonts/comfortaa-400.woff2" \
      "fonts/comfortaa-700.woff2" \
      "fonts/LXGWWenKai-Regular-subset.ttf"
    do
      if [ -f "$WEB_DIR/$f" ]; then
        ok "字体: $f"
      else
        fail "字体缺失: $f"
      fi
    done

    # 3d. index.html 体积检查（应 ≤ 600 行，之前 5194 行）
    HTML_LINES=$(wc -l < "$WEB_DIR/index.html" | tr -d ' ')
    if [ "$HTML_LINES" -le 600 ]; then
      ok "index.html 体积: ${HTML_LINES} 行（≤ 600）"
    else
      warn "index.html 体积: ${HTML_LINES} 行（期望 ≤ 600）"
    fi

    # 3e. 外联资产引用检查
    if grep -q 'assets/index.css' "$WEB_DIR/index.html" && \
       grep -q 'assets/index.js' "$WEB_DIR/index.html"; then
      ok "index.html 正确引用外联 CSS/JS"
    else
      fail "index.html 未正确引用外联 CSS/JS"
    fi

    # 3f. 文案风格指南
    if [ -f "$WEB_DIR/assets/ARCHER-COPY-GUIDE.md" ]; then
      ok "文案风格指南存在"
    else
      warn "文案风格指南缺失（非阻塞）"
    fi

    # 3g. deploy.sh 检查
    if [ -f "web/deploy.sh" ]; then
      ok "deploy.sh 存在"
    else
      warn "deploy.sh 缺失"
    fi
  else
    fail "Web 项目目录不存在: $WEB_DIR"
  fi

  echo ""
fi

# ══════════════════════════════════════════════════════════
# 汇总
# ══════════════════════════════════════════════════════════
echo "═══════════════════════════════════════════"
echo -e "  ${GREEN}PASS${NC}: ${PASS}   ${RED}FAIL${NC}: ${FAIL}   ${YELLOW}WARN${NC}: ${WARN}"
echo "═══════════════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
  echo -e "\n${RED}验证未通过${NC} — ${FAIL} 项失败"
  exit 1
else
  echo -e "\n${GREEN}全部通过${NC} ✓"
  exit 0
fi
