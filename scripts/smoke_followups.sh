#!/usr/bin/env bash
# Low-cost smoke for Part 5 follow-ups: plan child jobs + plugin zip + desktop build.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== Python: plugin + spawn =="
.venv/bin/pytest -q \
  tests/test_plugin.py \
  tests/test_desktop_api.py::test_background_job_spawn_creates_child_jobs

echo "== Desktop: planBridge + build =="
cd client/desktop
npm run test -- src/agent/__tests__/planBridge.test.ts
npm run build

echo "smoke_followups: ok"
