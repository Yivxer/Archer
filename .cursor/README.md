# Cursor agent skills (Archer)

[addyosmani/agent-skills](https://github.com/addyosmani/agent-skills) is vendored at `.cursor/vendor/agent-skills/` and exposed to Cursor via symlinks in `.cursor/skills/`.

## Usage

- Start a session with **using-agent-skills** in mind — it routes tasks to the right workflow (spec, TDD, review, ship, etc.).
- For product/UI work: **frontend-ui-engineering**, **code-review-and-quality**, **performance-optimization**.
- For Archer runtime changes: **incremental-implementation** + **test-driven-development** + **debugging-and-error-recovery**.
- Shared checklists live under `.cursor/skills/references/`; specialist personas under `.cursor/skills/agents/`.
- Project collaboration constraints remain in `AGENTS.md` (token budget, minimal verification first).

## Update

```bash
git submodule update --remote .cursor/vendor/agent-skills
```

Symlinks in `.cursor/skills/` pick up changes automatically; no copy step needed.
