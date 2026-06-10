from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_chat_greetings_module_exports_pool():
    path = ROOT / "client/desktop/src/renderer/src/lib/chatGreetings.ts"
    # Greetings are TS — assert file content and length for pytest
    text = path.read_text()
    assert "export const CHAT_GREETINGS" in text
    assert text.count("'") >= 20
    assert "pickChatGreeting" in text
