#!/usr/bin/env bash
# Archer 测试入口
set -e

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "[ERROR] .venv 不存在，请先运行 pip install -r requirements.txt"
  exit 1
fi

source .venv/bin/activate

echo "=== Archer Smoke Tests ==="
python tests/test_smoke.py
