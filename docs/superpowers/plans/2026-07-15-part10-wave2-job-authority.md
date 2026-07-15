# Part 10 Wave 2 Job Authority Plan

**Goal:** Make the server-backed `jobStore` the only Tasks page state projection and feed job SSE events into it.

**Boundary:** This batch covers the job domain only. Session, profile, approval, and broader `storeSync` event migration remain separate Wave 2 work.

## Tasks

- [x] Add a source boundary test requiring TasksPage to use `jobStore` and forbidding delayed refresh polling.
- [x] Replace TasksPage-local `jobs / jobDetail / loadState` with `jobStore` selectors and actions.
- [x] Project server action responses into both job list and selected detail.
- [x] Feed Chat `job.event` SSE payloads into `jobStore.mergeJobEvent()`.
- [x] Reuse the adapter `SpawnChildSpec` request type instead of duplicating it.
- [x] Run focused Python/Vitest tests, full Desktop Vitest, and production build.
- [ ] Update canonical Archer documents and commit the batch.
