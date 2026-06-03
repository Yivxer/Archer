# Archer 2.0 Runtime Scope Report

Updated: 2026-06-03 19:18 CST

## Purpose

Isolate the Archer 2.0 runtime changes from the existing dirty repository state before continuing product work.

## Included Scope

Stage and review only these areas for the Archer 2.0 runtime batch:

- `client/desktop/` source, config, lockfile, and checked-in image/icon resources
- `archer_api.py` compatibility entrypoint
- `terminal/archer_api.py`
- `terminal/api/`
- `tests/test_desktop_api.py`

The broader `client/desktop/` scope is intentional because the desktop app did not exist in `HEAD`; staging only runtime files would create an incomplete, non-buildable commit.

## Excluded Scope

Do not stage or clean up unrelated dirty files in this batch.

Current unrelated or uncertain areas include tracked changes/deletions in root docs, `core/`, `memory/`, `skills/`, templates, and older Python tests, plus many untracked folders such as `web/`, `workflows/`, `modes/`, `terminal/commands/`, and broad new skill/test files.

Ignored/generated files remain excluded: `node_modules/`, `client/desktop/release/`, `client/desktop/out/`, `.DS_Store`, `__pycache__/`, and `.pyc`.

## Current Part 3 State

Completed:

- B1 TS runtime skeleton
- B2 Python bridge and approval shadow integration
- B3 background job API and execution loop
- B4 Desktop job adapter and ChatPage minimum UX
- B5 verification
- B6 job persistence, cancel, and retry
- B7 job timeout and UI controls
- B8 automatic task routing
- B9 persistent runtime event log
- B10 independent Tasks page

Remaining:

- Productize real subagent runtime
- Migrate or adapt Python skills behind typed runtime contracts
- Strengthen real Hugo blog publish flow with single-page accessibility verification
- Make runtime approval queue the primary approval state source
- Run real Electron manual acceptance
- Clean and commit git state in small, reviewable batches

## Last Verification

Before this scope report, the Archer 2.0 batch had passed:

- `cd client/desktop && npm run test`
- `cd client/desktop && npm run build`
- `.venv/bin/python -m pytest -q tests/test_desktop_api.py`

No code changes were made during the read-only git triage before creating this report.
