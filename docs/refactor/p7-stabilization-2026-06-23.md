# Archer P7 Stabilization

Date: 2026-06-23
Status: stabilization batch, not Part 8

## Why This Exists

Part 7 reached engineering closeout, but daily-use regression checks exposed product polish gaps:

- Workspace IA introduced a visible `Workspace` text toggle in the chat surface.
- Chat stream cancellation and timeout states were too easy to collapse into the same user-facing notice.
- Real multi-turn model usage was underrepresented in the closeout checks.

## Fixed In This Batch

- Kept normal API requests on the short timeout guard while letting `/chat/stream` use the caller cancellation signal directly.
- Preserved `AbortError` from chat streams so manual stop remains distinguishable from network/runtime failures.
- Added adapter tests for stream timeout wrapping and manual cancellation semantics.
- Replaced the chat surface's visible `Workspace` text toggle with a quieter icon-only context-panel button.
- Localized the Workspace context panel landmark/title copy to `工作台上下文` / `上下文`.
- Added explicit timeout notices in the primary send and regenerate flows so timeout is not described as a manual stop.

## Verification

- `cd client/desktop && npm test -- --run src/renderer/src/adapters/__tests__/localArcher.test.ts`

## Still Required Before Part 8

- Run a real installed-app smoke with Kimi:
  - new chat, two consecutive short messages
  - manual stop during generation
  - history session continuation
  - model switch and retry
- State the strongest verified Desktop level separately: dev, build, packaged, or installed.
