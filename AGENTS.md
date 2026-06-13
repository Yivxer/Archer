# Archer Collaboration Rules

## Role

- Act as a pragmatic long-term collaborator.
- Prefer direct fixes, durable notes, and small verified steps.
- Keep Archer stable before expanding capabilities.

## Token And Execution Budget

- Default to low-cost inspection first: `rg`, targeted `sed`, small diffs, and focused tests.
- Do not read large logs, full files, broad git diffs, or long generated outputs unless the task clearly needs them.
- Do not run long real model/API streaming checks as the first verification path. Prefer unit tests or short synthetic requests.
- For real app/API verification, use the shortest request that proves the behavior. Avoid pasting long user text into repeated live requests.
- After one failed fix attempt, pause and state the new suspected root cause before continuing deeper.
- After two rounds of investigation or a likely high-cost action, stop and report the cost/risk tradeoff before proceeding.
- Keep command output narrow with `rg`, line ranges, `tail -n`, and file-specific status checks.
- Avoid repeatedly printing full diffs. Use `git diff --stat`, `git diff --name-status`, then inspect only the changed hunks that matter.
- When the user is debugging a live breakage, prioritize a minimal rollback/fix path over broad architecture cleanup.

## Verification Defaults

- Run the smallest relevant test first.
- Run broader tests only when the touched surface justifies it.
- Use one real API/UI smoke test after tests pass, unless the user explicitly asks for deeper validation.
- If a real verification may consume model/API quota, say so before running it unless it is clearly tiny.
- Low-cost smoke order for Desktop/API work:
  1. focused unit or route test for the touched behavior
  2. broader local suite only if the touched surface is shared
  3. `npm run build` only for Desktop TypeScript/renderer/main changes
  4. real Electron/API smoke only when UI/runtime behavior changed or tests cannot prove it
- Real model/API smoke must use the shortest prompt that proves the behavior; avoid long user text, repeated live streams, or quota-heavy checks unless explicitly approved.

## Desktop Runtime Status

- After Desktop changes, state the strongest verification level reached:
  - `dev verified`: checked through `npm run dev` or Electron dev smoke.
  - `build verified`: `cd client/desktop && npm run build` passed, but no packaged app was installed.
  - `packaged`: DMG/app package was built.
  - `installed`: the packaged app was installed/replaced on the user's machine.
- Do not imply an installed app changed when only source, dev server, tests, or build output changed.
- If only tests/build ran, say that explicitly and leave manual installed-app verification as a separate item.

## Documentation

- Update the Obsidian Archer growth plan when the work changes project direction, policy, or completed milestones.
- Keep notes concise and factual: what broke, root cause, fix, tests.
