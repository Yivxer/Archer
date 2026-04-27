# Memory System

Archer maintains long-term memory across sessions using SQLite and optional vector search.

## How it works

```
Conversation
    → session ends (or /reflect, /exit, every 6 turns)
    → background extraction thread runs
    → LLM proposes candidate memories
    → stored in pending_memories table
    → you review with /memory pending
    → /memory accept → written to memories table
    → future sessions retrieve relevant memories automatically
```

Memories are never auto-accepted. You always decide what persists.

## Memory types

| Type | Purpose | Decay |
|------|---------|-------|
| `identity` | Who you are — values, personality | never |
| `preference` | How you work, what you like | never |
| `decision` | Significant decisions made | never |
| `insight` | Things you've learned | never |
| `project` | Project progress and blockers | 60 days unused |
| `todo` | Commitments and to-dos | 60 days unused |
| `risk` | Potential problems flagged | 60 days unused |
| `context` | Temporary situational context | 30 days unused |
| `reflection` | Session reflection summaries | 30 days unused |

**Decay** means importance score drops by 1 when unused past the threshold (floor: 1). Identity and decision memories are immune to decay.

## Retrieval

Each turn, Archer retrieves the most relevant memories using:

1. **Vector search** (if `sqlite-vec` + `sentence-transformers` are installed) — semantic similarity
2. **FTS5 full-text search** — keyword matching
3. **De-duplication** — combined results are de-duped

The top 5 memories (configurable) are injected into the system prompt when relevant.

**Lightweight queries** (short, no decision keywords) skip memory injection — this saves ~1KB/turn for simple conversation.

## Memory fields

```sql
content      TEXT     -- the memory content
type         TEXT     -- one of the types above
scope        TEXT     -- 'user' (default) or custom scope
confidence   REAL     -- 0.7 for auto-extracted, 0.9 for manual
importance   INTEGER  -- 1-5 (★4+ are "core memories")
valid_until  TEXT     -- expiry date (optional)
last_used_at TEXT     -- last retrieval timestamp (used for decay)
session_id   TEXT     -- which session created this memory
status       TEXT     -- 'active' or 'archived'
```

## Memory health check

`/memory review` runs a health scan and flags:

- Apparent duplicates
- Conflicting memories
- Expired entries (`valid_until` in the past)
- High-importance insights that might need updating

It does not auto-delete anything — you decide what to do.

## Behavior themes

`/themes detect` runs a cross-session pattern analysis:

1. Archer reads your memory store
2. LLM identifies recurring behavioral patterns
3. Each pattern must pass quality gates before being stored:
   - Name ≤ 12 characters
   - At least 2 supporting memories
   - Memories must come from at least 2 different sessions

This prevents single-session "fake patterns" from being recorded as long-term themes.

## Searching memories

```
/memory search <term>
```

- Terms of 3+ characters use the FTS5 index
- Terms of 1-2 characters fall back to LIKE search
- With vector search installed, semantic similarity is also applied

## Manual memory management

Add a memory directly:
```
/memory add I work best when I have one clear priority, not three parallel tracks.
```

Update an existing memory:
```
/memory update 42 I work best in 90-minute focused blocks, not open-ended sessions.
```

Archive (soft-delete):
```
/memory archive 42
```
