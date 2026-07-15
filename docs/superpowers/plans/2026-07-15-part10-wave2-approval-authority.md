# Part 10 Wave 2 Approval Authority Plan

**Goal:** Keep approval state exclusively in the server event projection handled by `runtimeStore`.

## Tasks

- [x] Trace production callers of the standalone Desktop approval queue.
- [x] Add a boundary test requiring `tool.request` and `approval.result` runtime reduction.
- [x] Delete the unused `approvalQueue.ts`, its isolated tests, and public exports.
- [x] Run approval/runtime focused Vitest and production build.
- [x] Run full Desktop regression, update canonical Archer documents, and commit.
