# Command Reference

## Conversation management

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/status` | Model, mode, token usage, active project, soul proposals |
| `/mode <mirror\|coach\|critic\|operator>` | Switch conversation mode (persisted to toml) |
| `/model [<name>]` | View or switch the active LLM model |
| `/reflect` | Structured reflection on the current session (JSON output, stays in history) |
| `/listen [stop]` | Silent recording mode — notes are saved, no LLM response triggered |
| `/sessions [days]` | Session history statistics |
| `/save` | Explicitly save current session |
| `/clear` | Clear conversation history (starts fresh) |
| `/compact` | Summarize and compress current history |
| `/exit` | Exit Archer (saves session, runs background extraction) |

## Memory system

| Command | Description |
|---------|-------------|
| `/memory list` | List all active memories |
| `/memory search <term>` | Hybrid search (vector + full-text) |
| `/memory add <content>` | Manually add a memory |
| `/memory pending` | View memories proposed by Archer, awaiting your review |
| `/memory accept [ID\|all]` | Accept proposed memories |
| `/memory reject [ID\|all]` | Reject proposed memories |
| `/memory update <ID> <content>` | Update an existing memory |
| `/memory archive <ID>` | Archive (soft-delete) a memory |
| `/memory delete <ID>` | Permanently delete |
| `/memory review` | Health check — flags duplicates, conflicts, stale entries |
| `/memory extract` | Manually trigger background extraction |
| `/memory reindex` | Rebuild vector index |

## Soul system

| Command | Description |
|---------|-------------|
| `/soul list` | View pending SOUL.md evolution proposals |
| `/soul accept <ID\|all>` | Accept — appends to SOUL.md |
| `/soul reject <ID\|all>` | Discard proposal |
| `/soul view` | View recent SOUL.md evolution history |
| `/covenant view` | View your COVENANT.md |
| `/covenant propose <text>` | Propose a covenant change (saved to history, not auto-applied) |
| `/presence view` | View your PRESENCE.md |
| `/presence suggest <text>` | Suggest a presence change (saved to history, not auto-applied) |

## Self-critique system

| Command | Description |
|---------|-------------|
| `/critique list` | View all critique records (open / dismissed) |
| `/critique add` | Manually add a critique observation (min 30 chars) |
| `/critique dismiss <ID>` | Dismiss a critique |

## Themes

| Command | Description |
|---------|-------------|
| `/themes` | List detected behavior themes |
| `/themes detect` | Run pattern detection across memory |
| `/themes <ID>` | View theme details and linked memories |

## Projects

| Command | Description |
|---------|-------------|
| `/project list` | List all projects |
| `/project new <name> [description]` | Create a project |
| `/project use <ID\|name>` | Set active project (auto-injected into context) |
| `/project log <ID\|name> <content>` | Log a project event |
| `/project status <ID\|name>` | View project details |
| `/project archive <ID\|name>` | Archive a project |

## Automation

| Command | Description |
|---------|-------------|
| `/cron list` | List scheduled tasks |
| `/cron add <interval> <task>` | Add a task (daily / weekly / monthly / Nh) |
| `/cron del <ID>` | Remove a scheduled task |
| `/cron run <ID>` | Run a task immediately |

## Skills

| Command | Description |
|---------|-------------|
| `/skill list` | List installed skills |
| `/skill info <name>` | Skill details and schema |
| `/skill install <path\|URL>` | Install from local path or GitHub URL |
| `/skill remove <name>` | Uninstall |

## System

| Command | Description |
|---------|-------------|
| `/doctor [--fix]` | System health check (11 items); `--fix` auto-repairs what it can |

## Input shortcuts

| Action | Shortcut |
|--------|----------|
| Send message | `Enter` |
| New line | `Option+Enter` (macOS) / `Alt+Enter` |
| Attach file | `@/path/to/file` or `@~/path` |
| Attach file with spaces | `@"path with spaces"` |
| Command completion | `Tab` after `/` |
| Exit | `Ctrl+C` |
