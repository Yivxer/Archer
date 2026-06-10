from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT_PAGE = ROOT / "client/desktop/src/renderer/src/pages/ChatPage.tsx"
CHAT_CSS = ROOT / "client/desktop/src/renderer/src/styles/chat.css"


def test_chat_page_rotates_home_greetings():
    source = CHAT_PAGE.read_text()
    greetings = (ROOT / "client/desktop/src/renderer/src/lib/chatGreetings.ts").read_text()

    assert "pickChatGreeting" in source
    assert "homeGreeting" in source
    assert "CHAT_GREETINGS" in greetings
    assert "想说点什么？" in greetings
    assert "我在，慢慢说。" in greetings


def test_chat_page_offers_lightweight_conversation_starters():
    source = CHAT_PAGE.read_text()

    assert "CHAT_STARTERS" in source
    assert "先听我说" in source
    assert "setDraft(starter.prompt)" in source
    assert "有点卡住" in source
    assert "轻轻复盘" in source
    assert "继续那条线" in source


def test_chat_page_pins_approval_cards_above_composer():
    source = CHAT_PAGE.read_text()

    assert "chat-approval-dock" in source
    assert "approvalToolEvents" in source
    assert "defaultExpanded={event.name === 'hugo_blog'}" in source


def test_chat_styles_keep_conversation_chrome_quiet():
    css = CHAT_CSS.read_text()

    assert ".home-subtitle" in css
    assert "background: transparent;" in css
    assert "padding: 2px 0 0;" in css
    assert ".starter-row" in css
