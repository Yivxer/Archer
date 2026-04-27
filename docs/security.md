# Security

## Shell command risk scoring

All shell commands are scored before execution using `score_shell_risk()`:

| Level | Action | Examples |
|-------|--------|---------|
| `low` | Allowed | `git status`, `ls`, `cat`, read-only commands |
| `medium` | Requires confirmation | Most commands with side effects |
| `high` | Requires explicit confirmation + reason | `sudo`, `shutdown`, `osascript`, recursive deletes, writing to shell config files |
| `critical` | Denied | `sudo rm -rf /`, `dd of=/dev/...`, fork bombs, `curl \| sh` |

The confirmation prompt for high-risk commands asks you to state a reason before proceeding. Critical commands cannot be executed through Archer.

## Path safety

File write operations use `is_inside_vault()` to verify that a path is genuinely inside your configured vault — using `Path.resolve()` and `relative_to()` rather than string matching.

This prevents:
- String-based bypass (a path that contains "obsidian" but isn't actually inside the vault)
- `../` path traversal
- Symlink escape

## Permission model

| Operation | Default |
|-----------|---------|
| Obsidian read/write/search | Allowed (vault paths verified with `is_inside_vault`) |
| File read / list | Allowed |
| File write to your vault | Allowed (after path verification) |
| File write to other paths | Requires confirmation |
| Shell — low risk | Allowed |
| Shell — medium/high | Requires confirmation |
| Shell — critical | Denied |
| Skill install from URL | Full review flow: download → code scan → preview → type `INSTALL <name>` to confirm |

## Confirmation dialog

Standard confirmation (medium risk):
```
  ⚠  <operation description>
  y  confirm    n  skip    q  cancel task
  →
```

Strong confirmation (high risk):
```
  🔴  <operation> (high risk)
  Risk: <reason>
  State your reason, then type YES to confirm:
  →
```

`q` cancels the entire tool chain, not just the current step.

## Skill installation

Installing a skill from an external URL goes through a staged review:

1. File is downloaded to a temp location
2. Static code scan checks for dangerous patterns
3. Full source is shown for your review
4. You must type `INSTALL <skill-name>` exactly to confirm

## What Archer cannot do

- Modify `COVENANT.md` automatically
- Accept memories without your approval
- Apply self-critiques to behavior automatically
- Bypass `DENY` decisions

## System health check

```bash
archer
/doctor
```

Runs 11 checks including path safety, vault accessibility, pending memory backlog, and risk configuration. Use `--fix` to auto-repair items that can be fixed automatically.
