from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_TSX = ROOT / "client/desktop/src/renderer/src/main.tsx"
BASE_CSS = ROOT / "client/desktop/src/renderer/src/styles/base.css"
CHAT_PAGE = ROOT / "client/desktop/src/renderer/src/pages/ChatPage.tsx"
CHAT_CSS = ROOT / "client/desktop/src/renderer/src/styles/chat.css"
COMPOSER_CSS = ROOT / "client/desktop/src/renderer/src/styles/composer.css"


def test_window_has_dedicated_drag_strip_above_workspace():
    assert "window-drag-strip" in MAIN_TSX.read_text()

    css = BASE_CSS.read_text()
    assert ".window-drag-strip" in css
    assert "-webkit-app-region: drag;" in css
    assert ".app-title-tools" in css
    assert "-webkit-app-region: no-drag;" in css


def test_chat_column_and_composer_share_one_width():
    css = CHAT_CSS.read_text()

    assert "--chat-column: 900px" in css
    assert "width: min(var(--chat-column), calc(100% - 40px));" in css
    assert "padding-top: var(--chat-top-safe-area)" in css
    assert "--chat-left-safe-area" in css
    assert "margin: 0 auto" in css


def test_composer_stays_compact_for_multi_window_layout():
    css = COMPOSER_CSS.read_text()

    assert "min-height: 56px" in css
    assert "min-height: 42px" in css
    assert "border-radius: 999px" in css


def test_message_actions_are_direct_buttons_not_a_dropdown_menu():
    source = CHAT_PAGE.read_text()

    assert "msg-action-more" not in source
    assert "msg-action-menu" not in source
    assert "msg-action-btn" in source
    assert "regenerateAssistantMessage" in source
    assert "RotateCcw" in source
