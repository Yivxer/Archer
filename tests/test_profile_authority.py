from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT_PAGE = ROOT / "client/desktop/src/renderer/src/pages/ChatPage.tsx"
SETTINGS_STORE = ROOT / "client/desktop/src/renderer/src/lib/settingsStore.ts"


def test_chat_profile_selection_projects_server_settings_only():
    chat_source = CHAT_PAGE.read_text()
    store_source = SETTINGS_STORE.read_text()

    assert "const activeModelProfile = settings?.activeProfile" in chat_source
    assert "useSettingsStore" in chat_source
    assert "data.settings" not in chat_source
    assert "setSelectedModel" not in chat_source
    assert "useState<'lite' | 'pro' | 'max'>(data.settings.activeProfile" not in chat_source
    assert "settings.activeProfile !== profileId" in store_source
    assert "await onRefresh?.()" in chat_source


def test_settings_snapshot_has_one_owner_and_preview_is_separate():
    renderer = ROOT / "client/desktop/src/renderer/src"
    adapter = (renderer / "adapters/localArcher.ts").read_text()
    main = (renderer / "main.tsx").read_text()
    settings_page = (renderer / "pages/SettingsPage.tsx").read_text()
    types = (renderer / "types.ts").read_text()
    mock = (renderer / "adapters/mockArcher.ts").read_text()
    assert "'/settings'" not in adapter
    assert "settings: SettingsDraft" not in types
    assert "settings:" not in mock
    assert "data.settings" not in settings_page
    assert "current.settings" not in main
    assert "saveSettings(submitted)" in settings_page
    assert "savedSettings: readConfirmedSettings" in settings_page
    assert "resetSettingsStore()" in main
