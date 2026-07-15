# Part 10 Wave 2 Session Authority Plan

**Goal:** Make `sessionStore` the single Desktop projection for session list, detail, and search reads.

**Boundary:** This batch migrates `main.tsx` and ReviewPage reads. Session persistence remains server-owned through the existing REST actions; profile, approval, and broader storeSync event delivery remain separate work.

## Tasks

- [x] Add a source boundary test preventing direct session read/search adapter calls from consumers.
- [x] Route main session restore through `sessionStore.loadSessionDetail()`.
- [x] Replace ReviewPage-local detail/search state with `sessionStore` selectors and actions.
- [x] Preserve debounce behavior without storing a second result set in ReviewPage.
- [x] Add stale-response guards for rapid detail selection and search query changes.
- [x] Add deterministic concurrency tests for detail and search races.
- [x] Run session Python tests, full Desktop Vitest, and production build.
- [ ] Update canonical Archer documents and commit the batch.
