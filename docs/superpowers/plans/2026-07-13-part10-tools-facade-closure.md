# Part 10 Tools Facade Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce `terminal/api/_tools.py` from 2297 lines to a compatibility facade below 800 lines without changing routing, approvals, SSE order, Hugo behavior, or legacy imports.

**Architecture:** Extract dependencies from the bottom up so new modules never import `_tools.py`. Shared request/event primitives move first, Hugo workflow moves second, and Desktop tool execution moves third. `_tools.py` keeps compatibility aliases plus chat-turn orchestration and dependency factories.

**Tech Stack:** Python 3.14, pytest, FastAPI/SSE, existing Desktop tool router and policy layer.

---

### Task 1: Extract shared tool request and event primitives

**Files:**
- Create: `terminal/api/api_tool_helpers.py`
- Modify: `terminal/api/_tools.py`
- Modify: `tests/test_architecture_boundaries.py`
- Test: `tests/test_desktop_api.py`, `tests/test_tool_stage.py`

- [x] Add a failing architecture test asserting shell execution, tool-event construction, Obsidian draft preview, API request/result conversion, and skill selection helpers are defined in `api_tool_helpers.py` and only re-exported by `_tools.py`.
- [x] Run `.venv/bin/python -m pytest -q tests/test_architecture_boundaries.py -k api_tool_helpers`; expect import failure before the module exists.
- [x] Move `_is_dangerous_shell` through `_execute_api_tool_preview` into `api_tool_helpers.py`; import router aliases and `_config` dependencies directly, with no import from `_tools.py`.
- [x] Re-export the historic private names from `_tools.py` and preserve exact function identity.
- [x] Run `.venv/bin/python -m pytest -q tests/test_architecture_boundaries.py tests/test_desktop_api.py tests/test_tool_stage.py -k 'api_tool_helpers or shell or obsidian or tool_event or approval'`; expect PASS.
- [x] Commit `refactor: extract api tool helpers`.

### Task 2: Extract deterministic Hugo workflow implementation

**Files:**
- Create: `terminal/api/hugo_workflow.py`
- Modify: `terminal/api/_tools.py`
- Modify: `tests/test_architecture_boundaries.py`
- Test: `tests/test_hugo_turn.py`, `tests/test_desktop_api.py`, `tests/test_hugo_*`

- [x] Add a failing architecture test asserting Markdown source parsing, publish/delete/redeploy, confirmation result, agent fallback, and Hugo summary helpers live in `hugo_workflow.py`.
- [x] Run the new architecture test and confirm it fails because `hugo_workflow.py` does not exist.
- [x] Move `_extract_md_path_from_query` through `_run_hugo_agent_turn` into `hugo_workflow.py`; import request/event primitives from `api_tool_helpers.py` and router helpers directly.
- [x] Keep `_tools.py` compatibility aliases and build `HugoTurnDependencies` from those aliases without changing direct-action priority.
- [x] Run Hugo, approval, architecture, and Desktop API focused regressions; expect PASS.
- [x] Commit `refactor: extract hugo workflow helpers`.

### Task 3: Extract Desktop tool execution and draft helpers

**Files:**
- Create: `terminal/api/desktop_tool_execution.py`
- Modify: `terminal/api/_tools.py`
- Modify: `tests/test_architecture_boundaries.py`
- Test: `tests/test_desktop_api.py`, `tests/test_tool_stage.py`, `tests/test_obsidian_write_preview.py`

- [x] Add a failing architecture test asserting `_run_desktop_tool_loop`, per-skill event iterators, draft generators, `_iter_api_tool_events`, `_append_obsidian_draft`, and `_execute_github_operation` live in `desktop_tool_execution.py`.
- [x] Run the new architecture test and confirm it fails because the module does not exist.
- [x] Move the tool loop and execution helpers into the new module; import shared request/event primitives from `api_tool_helpers.py` and router helpers directly.
- [x] Re-export historic private names from `_tools.py`; keep chat orchestration and dependency factories in `_tools.py`.
- [x] Run focused Desktop tool, approval, Obsidian, architecture, and chat-turn regressions; expect PASS and `_tools.py <800`.
- [x] Commit `refactor: close tools compatibility facade`.

### Task 4: Wave 1 closure verification

**Files:**
- Modify: `Archer成长计划.md` outside the repository
- Modify: `Archer 架构设计.md` outside the repository
- Modify: `客户端构建日志.md` outside the repository

- [x] Verify `_tools.py <800`, `_routes.py` remains a compatibility dispatcher, and architecture boundaries pass.
- [x] Run the Python full suite: 1560 passed with exit 0. Shutdown waited for the pre-existing `tests/test_tool_runtime.py::test_runtime_timeout` worker (`sleep(60)`); timeout returns early but does not cancel the running thread, recorded as separate runtime safety debt.
- [x] Run Desktop Vitest and `cd client/desktop && npm run build`.
- [x] Run the shortest Journey only if the local API health check is ready; Journey 0 passed without a real model call.
- [x] Update the three canonical Archer documents with exact lines, tests, and verification level.
