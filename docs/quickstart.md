# Quickstart

This guide walks through your first session with Archer.

## Before you start

Make sure you've completed [installation](install.md). You should have:

- `archer.toml` with your API key filled in
- `~/.archer/SOUL.md` (at minimum — even a blank one works)

## Start Archer

```bash
archer
```

You'll see a welcome screen and a prompt (`❯`). Type anything to begin.

## First things to do

### 1. Fill in your soul file

The more you put in `~/.archer/SOUL.md`, the more Archer can adapt to you. Open it in any editor:

```bash
open ~/.archer/SOUL.md
```

You don't need to fill everything at once. Start with your values and one or two patterns you've noticed about yourself.

### 2. Add some context

`~/.archer/MEMORY.md` is where you tell Archer what's happening in your life right now — active projects, current focus, open questions. Update it whenever things change significantly.

### 3. Try a few things

**Ask for advice on a decision:**
```
I'm trying to decide whether to take on a new client. The money is good but it feels like a distraction.
```

**Start a project:**
```
/project new "side project" figuring out what to build next
```

**Reflect on a session:**
```
/reflect
```

**Check your memory:**
```
/memory list
```

## Conversation modes

Switch with `/mode`:

| Mode | Behavior |
|------|---------|
| `coach` | Pushes toward action, asks "what next?" |
| `mirror` | Only asks questions, no advice |
| `critic` | Challenges your assumptions |
| `operator` | Concise, task-focused, no extras |

## After your first session

When you exit (`/exit` or Ctrl+C), Archer runs background memory extraction — it reads the conversation and proposes things to remember.

Next time you start, check:

```
/memory pending
```

Review the proposals and accept or reject them:

```
/memory accept all
/memory reject 3
```

Only accepted memories persist long-term.

## Tips

- Use `@/path/to/file` to attach any local file to your message (text, PDF, image)
- `/doctor` runs a health check if something seems off
- `/status` shows current model, token usage, and active project
- `/help` shows all commands
