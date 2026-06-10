from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STYLES = ROOT / "client/desktop/src/renderer/src/styles.css"
BASE_CSS = ROOT / "client/desktop/src/renderer/src/styles/base.css"
WORKSPACE_CSS = ROOT / "client/desktop/src/renderer/src/styles/workspace.css"
CHAT_CSS = ROOT / "client/desktop/src/renderer/src/styles/chat.css"
SIDEBAR_CSS = ROOT / "client/desktop/src/renderer/src/styles/sidebar.css"


def test_light_theme_uses_unified_white_workspace_backgrounds():
    styles = STYLES.read_text()
    base = BASE_CSS.read_text()
    workspace = WORKSPACE_CSS.read_text()
    sidebar = SIDEBAR_CSS.read_text()

    assert "--bg-1: #ffffff" in styles
    assert "--panel: #ffffff" in styles
    assert "--panel-solid: #ffffff" in styles
    assert "body {\n  background: #ffffff;" in base
    assert ".app-shell {" in base
    assert "background: #ffffff;" in base
    assert "background: #ffffff;" in workspace
    assert "background: #ffffff;" in sidebar


def test_sidebar_defaults_open_and_exposes_status_footer():
    main = (ROOT / "client/desktop/src/renderer/src/main.tsx").read_text()

    assert "archer-sidebar-open" in main
    assert "sidebar-footer" in main
    assert "setProfileOpen" in main
    assert "saved === null ? true" in main


def test_chat_top_safe_area_expands_on_narrow_windows():
    chat = CHAT_CSS.read_text()
    base = BASE_CSS.read_text()

    assert "--chat-top-safe-area: 96px" in chat
    assert "--chat-left-safe-area" in chat
    assert "padding-top: var(--chat-top-safe-area)" in chat
    assert "app-shell.focus-mode .chat-layout" in chat
    assert "--chat-left-safe-area: 176px" in chat
    assert "@media (max-width: 1120px)" in chat
    assert "--chat-top-safe-area: 104px" in chat
    assert ".app-title-tools" in base
    assert "left: 92px" in base
    assert "border-radius: 999px" in base
