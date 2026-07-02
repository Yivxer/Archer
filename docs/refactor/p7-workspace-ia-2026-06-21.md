# P7.7 Workspace IA Design

Date: 2026-06-21
Status: design complete, implementation pending

## Goal

Move Archer Desktop from feature-tab navigation toward workflow navigation without rewriting the Python core or removing existing pages in one step.

The new IA should make the first screen useful for daily work, keep chat as the primary action surface, and fold tasks, memory, soul, and settings into places where they support the current workflow instead of competing as equal modules.

## Current State

Current route set:

| Route | Current role | Main issue |
|---|---|---|
| `Chat` | primary conversation surface | Good default, but weak project/work context |
| `Sessions` | history list | Useful, but separated from review and continuation |
| `Tasks` | background jobs | Operationally useful, but isolated from chat/workspace |
| `Memory` | memory review | Useful, but not naturally tied to session review |
| `Soul` | profile/review surface | Good long-term surface, but mixed with daily navigation |
| `Skills` | skill catalog | Advanced/admin surface, should not be main workflow |
| `Settings` | local brain, model, context, config | Correct as admin surface |

## Target IA

| Target route | Purpose | Reuses today |
|---|---|---|
| `Today` / `Home` | Daily landing: local brain status, latest sessions, pending reviews, active jobs | status footer, `Sessions`, pending `Memory`, active `Tasks` |
| `Workspace` | Main workbench: project/context + chat + tool/skill shortcuts + active job strip | `ChatPage`, selected `Tasks`, selected `Skills` |
| `Review` | Retrospective surface: sessions, memory approvals, weekly/monthly/life reviews | `Sessions`, `MemoryPage`, review sections in `SoulPage` |
| `Soul` | Stable identity/profile surface: Soul profile, growth markers, narrative state | `SoulPage` profile sections |
| `Settings` | Admin/config surface: brain connection, model/context, skills, schedules | `SettingsPage`, `SkillsPage` |

## Route Mapping

| Existing route | Target home | Migration rule |
|---|---|---|
| `Chat` | `Workspace` | Keep component first; wrap with workspace shell later |
| `Sessions` | `Review` and `Today` | Sessions list becomes reusable panel |
| `Tasks` | `Workspace` and `Today` | Active jobs move near work; full list can remain behind a panel |
| `Memory` | `Review` | Pending memory review belongs to review workflow |
| `Soul` | `Soul` | Keep as a stable top-level route |
| `Skills` | `Settings` and `Workspace` shortcuts | Catalog moves to settings; selected shortcuts appear in workspace |
| `Settings` | `Settings` | Keep top-level |

## First Implementation Slice

Do not rewrite all pages at once.

1. Introduce target route labels/types while preserving old route render targets.
2. Rename sidebar labels conservatively:
   - `Chat` -> `Workspace`
   - `Sessions` -> `Review`
   - `Skills` -> move entry under `Settings` later, keep hidden or secondary only after Settings has a skills panel.
3. Keep current components mounted behind compatibility routes until each target surface has equivalent functionality.
4. Add reusable panels only when a page is moved:
   - `SessionListPanel`
   - `ActiveJobsPanel`
   - `PendingMemoryPanel`
   - `SkillShortcutPanel`

## UX Rules

- First screen should be usable, not a marketing/overview page.
- Preserve direct chat entry and keyboard flow.
- Do not hide pending approvals or running jobs behind deep navigation.
- API offline state must still show cached sessions/runtime events where available.
- Advanced skill catalog belongs in Settings; common action shortcuts belong in Workspace.

## Non-goals

- No Python API change for P7.7 IA.
- No Soul Insight Engine implementation here; that remains P7.8.
- No packaged app install as part of this design step.
- No full visual redesign before route compatibility is proven.

## Acceptance

- Design gives a clear mapping from every current route to a target surface.
- First implementation slice can be done without deleting existing pages.
- Desktop build remains the verification floor for any later UI slice.
