# Archer Sensor for Obsidian

This is a minimal local Obsidian plugin source package that sends the currently focused Markdown note to Archer Desktop.

## What It Sends

- current note path
- title
- selected text, if any
- a short content preview
- headings and tags

It does not write to Obsidian. Archer still validates that the path is inside `[obsidian].vault_path`.

## Install Locally

1. Copy this folder to:

   ```text
   <your-vault>/.obsidian/plugins/archer-sensor
   ```

2. Restart Obsidian or reload plugins.
3. Enable `Archer Sensor` in Obsidian community plugins.
4. Open plugin settings and set:

   ```text
   Archer API endpoint: http://127.0.0.1:8765
   Desktop API token: <Archer Desktop API token>
   ```

The token is required because Archer protects local API routes with `Authorization: Bearer ...`.

On the installed desktop app, the token file is usually:

```text
~/Library/Application Support/archer-desktop/security/desktop-api-token
```

## Test

Open a Markdown note in Obsidian, then run:

```text
Command Palette -> Archer Sensor: Send current note focus to Archer
```

You can verify the current focus from Archer:

```bash
curl -s -H "Authorization: Bearer <token>" \
  http://127.0.0.1:8765/sensors/status
```

## Notes

- Automatic sending happens only when opening or switching notes.
- The plugin caps preview text before sending.
- The Archer backend decides whether the path is allowed and how much context reaches chat.
