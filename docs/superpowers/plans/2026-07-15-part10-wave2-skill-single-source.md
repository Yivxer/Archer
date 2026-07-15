# Part 10 Wave 2 Skill Single Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Python the only production executor for the six duplicated skills: `obsidian_read`, `obsidian_write`, `file_ops`, `file_search`, `web_fetch`, and `web_search`.

**Architecture:** Switch execution authority before deleting compatibility code. First, `core.tool_runtime` always invokes the loaded Python skill module. Second, remove Desktop IPC and CLI runner entry points. Third, delete the six unreachable TS implementations and their implementation-specific tests while retaining shared UI-safe file and URL helpers that still have production callers.

**Tech Stack:** Python 3.14, pytest, TypeScript, Vitest, Electron/Vite.

---

### Task 1: Make Python tool runtime authoritative

**Files:**
- Modify: `core/tool_runtime.py`
- Modify: `tests/test_ts_skill_bridge.py`
- Modify: `tests/test_architecture_boundaries.py`

- [x] Add a failing behavior test that patches `core.ts_skill_bridge.try_execute_ts_skill` to return a TS result, invokes a loaded Python skill, and asserts the Python result wins.
- [x] Add a failing architecture test asserting `core/tool_runtime.py` neither imports nor calls `try_execute_ts_skill`.
- [x] Run `.venv/bin/python -m pytest -q tests/test_ts_skill_bridge.py tests/test_architecture_boundaries.py -k 'python_runtime or ts_bridge'`; expect the old TS-first behavior to fail.
- [x] Remove the `try_execute_ts_skill()` branch from `invoke()`; keep the Python skill lookup, policy wrapper, timeout, artifacts, and metadata unchanged.
- [x] Run tool-runtime, TS-bridge compatibility, architecture, API tool service, and six-skill focused tests; expect PASS.
- [x] Commit `refactor: make python skill runtime authoritative`.

### Task 2: Retire Desktop production runner entry points

**Files:**
- Modify: `client/desktop/src/main/index.ts`
- Modify: `client/desktop/electron.vite.config.ts`
- Modify: `client/desktop/src/agent/skills/index.ts`
- Delete: `client/desktop/src/main/runLocalSkill.ts`
- Delete: `client/desktop/src/agent/skills/localSkillBridge.ts`
- Modify: `client/desktop/src/agent/skills/__tests__/localSkillBridge.test.ts`

- [ ] Add a failing source-boundary test asserting Desktop main has no `archer:execute-local-skill` or `archer:list-local-skills` IPC handlers and the build has no `runLocalSkill` entry.
- [ ] Remove both IPC handlers and their bridge import from Desktop main.
- [ ] Remove the secondary Electron build entry and delete the CLI/registry bridge.
- [ ] Replace the old bridge behavior test with the source-boundary test and remove bridge exports.
- [ ] Run Desktop skill/main focused Vitest and `npm run build`; expect PASS and no `out/main/runLocalSkill.js`.
- [ ] Commit `refactor: retire desktop skill runner`.

### Task 3: Delete duplicated TS skill implementations

**Files:**
- Delete: `client/desktop/src/agent/skills/obsidianRead.ts`
- Delete: `client/desktop/src/agent/skills/obsidianWrite.ts`
- Delete: `client/desktop/src/agent/skills/fileOpsRead.ts`
- Delete: `client/desktop/src/agent/skills/fileSearch.ts`
- Delete: `client/desktop/src/agent/skills/webFetch.ts`
- Delete: `client/desktop/src/agent/skills/webSearch.ts`
- Delete: their six implementation-specific test files under `client/desktop/src/agent/skills/__tests__/`
- Modify: `client/desktop/src/agent/skills/index.ts`

- [ ] Add a failing architecture assertion that the six TS implementation files and exports are absent.
- [ ] Verify `vault.ts`, `urlSafety.ts`, and shared skill types independently before deletion; retain any helper with a production caller.
- [ ] Delete only the six duplicate implementations and tests, then remove their public exports.
- [ ] Run Python six-skill tests, Desktop Vitest, and `npm run build`; expect PASS.
- [ ] Commit `refactor: remove duplicate ts skill implementations`.

### Task 4: Wave 2 skill-source closure

**Files:**
- Modify: `Archer成长计划.md` outside the repository
- Modify: `Archer 架构设计.md` outside the repository
- Modify: `客户端构建日志.md` outside the repository

- [ ] Run the relevant Python suite, full Desktop Vitest, production build, and Journey 0 if local API is ready.
- [ ] Confirm repository search and code graph show no production TS executor for the six skill names.
- [ ] Update the three canonical documents with exact commits, counts, and verification level.
