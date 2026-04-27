# Privacy

## Local-first design

Archer is designed so your personal data never leaves your machine, except for the LLM API calls you make to your chosen provider.

**What stays local:**

| Data | Location |
|------|---------|
| Long-term memories | `~/.archer/archer.db` (SQLite) |
| Soul archive | `~/.archer/SOUL.md` |
| Memory snapshot | `~/.archer/MEMORY.md` |
| Covenant | `~/.archer/COVENANT.md` |
| Presence style | `~/.archer/PRESENCE.md` |
| Session transcripts | `~/.archer/sessions/` |
| Artifacts | `.artifacts/` in the project directory |
| Configuration | `archer.toml` (in project directory, gitignored) |

None of these files are transmitted to any Archer server. There is no Archer server.

## What does leave your machine

**LLM API calls.** When you send a message, Archer sends:

- Your message
- Conversation history (compressed if approaching token limits)
- Relevant memories retrieved from your local database
- Summaries of your soul/memory/covenant/presence files (when relevant to the query)
- Skill schemas (for function calling)

This data is sent to whichever LLM API you've configured (`api.base_url` in `archer.toml`). It is subject to that provider's privacy policy.

**Embedding calls.** If you've installed `sentence-transformers`, memory embeddings are computed **locally** — no API call is made. The model runs on your machine.

## Git hygiene

The following are gitignored by default and will never be committed:

```
.env
archer.toml
SOUL.md
MEMORY.md
COVENANT.md
PRESENCE.md
*.db
sessions/
.artifacts/
```

If you fork or contribute to Archer, your personal data cannot accidentally be included in a commit.

## No telemetry

Archer collects no usage data, crash reports, or analytics. There is no built-in tracking of any kind.

## Third-party skills

Skills installed from external sources may make their own network calls. Review skill source code before installing. The skill installer shows you the full source before confirming.

## LLM provider choice

You choose your provider. If privacy is critical:
- Run a local model via Ollama (`http://localhost:11434/v1`)
- Use a provider with a strong data retention policy
- Review your provider's terms before using Archer with sensitive personal data
