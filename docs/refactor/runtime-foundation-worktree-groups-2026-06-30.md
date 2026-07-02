# Runtime Foundation Worktree Groups - 2026-06-30

This document groups the current large dirty worktree into safe review/commit batches.
It is a handoff map only: no files are staged by this document.

## Current State

- Scope: Archer Runtime Foundation stabilization plus Trae additions.
- Verification already reached: installed smoke verified after the latest DeepSeek baseline change.
- Installed app backup from latest install: `/Applications/.archer-backups/Archer.app.backup-20260630-203946`.
- Recommended rule: stage and commit one group at a time; rerun the group's focused tests before each commit.

## Suggested Commit Order

### 1. Desktop API Process And Model Switching

Purpose:
- Stop API self-recovery storms.
- Make model switching read-back verified.
- Keep DeepSeek/lite as the temporary default test baseline.

Files:
- `client/desktop/src/main/apiProcess.ts`
- `client/desktop/src/main/apiProcess.test.ts`
- `client/desktop/src/main/index.ts`
- `client/desktop/src/renderer/src/adapters/localArcher.ts`
- `client/desktop/src/renderer/src/adapters/__tests__/localArcher.test.ts`
- `client/desktop/src/renderer/src/lib/conversationPersona.ts`
- `client/desktop/src/renderer/src/lib/__tests__/conversationPersona.test.ts`
- `client/desktop/src/renderer/src/pages/ChatPage.tsx`
- `client/desktop/src/renderer/src/styles/chat.css`
- `client/desktop/src/renderer/src/types.ts`
- `terminal/api/fastapi_app.py`
- `terminal/api/_routes.py`
- `tests/test_fastapi_routes.py`
- `archer.toml`

Focused verification:
- `cd client/desktop && npm test -- --run src/renderer/src/lib/__tests__/conversationPersona.test.ts src/renderer/src/adapters/__tests__/localArcher.test.ts src/main/apiProcess.test.ts`
- `.venv/bin/pytest tests/test_fastapi_routes.py::test_health_ready_and_status_are_not_rate_limited -q`
- `cd client/desktop && npm run build`

Notes:
- `archer.toml` contains local API keys. Do not commit it unless the repo policy already treats it as local-only and ignored; prefer committing examples/templates separately.

### 2. Runtime Contracts, Trace, Permissions, And Event Log

Purpose:
- Preserve traceId across runtime/tool/approval/job events.
- Add visible trace diagnostics and permission levels.
- Keep runtime restore from reviving stale work.

Files:
- `client/desktop/src/agent/contracts.ts`
- `client/desktop/src/agent/contractSchemas.ts`
- `client/desktop/src/agent/pythonBridge.ts`
- `client/desktop/src/agent/index.ts`
- `client/desktop/src/agent/eventLog.ts`
- `client/desktop/src/agent/runtimeStore.ts`
- `client/desktop/src/agent/jobBridge.ts`
- `client/desktop/src/agent/taskRouter.ts`
- `client/desktop/src/agent/traceDiagnostics.ts`
- `client/desktop/src/agent/__tests__/contractSchemas.test.ts`
- `client/desktop/src/agent/__tests__/pythonBridge.test.ts`
- `client/desktop/src/agent/__tests__/traceDiagnostics.test.ts`
- `client/desktop/src/agent/__tests__/eventLog.test.ts`
- `client/desktop/src/agent/__tests__/runtimeStore.test.ts`
- `client/desktop/src/agent/__tests__/jobBridge.test.ts`
- `client/desktop/src/agent/__tests__/taskRouter.test.ts`
- `core/permission_levels.py`
- `core/cache_policy.py`
- `core/api_tool_service.py`
- `terminal/api/_config.py`
- `tests/test_api_tool_service.py`
- `tests/test_doctor.py`

Focused verification:
- `cd client/desktop && npm test -- --run src/agent/__tests__/contractSchemas.test.ts src/agent/__tests__/pythonBridge.test.ts src/agent/__tests__/traceDiagnostics.test.ts src/agent/__tests__/eventLog.test.ts src/agent/__tests__/runtimeStore.test.ts`
- `.venv/bin/pytest tests/test_api_tool_service.py tests/test_doctor.py -q`

### 3. Desktop UI Stabilization And Diagnostics

Purpose:
- Settings diagnostic tab, permission matrix visualization, lazy page loading, chat/task visibility, model/user-facing states.

Files:
- `client/desktop/src/renderer/src/main.tsx`
- `client/desktop/src/renderer/src/pages/SettingsPage.tsx`
- `client/desktop/src/renderer/src/pages/TasksPage.tsx`
- `client/desktop/src/renderer/src/pages/MemoryPage.tsx`
- `client/desktop/src/renderer/src/pages/SoulPage.tsx`
- `client/desktop/src/renderer/src/pages/TodayPage.tsx`
- `client/desktop/src/renderer/src/pages/ReviewPage.tsx`
- `client/desktop/src/renderer/src/components/ExpertAvatar.tsx`
- `client/desktop/src/renderer/src/components/ReviewPanels.tsx`
- `client/desktop/src/renderer/src/components/WorkspaceContextPanel.tsx`
- `client/desktop/src/renderer/src/components/common.tsx`
- `client/desktop/src/renderer/src/lib/brainConnection.ts`
- `client/desktop/src/renderer/src/lib/initiativeShadow.ts`
- `client/desktop/src/renderer/src/lib/thinkingMutter.ts`
- `client/desktop/src/renderer/src/lib/__tests__/initiativeShadow.test.ts`
- `client/desktop/src/renderer/src/lib/__tests__/thinkingMutter.test.ts`
- `client/desktop/src/renderer/src/styles.css`
- `client/desktop/src/renderer/src/styles/base.css`
- `client/desktop/src/renderer/src/styles/composer.css`
- `client/desktop/src/renderer/src/styles/pages.css`
- `client/desktop/src/renderer/src/styles/sidebar.css`
- `client/desktop/src/renderer/src/styles/tools.css`
- `client/desktop/src/renderer/src/types.ts`
- `client/desktop/src/renderer/src/vite-env.d.ts`
- `tests/test_today_page.py`
- `tests/test_desktop_mock_preview_states.py`
- `tests/test_chat_page_natural_copy.py`

Focused verification:
- `cd client/desktop && npm test -- --run src/renderer/src/lib/__tests__/initiativeShadow.test.ts src/renderer/src/lib/__tests__/thinkingMutter.test.ts`
- `cd client/desktop && npm run build`

### 4. Tool Runtime, Skills Safety, Hugo, And Obsidian

Purpose:
- Skill exception safety.
- Side-effect idempotency.
- Obsidian write safeguards.
- Hugo publish/new/deploy resilience.

Files:
- `core/tool_runtime.py`
- `core/desktop_tool_router.py`
- `core/skill_router.py`
- `core/policy.py`
- `skills/_vault.py`
- `skills/obsidian_write.py`
- `skills/obsidian_read.py`
- `skills/obsidian_search.py`
- `skills/hugo_blog.py`
- `skills/browser_automation.py`
- `skills/clipboard.py`
- `skills/image_analysis.py`
- `skills/image_generator.py`
- `skills/installer.py`
- `skills/memory_save.py`
- `skills/weekly_review.py`
- `terminal/api/_tools.py`
- `tests/test_obsidian_write_preview.py`
- `tests/test_hugo_blog_publish.py`
- `tests/test_desktop_tool_router.py`
- `tests/test_policy.py`
- `tests/test_skill_security.py`

Focused verification:
- `.venv/bin/pytest tests/test_obsidian_write_preview.py tests/test_hugo_blog_publish.py tests/test_desktop_tool_router.py tests/test_policy.py tests/test_skill_security.py -q`

### 5. SSRF And URL Safety Follow-Up

Purpose:
- Keep external URL checks behind URL safety gates.

Files:
- `skills/site_check.py`
- `skills/weather.py`
- `skills/web_search.py`
- `skills/hugo_blog.py`
- `workflows/url_to_reading_note.py`
- `web/public/assets/web-companion.js`
- `tests/test_skill_security.py`

Focused verification:
- `.venv/bin/pytest tests/test_skill_security.py -q`

Notes:
- `skills/hugo_blog.py` overlaps group 4. If staging is difficult, include it in group 4 and keep group 5 as a review checklist only.

### 6. Background Jobs, Scheduler, Memory, And Part 8 Shadow

Purpose:
- Zombie job cleanup.
- Background job stale/cancel semantics.
- Part 8 shadow/error-isolation and proactive systems.

Files:
- `core/orchestrator.py`
- `core/context.py`
- `core/llm.py`
- `core/model_select.py`
- `core/proactive.py`
- `core/scheduler.py`
- `core/session_store.py`
- `memory/retrieve.py`
- `memory/store.py`
- `memory/soul_profile.py`
- `memory/hypothesis_tracker.py`
- `workflows/vault_reflection.py`
- `tests/test_p4_orchestrator.py`
- `tests/test_model_select.py`
- `tests/test_proactive_touch.py`
- `tests/test_scheduler.py`
- `tests/test_soul_profile.py`
- `tests/test_token_tracking.py`
- `tests/test_hypothesis_tracker.py`
- `tests/test_vault_reflection.py`
- Part 8 files and tests:
  - `core/arbitrator.py`
  - `core/attention.py`
  - `core/connector.py`
  - `core/delivery_opt_in.py`
  - `core/devil.py`
  - `core/dissent.py`
  - `core/event_bus.py`
  - `core/experts.py`
  - `core/feedback.py`
  - `core/initiative_shadow.py`
  - `core/moments.py`
  - `core/monologue.py`
  - `core/opportunity.py`
  - `core/part8_clues.py`
  - `core/part8_retention.py`
  - `core/part8_threads.py`
  - `core/pipeline.py`
  - `core/presence.py`
  - `core/reflection_cycle.py`
  - `core/reflection_scheduler.py`
  - `core/reframer.py`
  - `core/rhythm.py`
  - `core/scorer.py`
  - `core/shadow_validation.py`
  - `core/surprise.py`
  - `core/threshold.py`
  - `core/voice.py`
  - `tests/test_part8_*.py`
  - `tests/test_experts.py`
  - `tests/test_expert_memory_tags.py`

Focused verification:
- `.venv/bin/pytest tests/test_p4_orchestrator.py tests/test_model_select.py tests/test_scheduler.py tests/test_proactive_touch.py -q`
- `.venv/bin/pytest tests/test_part8_*.py tests/test_experts.py tests/test_expert_memory_tags.py -q`

Notes:
- This is the largest and riskiest group. Consider splitting into:
  1. runtime/job/scheduler/memory
  2. Part 8 shadow modules
  3. Part 8 tests

### 7. Config, Packaging, Install, And Docs

Purpose:
- Installed smoke, local packaging, config examples, and contract documentation.

Files:
- `client/desktop/package.json`
- `client/desktop/package-lock.json`
- `client/desktop/.nvmrc`
- `client/desktop/scripts/hide-helper-apps-mac.sh`
- `client/desktop/scripts/install-local-mac.sh`
- `scripts/verify_desktop_live.sh`
- `tests/test_desktop_packaging.py`
- `README.md`
- `docs/api-contract.md`
- `docs/p5-plugin-design.md`
- `archer.toml.example`
- `templates/archer.example.toml`
- `terminal/archer.py`
- `terminal/archer_api.py`
- `terminal/commands/skill.py`
- `terminal/ui.py`
- `terminal/api/_security.py`
- `tests/test_config_lock.py`

Focused verification:
- `.venv/bin/pytest tests/test_desktop_packaging.py tests/test_config_lock.py -q`
- `cd client/desktop && npm run build`
- `VERIFY_OPEN_APP=1 bash scripts/verify_desktop_live.sh`

### 8. Obsidian Sensor Integration

Purpose:
- Vault focus sensor integration and installer.

Files:
- `integrations/obsidian-archer-sensor/README.md`
- `integrations/obsidian-archer-sensor/main.js`
- `integrations/obsidian-archer-sensor/manifest.json`
- `scripts/install_obsidian_archer_sensor.sh`
- `knowledge/__init__.py`
- `knowledge/vault_sensor.py`
- `tests/test_vault_sensor.py`

Focused verification:
- `.venv/bin/pytest tests/test_vault_sensor.py -q`

### 9. Non-Core / Review Separately

Files:
- `CLAUDE.md`
- `overview.md`
- `archer-showcase.html`
- `contest/archer-soul-demo.html`
- `contest/trae-application-guide.md`
- `archer.toml.bak.20260623_204948`
- Chinese `.docx` technical documents

Recommendation:
- Do not include these in Runtime Foundation commits unless there is a clear reason.
- `archer.toml.bak.20260623_204948` should likely stay untracked or be removed manually after confirmation.
- `.docx` files should be explicitly reviewed before staging.

## Final Integration Verification

After all intended groups are committed or at least staged cleanly:

1. `.venv/bin/pytest tests/test_fastapi_routes.py tests/test_desktop_api.py tests/test_doctor.py tests/test_obsidian_write_preview.py tests/test_hugo_blog_publish.py tests/test_skill_security.py -q`
2. `cd client/desktop && npm test -- --run src/main/apiProcess.test.ts src/renderer/src/adapters/__tests__/localArcher.test.ts src/agent/__tests__/contractSchemas.test.ts src/agent/__tests__/pythonBridge.test.ts src/agent/__tests__/traceDiagnostics.test.ts`
3. `cd client/desktop && npm run build`
4. `cd client/desktop && npm run build:mac:local`
5. `VERIFY_OPEN_APP=1 bash scripts/verify_desktop_live.sh`

## Current Recommended Next Action

Do not stage everything at once.
Start with group 1 because it is the smallest user-visible stability fix and already has recent installed smoke evidence.
