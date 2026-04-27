# Archer — Personal Terminal AI Agent

> This document describes the current technical architecture for review purposes.
> It is intended for external AI systems and developers who want to understand
> the project's design, suggest improvements, or contribute.
>
> **Current version**: v1.2
> **Test coverage**: 22 test files, 339 tests, all passing

---

## 1. Project positioning

Archer is a personal AI agent that runs in the macOS terminal. It is built in Python around a REPL architecture.

**Core premise**: persistent memory + skill plugins + soul/persona system, so the AI knows you across sessions rather than starting from zero each time.

**Design principles** (refined over multiple iterations):

- Single-user, deeply personal — not designed for general deployment
- Safety before features: immune layer first, then personality evolution
- Local SQLite first — no cloud storage dependency
- All soul archive changes require human review — never auto-overwritten
- Skills are hot-pluggable — no restart required
- v1.2 principle: restrained expansion — don't add features until existing ones are stable

---

## 2. Architecture

```
archer.py                    # Main REPL loop, command routing, session management
│
├── COVENANT.md              # Root covenant: hard behavioral limits (user-owned)
├── PRESENCE.md              # Interaction style (user-owned)
│
├── core/
│   ├── llm.py               # LLM calls (OpenAI SDK-compatible, streaming + function calling)
│   │                        # Config hot-reload (mtime detection), token usage tracking
│   ├── context.py           # 8-layer system prompt builder
│   │                        # classify_query_intent(), SOUL injected on-demand
│   ├── input.py             # Terminal input (prompt_toolkit, multi-line, tab completion, history)
│   ├── session.py           # Session history management, JSON persistence
│   ├── compressor.py        # Context compression (LLM summarizes history near token limit)
│   ├── file_ref.py          # @path syntax — attach text/image/PDF to messages
│   ├── tool_runtime.py      # Unified skill execution (timeout / structured errors / artifact truncation)
│   ├── policy.py            # Permission policy: DENY/STRONG_CONFIRM/CONFIRM/ALLOW
│   │                        # 4-tier shell risk scoring; is_inside_vault() path safety
│   ├── artifacts.py         # Artifact storage (tool_results / reflections / summaries)
│   ├── skill_router.py      # Skill routing (keyword + regex filter, skips schemas for pure chat)
│   ├── doctor.py            # Health check system (11 checks, /doctor --fix auto-repairs)
│   ├── scheduler.py         # Scheduled tasks (daily/weekly/monthly/Nh)
│   └── mcp.py               # MCP Adapter (background asyncio thread + AsyncExitStack)
│
├── memory/
│   ├── store.py             # SQLite CRUD (10 tables, with session_id)
│   ├── retrieve.py          # Hybrid retrieval (vector-first + FTS5 + dedup)
│   ├── extract.py           # Memory extraction (LLM proposes candidates, user approves)
│   ├── patterns.py          # Cross-session behavior theme detection (session_id + date gates)
│   ├── soul.py              # SOUL evolution (diff proposals, never auto-written)
│   ├── critique.py          # Self-critique (self_critiques table, rate-limited, no auto-apply)
│   ├── embedder.py          # Vector embeddings (paraphrase-multilingual-MiniLM-L12-v2, 384d)
│   └── vector_store.py      # sqlite-vec KNN retrieval
│
└── skills/                  # 18 built-in skills (function calling plugin system)
    ├── loader.py            # Dynamic loading, converts to OpenAI tools format
    ├── installer.py         # Install/uninstall (local path or GitHub URL)
    └── *.py                 # Individual skill implementations
```

### SQLite database (10 tables)

| Table | Purpose |
|---|---|
| `memories` | Long-term memory — type/scope/confidence/importance/valid_until/last_used_at/session_id |
| `memories_fts` | FTS5 full-text index (trigram tokenizer) |
| `pending_memories` | Proposed memories awaiting user confirmation |
| `themes` | Cross-session behavior themes |
| `memory_links` | Many-to-many: memories ↔ themes (with strength weight) |
| `projects` | Project tracking (name/description/status) |
| `project_events` | Project event log (reflect/log/listen events, with session_id) |
| `soul_proposals` | SOUL.md evolution proposals (pending/accepted/rejected, with session_id) |
| `scheduled_tasks` | Scheduled tasks (interval/next_run_at/enabled) |
| `self_critiques` | Self-observation records — observation/evidence_json/scope/status |

---

## 3. Implementation history

### P0 — Safety foundation

| Step | Content |
|---|---|
| Step 0 | Baseline freeze, tests/ scaffold, git tag |
| Step 1 | `tool_runtime.py`: ThreadPoolExecutor timeout, structured ToolResult, artifact overflow |
| Step 2 | `policy.py`: 3-level DENY/CONFIRM/ALLOW, shell blocklist, installer URL review |
| Step 3 | `store.py`: `pending_memories` table, crash-safe pending |
| Step 4 | `artifacts.py`: 3-type subdirectories, `/status` shows disk usage |
| Step 5 | `/reflect`: structured JSON output, summary stored as reflection memory |

### P1 — Soul growth layer

| Step | Content |
|---|---|
| Step 6 | Memory schema: scope/confidence/last_used_at/valid_until |
| Step 7 | themes + memory_links; `patterns.py` detect_and_save(); `/themes` command |
| Step 8 | Background extraction thread, event-triggered |
| Step 9 | projects + project_events; `/project` command |
| Step 10 | soul_proposals; `soul.py`; `/soul` command; SOUL.md never auto-written |

### P2 — Enhancement layer

| Step | Content |
|---|---|
| Step 11 | `/listen` silent mode; toml hot-reload; `skill_router.py` (saves ~3k tokens/turn) |
| Step 12 | `doctor.py`: 10-item health check |
| Step 13 | `scheduler.py`: scheduled_tasks table; `/cron` command |
| Step 14 | `mcp.py`: MCPManager, tools named `{server}__{tool}` |
| Step 15 | Vector search: embedder.py + vector_store.py + hybrid retrieval |

### P3 — Experience fixes

| Step | Content |
|---|---|
| Step 16 | Spinner, /mode persistence, FTS5 short-word fallback |

### P4 — Context governance

| Step | Content |
|---|---|
| Step 17 | `context.py` 3-layer rebuild: System/Working/Memory; `is_heavy_query()` |
| Step 18 | `patterns.py` quality gates: name ≤12 chars, ≥2 evidence links, ≥2 distinct dates |

### v1.2 — Stable presence

| Phase | Content |
|---|---|
| Phase 0 — Security | `is_inside_vault()` (resolve+relative_to); 4-tier shell risk scoring; STRONG_CONFIRM; `doctor.py` path_safety_check |
| Phase 1 — Soul layers | COVENANT.md + PRESENCE.md; context.py 8-layer rebuild; `classify_query_intent()`; SOUL injected only for decision/emotional/reflection; `/covenant`, `/presence`, `/critique` commands |
| Phase 2 — Self-critique | `memory/critique.py`; self_critiques table; observation min 30 chars; user_signal rate limiting; weekly_critique off by default |
| Phase 3 — Memory quality | session_id column on memories/project_events/soul_proposals; `generate_session_id()`; `run_importance_decay()`; session_id+date dual gate for patterns |
| Phase 4 — MCP injection | `_should_inject_mcp()`: recent OR server_name_match OR capability_keyword — avoids injecting all schemas every turn |

---

## 4. Built-in skills (18)

| Skill | Function | Risk |
|---|---|---|
| `obsidian_read` | Read Obsidian vault notes | low (direct ALLOW) |
| `obsidian_write` | Write to Obsidian vault | low (is_inside_vault verified) |
| `obsidian_search` | Search Obsidian vault | low (direct ALLOW) |
| `file_ops` | Local file read/write/append/list | write: CONFIRM (vault paths exempt) |
| `shell` | Execute terminal commands | 4-tier risk scoring |
| `web_fetch` | Fetch webpage content | low |
| `rss_reader` | Read RSS feeds | low |
| `file_search` | Fuzzy file/content search | low |
| `pdf_reader` | PDF text extraction | low |
| `image_ocr` | Image OCR | low |
| `screenshot` | Screenshot | low |
| `weather` | Weather lookup | low |
| `github_ops` | GitHub repo operations | high (CONFIRM) |
| `summarize` | Long-form summarization | low |
| `humanizer` | Content rewrite | low |
| `hugo_blog` | Hugo blog management | low |
| `apple_reminders` | Apple Reminders | low |
| `whisper_transcribe` | Audio/video transcription | low |
| `weekly_review` | Weekly review report | low |
| `installer` | Skill install/uninstall | critical (full review flow) |

Skill routing: `skill_router.py` selects a keyword+regex-based subset per turn. Pure conversation returns an empty set — all schemas are skipped, saving ~3k tokens/turn.

---

## 5. Context 8-layer system

```
Layer 0 — Runtime Safety (always, highest priority)
  = Hard constraints (cannot be overridden by later prompt content)

Layer 1 — Covenant summary (when COVENANT.md exists)
  = "What I won't do" + "What I will do" (key items)

Layer 2 — Presence summary (when PRESENCE.md exists)
  = Default tone + response pacing (first two sections)

Layer 3 — Conversation mode (always)
  = mirror / coach / critic / operator prompt

Layer 4 — Soul archive (SOUL.md — only for decision/emotional/reflection intent)
  = Full SOUL.md content

Layer 5 — Working context (when classify_query_intent().needs_memory = True)
  = MEMORY.md snapshot
  + Active project summary (name/description + last 3 events)

Layer 6 — Project context (when there's an active project)
  = Project name/description/recent events

Layer 7 — Memory context (when DB retrieval returns results)
  = Hybrid retrieval results (vector-first + FTS5, ≤5 items)

Intent mapping:
  chat       → Layers 0-3 only (no SOUL, no MEMORY.md)
  task       → Layers 0-3, 5-7 (needs memory, no SOUL)
  project    → Layers 0-3, 5-7 (needs memory, no SOUL)
  decision   → Layers 0-7 (full injection, with SOUL)
  emotional  → Layers 0-7 (full injection, with SOUL)
  reflection → Layers 0-7 (full injection, with SOUL)
```

---

## 6. Memory system

### Extraction pipeline

```
Conversation
  → event trigger (/exit / /reflect / every 6 turns / /memory extract)
  → _bg_extract() daemon thread (non-blocking)
  → LLM proposes candidate memories
  → pending_memories table (survives crashes)
  → user reviews: /memory accept or /memory reject
  → memories table (active, with session_id)
```

### Memory types and decay

| Type | Decay threshold | Immune? |
|---|---|---|
| identity, preference, decision | — | Yes |
| project, todo, risk | 60 days unused | No |
| context, reflection | 30 days unused | No |

Decay: importance drops by 1 per decay cycle, floor = 1.

### Patterns / Themes quality gate

Three constraints must all pass before a theme is stored:

1. Name ≤ 12 characters
2. At least 2 supporting memory links
3. Memories must span ≥ 2 distinct session IDs (falls back to ≥ 2 dates for pre-v1.2 data)

---

## 7. Security design

### 4-tier shell risk scoring

| Level | Handling | Examples |
|---|---|---|
| critical | DENY | `sudo rm -rf /`, `dd of=/dev/...`, fork bomb, `curl\|sh` |
| high | STRONG_CONFIRM | `sudo`, `shutdown`, `osascript`, recursive rm, writing shell configs |
| medium | CONFIRM | Most commands with side effects |
| low | ALLOW | `git status`, `ls`, `cat`, read-only |

### Path safety

`is_inside_vault(child, vault_path)` uses `Path.resolve() + relative_to()` to verify a path is genuinely inside the vault, blocking:

- String-based bypass
- `../` path traversal  
- Symlink escape

### Permission matrix

| Operation | Policy |
|---|---|
| Obsidian read/write/search | ALLOW (is_inside_vault verified) |
| File read / list | ALLOW |
| File write inside vault | ALLOW (after path verification) |
| File write elsewhere | CONFIRM |
| Shell low | ALLOW |
| Shell medium / high | CONFIRM / STRONG_CONFIRM |
| Shell critical | DENY |
| Skill install from URL | download → code scan → preview → `INSTALL <name>` confirmation |

---

## 8. Tech stack

```
Python 3.11+
openai >= 1.0.0         # LLM calls (OpenAI SDK-compatible)
prompt_toolkit >= 3.0.0 # Terminal input
rich >= 13.0.0          # Terminal rendering
sqlite-vec              # Vector KNN (optional, degrades gracefully)
sentence-transformers   # Local embeddings (optional, degrades gracefully)
mcp                     # MCP protocol (optional)
```

Works with any OpenAI-compatible LLM API (DeepSeek, OpenAI, Ollama, etc.).

---

## 9. Configuration structure

See `templates/archer.example.toml` for the full annotated config. Key sections:

```toml
[api]          # API key, base URL, model
[persona]      # Name, file paths (SOUL/MEMORY/COVENANT/PRESENCE)
[memory]       # DB path, context memory limit
[obsidian]     # Vault path (optional)
[critique]     # Self-critique settings
[security]     # Risk scoring toggles
[mcp]          # MCP server configuration
```

---

## 10. Known design trade-offs

### Won't do

- Web UI or server deployment — single-machine terminal, by design
- Multi-user — highly personal, not a general framework
- Auto-write SOUL.md / COVENANT.md / PRESENCE.md — user review required
- Auto-accept pending memories — all LLM-extracted memories need user approval
- Auto-apply self-critiques — observation only, not a behavior patch system

### Deferred (v1.2.1)

- Workflow layer: voice_to_journal, url_to_reading_note, weekly_digest, project_briefing
- Weekly briefing templates
- Voice input in the main REPL loop

### Active trade-offs

- `classify_query_intent()` uses keyword heuristics, not a classifier — edge cases exist
- MCP 3-condition injection (recent / server name / capability keyword) can miss a first invocation before the server is established as "recent"
- self_critiques are currently manual + user_signal only — weekly auto-critique is off by default
- Importance decay thresholds (30/60 days) are empirical — may need tuning per user

---

## 11. Questions for review

1. **Memory retrieval**: Is the hybrid search dedup strategy optimal? Any improvements for the importance decay schedule?
2. **Intent classification**: `classify_query_intent()` — better approaches that avoid a full classification model?
3. **Pattern quality**: What edge cases does the session_id+date dual gate miss that pure date gating would catch?
4. **Shell risk scoring**: What dangerous command patterns are missing from the 4-tier classification?
5. **SOUL evolution**: Is the COVENANT/PRESENCE propose-and-review flow (history only, no auto-diff-apply) the right design?
6. **MCP injection**: How should first-invocation false negatives be handled gracefully?
7. **Self-critique**: How should the `scope` mechanism extend beyond `skill_router_hint`?
