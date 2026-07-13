# Part 10 Wave 2 Python Task Route Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Python orchestration the single source of truth for foreground/background task routing while keeping Desktop behavior unchanged during the migration.

**Architecture:** Python serializes a versioned `taskRoute` snapshot inside every full-path `orchestrationEvent`. Desktop validates and stores that snapshot for UI projection. Once the contract is available, `ChatPage` stops running the TS keyword router before sending; the remaining TS helpers are limited to presentation safeguards for plan and Hugo cards.

**Tech Stack:** Python 3.14, pytest, TypeScript, Zod, Vitest, Electron/Vite.

---

### Task 1: Add the authoritative Python task route snapshot

**Files:**
- Modify: `core/orchestrator.py`
- Modify: `tests/test_p4_orchestrator.py`
- Modify: `tests/test_desktop_contract.py`

- [x] Add a failing test asserting `orchestration_to_event_dict()` emits `taskRoute.mode`, `reason`, `title`, and `timeoutSeconds`, with approval-required and Hugo/tool side effects forced to foreground.
- [x] Run `.venv/bin/python -m pytest -q tests/test_p4_orchestrator.py -k task_route`; expect failure because `taskRoute` is missing.
- [x] Add a pure `task_route_snapshot(orchestration)` helper. Return `background` only when `needs_job` is true and `side_effect_level` is not `approval_required`; otherwise return `foreground`. Derive title from the existing sub-intent label and keep timeout at 300 seconds.
- [x] Include the snapshot in `orchestration_to_event_dict()` without changing existing fields.
- [x] Run orchestrator and Desktop contract tests; expect PASS.
- [x] Commit `feat: expose python task route snapshot`.

### Task 2: Project taskRoute through the Desktop contract

**Files:**
- Modify: `client/desktop/src/agent/contracts.ts`
- Modify: `client/desktop/src/agent/contractSchemas.ts`
- Modify: `client/desktop/src/agent/pythonBridge.ts`
- Modify: `client/desktop/src/agent/__tests__/contractSchemas.test.ts`
- Modify: `client/desktop/src/agent/__tests__/pythonBridge.test.ts`
- Modify: `client/desktop/src/agent/__tests__/runtimeStore.test.ts`

- [ ] Add failing Vitest assertions that a Python `taskRoute` survives schema validation, bridge conversion, and runtime-store reduction.
- [ ] Run `npm test -- --run src/agent/__tests__/contractSchemas.test.ts src/agent/__tests__/pythonBridge.test.ts src/agent/__tests__/runtimeStore.test.ts`; expect type/schema failure.
- [ ] Add `TaskRouteSnapshot` to the shared contract and require it on orchestration events.
- [ ] Extend the Python bridge input type and `pythonOrchestrationToAgentEvent()` mapping.
- [ ] Run the focused Vitest files; expect PASS.
- [ ] Commit `feat: project python task route in desktop`.

### Task 3: Remove Desktop pre-send routing decisions

**Files:**
- Modify: `client/desktop/src/renderer/src/pages/ChatPage.tsx`
- Modify: `client/desktop/src/agent/taskRouter.ts`
- Modify: `client/desktop/src/agent/index.ts`
- Modify: `client/desktop/src/agent/__tests__/taskRouter.test.ts`
- Test: `client/desktop/src/renderer/src/pages/ChatPage.test.tsx`

- [ ] Add a failing ChatPage test proving local messages always enter the Python chat stream instead of being diverted by TS keyword/path heuristics.
- [ ] Remove the `routeTaskForRuntime()` pre-send branch from `sendMessage()`.
- [ ] Delete `RuntimeTaskRoute`, `RuntimeTaskRouteInput`, keyword/path/approval routing helpers, and `routeTaskForRuntime()`; retain only Hugo intent and plan-card presentation helpers.
- [ ] Update exports and focused tests.
- [ ] Run task-router and ChatPage tests; expect PASS.
- [ ] Commit `refactor: remove desktop task routing decisions`.

### Task 4: Wave 2 route-source closure

**Files:**
- Modify: `tests/test_architecture_boundaries.py`
- Modify: `Archer成长计划.md` outside the repository
- Modify: `Archer 架构设计.md` outside the repository
- Modify: `客户端构建日志.md` outside the repository

- [ ] Add an architecture test forbidding `routeTaskForRuntime` and the removed background keyword tables from Desktop production code.
- [ ] Run Python route/contract tests, Desktop Vitest, and `npm run build`.
- [ ] Run Journey 0 only if local `/health` and `/ready` are available; do not spend model quota for this structural slice.
- [ ] Update the three canonical documents with exact commits and verification level.
