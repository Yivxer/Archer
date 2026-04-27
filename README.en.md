# Archer — Personal Terminal AI Agent

A local-first, deeply personal AI agent that runs in your terminal.

Archer is built around a simple premise: **your AI should know you**, not just your current message. It maintains long-term memory, learns your patterns over time, and can be given a "soul" — a set of values and preferences that shape how it thinks and responds.

Everything personal (your soul file, your memory, your config, your data) stays on your machine. Nothing is sent anywhere except your own LLM API calls.

---

## What makes Archer different

- **Persistent memory** — Archer remembers things across sessions, using SQLite + vector search
- **Soul system** — you give Archer a `SOUL.md` describing who you are; Archer uses it when helping with decisions or emotional topics
- **Covenant & Presence** — you define hard limits (`COVENANT.md`) and interaction style (`PRESENCE.md`); Archer never auto-modifies these
- **18 built-in skills** — shell, file ops, Obsidian integration, web fetch, PDF, OCR, GitHub, RSS, and more
- **Plugin skills** — install third-party skills from local files or GitHub URLs
- **MCP support** — connect external tool servers via the Model Context Protocol
- **4-tier shell safety** — all shell commands are risk-scored before execution
- **Works with any OpenAI-compatible API** — DeepSeek, OpenAI, local models via Ollama, etc.

---

## Your files, your data

Archer does not ship with any author's personal data. The following files are **yours to create**:

| File | Purpose |
|------|---------|
| `SOUL.md` | Who you are — values, patterns, how you work best |
| `MEMORY.md` | Where you are now — active projects, current focus |
| `COVENANT.md` | Hard limits on Archer's behavior |
| `PRESENCE.md` | Archer's interaction style with you |
| `archer.toml` | API keys and paths (never committed) |

Templates for all of these are in `templates/`. The installer copies them to `~/.archer/` to get you started.

---

## Requirements

- Python 3.11+
- macOS (Linux should work, Windows untested)
- An API key for any OpenAI-compatible LLM provider

Optional (for vector search):
- `sentence-transformers` — semantic memory retrieval
- `sqlite-vec` — vector KNN storage

Optional (for MCP tools):
- `mcp` Python package

---

## Installation

```bash
git clone https://github.com/Yivxer/Archer.git
cd Archer
bash install.sh
```

The installer will:
1. Create `~/.archer/` with template soul/memory/covenant/presence files
2. Create `archer.toml` with paths pre-filled (you add your API key)
3. Set up a Python virtualenv and install dependencies
4. Install the `archer` command to `/usr/local/bin/`

Then edit `archer.toml` to add your API key, and start filling in `~/.archer/SOUL.md`.

### Manual setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp templates/archer.example.toml archer.toml
# Edit archer.toml, then:
python archer.py
```

---

## Quick start

```
$ archer

  ◜──────────────────────◝
  ◜   Archer · ready     ◝
  ◟──────────────────────◞

❯ 
```

Type anything to start. Use `/help` to see all commands.

See [docs/quickstart.md](docs/quickstart.md) for a guided introduction.

---

## Core commands

```
/help                    show all commands
/status                  current model, mode, token usage, active project
/mode coach|mirror|critic|operator   switch conversation mode
/memory list|search|add  manage long-term memory
/soul list|accept|reject manage SOUL evolution proposals
/covenant view|propose   view or propose changes to COVENANT
/presence view|suggest   view or suggest changes to PRESENCE
/project list|new|use    manage projects
/reflect                 structured reflection on the current session
/doctor [--fix]          system health check
/skill list|install      manage skills
```

---

## Supported LLM providers

Any OpenAI-compatible API works. Set `base_url` and `api_key` in `archer.toml`:

```toml
[api]
base_url = "https://api.deepseek.com/v1"
api_key  = "sk-..."
model    = "deepseek-chat"
```

Examples:
- **DeepSeek**: `https://api.deepseek.com/v1`
- **OpenAI**: `https://api.openai.com/v1`
- **Ollama** (local): `http://localhost:11434/v1`
- **Together AI**, **Groq**, **Mistral**: use their OpenAI-compatible endpoints

---

## Privacy

Archer is local-first by design:

- All memory is stored in `~/.archer/archer.db` (SQLite, on your machine)
- Soul, memory, covenant, and presence files stay on your disk
- The only network requests are your LLM API calls
- Sessions are stored as JSON files in `~/.archer/sessions/`
- Nothing is sent to any Archer server (there isn't one)

See [docs/privacy.md](docs/privacy.md) for details.

---

## Security

Shell commands are risk-scored before execution:

| Level | Action |
|-------|--------|
| low | allowed |
| medium / high | requires confirmation |
| critical | denied |

File writes to paths outside your vault require explicit confirmation. See [docs/security.md](docs/security.md).

---

## Writing a custom skill

```python
SKILL = {
    "name": "my_skill",
    "description": "Does something useful",
    "version": "1.0.0",
}

def schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "my_skill",
            "description": "Does something useful",
            "parameters": {
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": "The input"}
                },
                "required": ["input"],
            },
        },
    }

def run(args: dict) -> str:
    return f"Result: {args['input']}"
```

Install with `/skill install /path/to/my_skill.py`.

---

## Docs

- [docs/install.md](docs/install.md) — detailed installation
- [docs/quickstart.md](docs/quickstart.md) — first session walkthrough
- [docs/commands.md](docs/commands.md) — full command reference
- [docs/memory-system.md](docs/memory-system.md) — how memory works
- [docs/soul-system.md](docs/soul-system.md) — soul, covenant, presence
- [docs/security.md](docs/security.md) — security model
- [docs/privacy.md](docs/privacy.md) — privacy details

中文主文档见 [README.md](README.md)。

---

## License

MIT
