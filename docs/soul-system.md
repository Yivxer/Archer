# Soul System

Archer has a three-layer system for shaping how it thinks about you and how it shows up in conversation.

## The three layers

### SOUL.md — Who you are

Your long-term soul archive. Archer reads this when you ask for decisions, reflections, or emotionally-weighted guidance.

**What to put here:**
- Your values, in priority order
- Core tensions — pairs of things that pull against each other in your life
- Defense patterns — how you tend to avoid discomfort
- Recovery mechanisms — what actually helps when things go wrong
- How you want to work with AI

Archer will never overwrite this file automatically. Changes are proposed via `/soul list` and accepted only by you.

### COVENANT.md — Hard limits

The root covenant defines what Archer will and won't do, regardless of how you ask.

**What to put here:**
- Behaviors you never want Archer to perform
- Positive commitments you want Archer to uphold
- How to handle silence and absence

This file is not editable during a session. To propose a change, use `/covenant propose`. The proposal is saved to history — you review and apply it yourself.

### PRESENCE.md — How Archer shows up

The interaction style for this relationship. More flexible than COVENANT, more specific than mode settings.

**What to put here:**
- Default tone (coaching, listening, challenging)
- Response pacing rules
- How to handle dense or abstract topics
- How to handle sensitive personal topics
- When and how to push toward action

To suggest a change, use `/presence suggest`. Like covenant proposals, changes are saved for your review.

---

## Injection logic

Archer doesn't inject all three layers every turn — that would waste tokens on simple questions.

| Query type | SOUL injected? | MEMORY.md injected? |
|------------|---------------|---------------------|
| `chat` (greeting, simple question) | No | No |
| `task` (do something) | No | Yes |
| `project` (project-related) | No | Yes |
| `decision` (choice, advice) | **Yes** | Yes |
| `emotional` (feelings, wellbeing) | **Yes** | Yes |
| `reflection` (retrospective, pattern) | **Yes** | Yes |

COVENANT and PRESENCE summaries are injected on every turn (they're short).
Runtime safety rules are always injected first, before everything else.

---

## SOUL evolution

As you use Archer, it may detect signals worth adding to your soul archive:

- Identity statements ("I've realized that I...")
- Significant decisions
- Recurring patterns surfaced in reflections

When it detects one, it creates a `soul_proposal`. You review these with:

```
/soul list
```

Accept proposals that resonate:
```
/soul accept 3
```

Accepted proposals are **appended** to the end of SOUL.md with a timestamp. The original content is never modified.

---

## Self-critique system

Separate from soul evolution, Archer has a self-critique mechanism for observing its own behavior patterns.

```
/critique list
```

A critique is an observation about Archer's own tendencies — for example, noticing it's been over-explaining when you wanted brevity.

Critiques are:
- Stored in `self_critiques` table
- Reviewed by you, not auto-applied
- Rate-limited (max 1 per session from automatic detection)
- Not used to automatically change code or behavior

Think of it as Archer's introspection log, not a behavior patch system.

---

## Templates

The `templates/` directory contains starting points for all four files:

- `templates/SOUL.template.md`
- `templates/MEMORY.template.md`
- `templates/COVENANT.template.md`
- `templates/PRESENCE.template.md`

The installer copies these to `~/.archer/`. They're intentionally minimal — fill them in at your own pace.
