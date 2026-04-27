# Installation

## Requirements

- Python 3.11 or later
- macOS (Linux should work; Windows is untested)
- An API key from any OpenAI-compatible LLM provider

## Automated install

```bash
git clone https://github.com/your-username/archer.git
cd archer
bash install.sh
```

The script will:

1. Create `~/.archer/` and copy template files (SOUL, MEMORY, COVENANT, PRESENCE)
2. Generate `archer.toml` with paths pre-filled
3. Create a Python virtualenv at `.venv/`
4. Install Python dependencies from `requirements.txt`
5. Install the `archer` command to `/usr/local/bin/` (requires sudo)

If any of your `~/.archer/` files already exist, the script will not overwrite them — it will warn you and skip.

## Manual install

```bash
cd archer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Set up config
cp templates/archer.example.toml archer.toml

# Set up soul files
mkdir -p ~/.archer
cp templates/SOUL.template.md     ~/.archer/SOUL.md
cp templates/MEMORY.template.md   ~/.archer/MEMORY.md
cp templates/COVENANT.template.md ~/.archer/COVENANT.md
cp templates/PRESENCE.template.md ~/.archer/PRESENCE.md

# Edit config
open archer.toml   # fill in your API key and correct paths
```

## Configuration

Edit `archer.toml` after installation. The minimum required fields are:

```toml
[api]
api_key  = "sk-your-key-here"
base_url = "https://api.deepseek.com/v1"   # or any OpenAI-compatible URL
model    = "deepseek-chat"

[persona]
soul_path     = "/Users/you/.archer/SOUL.md"
memory_path   = "/Users/you/.archer/MEMORY.md"
covenant_path = "/Users/you/.archer/COVENANT.md"
presence_path = "/Users/you/.archer/PRESENCE.md"

[memory]
db_path = "/Users/you/.archer/archer.db"
```

See `templates/archer.example.toml` for the full list of options.

## Optional dependencies

### Vector search (recommended)

Enables semantic memory retrieval. Without it, Archer falls back to full-text search.

```bash
pip install sentence-transformers sqlite-vec
```

The embedding model (~120MB) is downloaded on first use and cached locally.

### MCP tool servers

Enables connecting external tool servers via the Model Context Protocol.

```bash
pip install mcp
```

Then add servers to `archer.toml`:

```toml
[mcp]
enabled = true

[[mcp.servers]]
name    = "fetch"
command = "uvx"
args    = ["mcp-server-fetch"]
```

## Updating

```bash
git pull
pip install -r requirements.txt
```

Your `~/.archer/` files and `archer.toml` are not affected by updates.

## Uninstalling

```bash
sudo rm /usr/local/bin/archer
rm -rf .venv
# Optionally: rm -rf ~/.archer
```
