from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STYLES = ROOT / "client/desktop/src/renderer/src/styles.css"
BASE_CSS = ROOT / "client/desktop/src/renderer/src/styles/base.css"
WORKSPACE_CSS = ROOT / "client/desktop/src/renderer/src/styles/workspace.css"
CHAT_CSS = ROOT / "client/desktop/src/renderer/src/styles/chat.css"
SIDEBAR_CSS = ROOT / "client/desktop/src/renderer/src/styles/sidebar.css"


def test_light_theme_tokens_are_the_single_source():
    tokens = (ROOT / "client/desktop/src/renderer/src/tokens.css").read_text()
    styles = STYLES.read_text()
    base = BASE_CSS.read_text()
    workspace = WORKSPACE_CSS.read_text()
    sidebar = SIDEBAR_CSS.read_text()
    chat = CHAT_CSS.read_text()
    composer = (ROOT / "client/desktop/src/renderer/src/styles/composer.css").read_text()

    assert "--bg-1: #f7f8f9" in tokens
    assert "--bg-2: #ffffff" in tokens
    assert "--panel: #ffffff" in tokens
    assert "--panel-solid: #ffffff" in tokens
    assert "--sidebar: #ffffff" in tokens
    assert "--shadow-sm:" in tokens
    assert "--line: rgba(15, 23, 42, 0.09)" in tokens
    for name in ("--bg-1:", "--bg-2:", "--ink:", "--cyan:", "--panel:"):
        assert name not in styles

    assert "background: var(--bg-1);" in base
    assert "background: #ffffff;" not in base
    assert ".app-shell {" in base
    assert "background: var(--bg-1);" in workspace
    assert "background: #ffffff;" not in workspace
    assert "background: var(--sidebar);" in sidebar
    assert "background: var(--bg-1);" in chat

    for name in (
        "wordmark-flow",
        "organic-morph",
        "ring-living-shell",
        "ring-orbit",
        "ring-shine-drift",
        "sidebar-ring-float",
    ):
        assert name not in base
        assert name not in sidebar
    assert "conic-gradient" in base
    assert "conic-gradient" in sidebar
    assert "background: var(--cyan);" in base
    assert "conic-gradient" not in composer
    assert "background: var(--cyan);" in composer
    assert "@keyframes msg-in" in base
    assert "@keyframes dot-pulse" in base
    assert "@keyframes cb-spin" in base
    assert "@keyframes ring-spin" in base


def test_sidebar_defaults_open_and_exposes_status_footer():
    main = (ROOT / "client/desktop/src/renderer/src/main.tsx").read_text()

    assert "archer-sidebar-open" in main
    assert "sidebar-footer" in main
    assert "setProfileOpen" in main
    assert "saved === null ? true" in main


def test_chat_top_safe_area_expands_on_narrow_windows():
    chat = CHAT_CSS.read_text()
    base = BASE_CSS.read_text()

    assert "--chat-top-safe-area: 132px" in chat
    assert "--chat-left-safe-area" in chat
    assert "padding-top: var(--chat-top-safe-area)" in chat
    assert "app-shell.focus-mode .chat-layout" in chat
    assert "chat-approval-dock" in chat
    assert "--chat-left-safe-area: 188px" in chat
    assert "@media (max-width: 1120px)" in chat
    assert "--chat-top-safe-area: 144px" in chat
    assert ".app-title-tools" in base
    assert "left: 92px" in base
    assert "border-radius: 999px" in base
