# ADR 0001: P7 Workspace Information Architecture

Date: 2026-06-21
Status: accepted

## Context

Archer Desktop currently exposes separate feature routes: Chat, Sessions, Tasks, Memory, Soul, Skills, and Settings. This is understandable for implementation, but it makes the product feel like modules instead of a workbench.

Part 7 has already stabilized the local API and clarified the Python/TS runtime boundary. The next UI change should reorganize surfaces around user workflow without moving the Python core or deleting working pages prematurely.

## Decision

Adopt five target surfaces:

| Surface | Role |
|---|---|
| Today / Home | daily landing, status, latest sessions, pending reviews, active jobs |
| Workspace | main workbench: chat, context, active jobs, skill shortcuts |
| Review | sessions, memory approval, periodic reviews |
| Soul | stable identity/profile and growth narrative |
| Settings | local brain, model/context, skills, schedules, admin controls |

Existing routes remain compatibility render targets during migration. The first implementation slice should relabel and route conservatively before extracting panels or deleting pages.

## Consequences

- Chat remains the primary action surface, but becomes Workspace.
- Sessions and Memory move toward Review.
- Tasks support Workspace/Today rather than remaining a separate mental model.
- Skills move out of primary navigation over time; Settings owns the full catalog, Workspace gets only shortcuts.
- Soul stays top-level because it represents long-term identity rather than daily operations.

## Non-goals

- No Soul Insight Engine implementation in this ADR.
- No packaged app install.
- No broad UI rewrite in one step.
