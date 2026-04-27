#!/usr/bin/env bash
# Archer install script
# Sets up ~/.archer/ with default templates and installs the `archer` command.

set -euo pipefail

ARCHER_DIR="$HOME/.archer"
TEMPLATES_DIR="$(cd "$(dirname "$0")/templates" && pwd)"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"

# ── Colors ────────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC}  $*"; }
info() { echo -e "${CYAN}→${NC}  $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
err()  { echo -e "${RED}✗${NC}  $*" >&2; }

echo ""
echo "  Archer — personal terminal AI agent"
echo "  ──────────────────────────────────────"
echo ""

# ── 1. Create ~/.archer/ ──────────────────────────────────────────────────────
if [ ! -d "$ARCHER_DIR" ]; then
    mkdir -p "$ARCHER_DIR/history/covenant" "$ARCHER_DIR/history/presence"
    ok "Created $ARCHER_DIR"
else
    info "$ARCHER_DIR already exists — skipping directory creation"
fi

# ── 2. Copy templates (never overwrite existing user files) ───────────────────
copy_template() {
    local src="$1"
    local dest="$2"
    local label="$3"

    if [ -f "$dest" ]; then
        warn "$label already exists at $dest — not overwritten"
    else
        cp "$src" "$dest"
        ok "Created $dest"
    fi
}

copy_template "$TEMPLATES_DIR/SOUL.template.md"     "$ARCHER_DIR/SOUL.md"      "SOUL.md"
copy_template "$TEMPLATES_DIR/MEMORY.template.md"   "$ARCHER_DIR/MEMORY.md"    "MEMORY.md"
copy_template "$TEMPLATES_DIR/COVENANT.template.md" "$ARCHER_DIR/COVENANT.md"  "COVENANT.md"
copy_template "$TEMPLATES_DIR/PRESENCE.template.md" "$ARCHER_DIR/PRESENCE.md"  "PRESENCE.md"

# ── 3. Set up archer.toml ─────────────────────────────────────────────────────
TOML_DEST="$PROJECT_DIR/archer.toml"
if [ -f "$TOML_DEST" ]; then
    warn "archer.toml already exists — not overwritten"
    warn "Edit it manually if you need to update paths."
else
    # Substitute ~/.archer paths into the example config
    sed \
        -e "s|~/.archer/SOUL.md|$ARCHER_DIR/SOUL.md|g" \
        -e "s|~/.archer/MEMORY.md|$ARCHER_DIR/MEMORY.md|g" \
        -e "s|~/.archer/COVENANT.md|$ARCHER_DIR/COVENANT.md|g" \
        -e "s|~/.archer/PRESENCE.md|$ARCHER_DIR/PRESENCE.md|g" \
        -e "s|~/.archer/archer.db|$ARCHER_DIR/archer.db|g" \
        -e "s|~/.archer/history/covenant/|$ARCHER_DIR/history/covenant/|g" \
        -e "s|~/.archer/history/presence/|$ARCHER_DIR/history/presence/|g" \
        "$TEMPLATES_DIR/archer.example.toml" > "$TOML_DEST"
    ok "Created archer.toml (edit it to add your API key)"
fi

# ── 4. Python virtual environment ─────────────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    info "Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
    ok "Created .venv"
else
    info ".venv already exists — skipping"
fi

info "Installing Python dependencies..."
"$VENV_DIR/bin/pip" install -q -r "$PROJECT_DIR/requirements.txt"
ok "Dependencies installed"

# ── 5. Install `archer` shell command ─────────────────────────────────────────
WRAPPER="/usr/local/bin/archer"
WRAPPER_CONTENT="#!/usr/bin/env bash
exec \"$VENV_DIR/bin/python\" \"$PROJECT_DIR/archer.py\" \"\$@\""

if [ -f "$WRAPPER" ]; then
    warn "$(which archer 2>/dev/null || echo $WRAPPER) already exists"
    read -r -p "  Overwrite? [y/N] " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        echo "$WRAPPER_CONTENT" | sudo tee "$WRAPPER" > /dev/null
        sudo chmod +x "$WRAPPER"
        ok "Updated $WRAPPER"
    else
        warn "Skipped — run archer with: $VENV_DIR/bin/python $PROJECT_DIR/archer.py"
    fi
else
    echo "$WRAPPER_CONTENT" | sudo tee "$WRAPPER" > /dev/null
    sudo chmod +x "$WRAPPER"
    ok "Installed archer command to $WRAPPER"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "  ${GREEN}Installation complete.${NC}"
echo ""
echo "  Next steps:"
echo "  1. Edit archer.toml — add your API key"
echo "  2. Edit ~/.archer/SOUL.md — describe yourself"
echo "  3. Edit ~/.archer/MEMORY.md — add your current context"
echo "  4. Run: archer"
echo ""
echo "  See docs/quickstart.md for more."
echo ""
