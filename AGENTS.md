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

## Documentation

- Update the Obsidian Archer growth plan when the work changes project direction, policy, or completed milestones.
- Keep notes concise and factual: what broke, root cause, fix, tests.
