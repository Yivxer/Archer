# Part 10 Wave 1 God File Next Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Continue Wave 1 by turning the remaining chat turn and API route god files into tested, compatibility-preserving facades before any Wave 2 routing work.

**Architecture:** Keep `terminal/api/_tools.py` and `_routes.py` as compatibility/dispatch facades. Extract one behavior-complete stage at a time, preserve SSE event order and existing public helper names, and make each stage independently testable with fake LLMs, fake clocks, and temporary databases.

**Tech Stack:** Python 3.14, FastAPI/SSE, SQLite, pytest, Electron/Vitest.

## Global Constraints

- Do not enter Wave 2, Durable Outbox, Part 8 live, or TS routing work in this plan.
- Preserve current SSE payloads, `contractVersion`, tool approval behavior, and legacy `terminal/archer_api.py` compatibility.
- Every implementation task is TDD: focused failing test, minimal change, focused regression, then one commit.
- Do not modify or stage the untracked `用户中心系统技术设计文档.docx`.
- Record only evidence-backed status in `Archer成长计划.md`, `Archer 架构设计.md`, and `客户端构建日志.md`.

---

### Task 1: Extract full-turn context preparation

**Status:** completed — commit `ea3c6ba`.

**Files:**
- Create: `terminal/api/chat_turn_context.py`
- Modify: `terminal/api/_tools.py`
- Test: `tests/test_chat_turn_context.py`

**Produces:** `prepare_full_turn(messages, memory_mode, obsidian_mode, file_refs, runtime_context)`, returning a dataclass containing query, trace ID, orchestration, context limits, selected tools, enriched messages, and ordered pre-model SSE events.

- [ ] Add a failing test proving file/vault/memory/Obsidian/web context events retain their current order and trace IDs.
- [ ] Move setup from `_iter_chat_chunks()` through `assemble_web_context()` into the new stage.
- [ ] Keep `_iter_chat_chunks()` responsible only for yielding the prepared stage events and selecting the next execution path.
- [ ] Run `pytest -q tests/test_chat_turn_context.py tests/test_desktop_api.py -k 'context or runtime'`.
- [ ] Commit: `refactor: extract full turn context preparation`.

### Task 2: Extract Hugo dedicated turn execution

**Status:** completed — commit `1be068c`.

**Files:**
- Create: `terminal/api/hugo_turn.py`
- Modify: `terminal/api/_tools.py`
- Test: `tests/test_hugo_turn.py`

**Produces:** `iter_hugo_turn_events(...)`, yielding the existing deployment heartbeat, tool events, failure hint, token, and terminal done event.

- [ ] Add failing tests for direct deploy success, blocked result, heartbeat, timeout, and fallback summary.
- [ ] Move the dedicated Hugo branch and its worker-thread loop out of `_iter_chat_chunks()`.
- [ ] Preserve current direct deploy priority: delete → attachment redeploy → existing deploy → publish → agent fallback.
- [ ] Run `pytest -q tests/test_hugo_turn.py tests/test_desktop_api.py -k 'hugo or deploy'`.
- [ ] Commit: `refactor: extract hugo turn execution`.

### Task 3: Extract model reply and rescue delivery

**Status:** completed — commit `4b69748`.

**Files:**
- Create: `terminal/api/chat_reply.py`
- Modify: `terminal/api/_tools.py`
- Test: `tests/test_chat_reply.py`

**Produces:** `iter_chat_reply_events(...)`, which owns model selection, heartbeat/status events, safe-token suppression, rescue-stream replacement, failure hint, and empty-reply receipt.

- [ ] Add failing tests for normal chunks, heartbeat, DSML rescue replacement, stream failure terminal order, and empty reply with/without tool activity.
- [ ] Use existing `iter_model_stream()`, `iter_rescue_stream()`, `stream_failure_events()`, and `empty_reply_events()`; do not duplicate them.
- [ ] Pass `RuntimeContext.llm_client` when present; retain the legacy default adapter path.
- [ ] Run `pytest -q tests/test_chat_reply.py tests/test_model_stream_stage.py tests/test_desktop_api.py -k 'model_stream or rescue or empty'`.
- [ ] Commit: `refactor: extract chat reply delivery`.

### Task 4: Extract post-reply draft effects

**Status:** completed — commit `f80ba8d`.

**Files:**
- Create: `terminal/api/post_reply_drafts.py`
- Modify: `terminal/api/_tools.py`
- Test: `tests/test_post_reply_drafts.py`

**Produces:** `iter_post_reply_draft_events(...)` for Obsidian and non-direct Hugo drafts only.

- [ ] Add failing tests for approval-required drafts, direct execution success, blocked policy, empty Obsidian draft, and generation exceptions.
- [ ] Preserve `workIntent`, preview fingerprint, approval cache, tool-event shape, and zero-side-effect behavior for denied drafts.
- [ ] Keep direct Hugo publish in Task 2; this task only handles post-reply draft creation.
- [ ] Run `pytest -q tests/test_post_reply_drafts.py tests/test_tool_stage.py tests/test_desktop_api.py -k 'obsidian_write or hugo'`.
- [ ] Commit: `refactor: extract post reply draft effects`.

### Task 5: Close the `_tools.py` facade batch

**Status:** completed for this chat-turn batch — commit `5aa0d04`; `_tools.py` is 2297 lines, so the Wave 1 global `<800` gate remains open.

**Files:**
- Modify: `terminal/api/_tools.py`, `tests/test_architecture_boundaries.py`

- [ ] Add a failing boundary test that forbids the four extracted execution bodies from returning to `_tools.py`.
- [ ] Reduce `_iter_chat_chunks()` to orchestration: prepare → Hugo short-circuit → tool loop → reply → post-reply drafts → compaction → done.
- [ ] Preserve `_iter_chat_chunks()` as the legacy public facade until callers migrate.
- [ ] Run focused suite, architecture boundaries, Python full suite, Desktop Vitest, and `cd client/desktop && npm run build`.
- [ ] Commit: `refactor: reduce chat turn compatibility facade`.

### Task 6: Split `_routes.py` by business domain, in this order

**Status:** in progress — sessions/threads completed in commit `162d2b9`; jobs is the next isolated domain.

**Files:**
- Create: `terminal/api/session_routes.py`, `terminal/api/job_routes.py`, `terminal/api/memory_routes.py`, `terminal/api/profile_routes.py`, `terminal/api/initiative_routes.py`
- Modify: `terminal/api/_routes.py`, `tests/test_desktop_api.py`, `tests/test_fastapi_routes.py`

- [ ] Extract sessions/threads first; preserve `payload_get()` / `payload_post()` routing and existing response shapes.
- [ ] Extract jobs second as one unit: queueing, child jobs, approval pause/resume, cancel, retry, and parent roll-up stay together.
- [ ] Extract memory/vault/sensors third, then profiles/settings/skills, then Part 8 shadow routes.
- [ ] After each domain, add a facade boundary test, run that domain's route tests, and commit separately.
- [ ] Do not change endpoint paths, auth, or contract envelope during this Wave 1 work.

### Task 7: Wave 1 closure gate

- [ ] Verify `_tools.py < 800` and that its remaining code is only facade/orchestration/legacy aliases.
- [ ] Verify `memory → core` has no unapproved imports and all new DB/LLM paths use explicit runtime dependencies.
- [ ] Run Python full suite, Desktop Vitest, and production build.
- [ ] Run one shortest Journey only when the local API is ready; record a prerequisite block separately from code regression.
- [ ] Update the three canonical Archer documents with exact line counts, test evidence, and verification level.

## Later Queue (Do Not Start Before Task 7)

1. **Wave 2:** Python-authoritative `taskRoute`; TS fallback only; six duplicated skills single-source or consistency-tested; server-authoritative state; event-driven `storeSync`; REST envelope/contract handshake; concurrency ownership table.
2. **Wave 3:** portable export/backup, config/key hardening, Evals, MCP permission policy, trace/performance metrics, Journey 5/6/7 determinism, Durable Outbox, and Part 8 graduation audit.
3. **Post-Wave 3:** exactly one Part 8 shadow → opt-in live vertical slice, then modes/experts single-source.
