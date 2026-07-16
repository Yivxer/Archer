from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT_PAGE = ROOT / "client/desktop/src/renderer/src/pages/ChatPage.tsx"
ADAPTER = ROOT / "client/desktop/src/renderer/src/adapters/localArcher.ts"


def test_chat_profile_selection_projects_server_settings_only():
    chat_source = CHAT_PAGE.read_text()
    adapter_source = ADAPTER.read_text()

    assert "const activeModelProfile = data.settings.activeProfile || 'lite'" in chat_source
    assert "setSelectedModel" not in chat_source
    assert "useState<'lite' | 'pro' | 'max'>(data.settings.activeProfile" not in chat_source
    assert "settings.activeProfile !== profileId" in adapter_source
    assert "await onRefresh?.()" in chat_source
