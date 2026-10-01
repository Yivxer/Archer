#!/usr/bin/env bash
# Archer 测试入口
set -e

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "[ERROR] .venv 不存在，请先运行 pip install -r requirements.txt"
  exit 1
fi

# Defaults to the same nine smoke tests, with disposable configuration/state.
# Full offline regression: bash run_tests.sh --suite full
exec .venv/bin/python scripts/verify_offline.py "$@"
