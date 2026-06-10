from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_TSX = ROOT / "client/desktop/src/renderer/src/main.tsx"
MEMORY_PAGE = ROOT / "client/desktop/src/renderer/src/pages/MemoryPage.tsx"
SETTINGS_PAGE = ROOT / "client/desktop/src/renderer/src/pages/SettingsPage.tsx"
SIDEBAR_CSS = ROOT / "client/desktop/src/renderer/src/styles/sidebar.css"


def test_mock_memory_preview_is_not_actionable_review():
    source = MEMORY_PAGE.read_text()

    assert "const isLocalAdapter = data.status.adapter === 'local'" in source
    assert "const canResolveMemory = isLocalAdapter" in source
    assert "memory-preview-note" in source
    assert "连接本地 API 后才能确认或拒绝真实记忆" in source
    assert "canResolveMemory && pending.length > 0" in source
    assert "canResolveMemory && item.status === 'pending' ? resolveMemory : undefined" in source


def test_mock_proactive_banner_is_hidden_and_api_error_can_be_dismissed():
    source = MAIN_TSX.read_text()

    assert "apiBannerDismissed" in source
    assert "setApiBannerDismissed(true)" in source
    assert "隐藏连接提示" in source
    assert "memoryTouchCount" in source
    assert "sidebar-nav-badge" in source
    assert "ProactiveTouchBanner" not in source
    assert "本地 API 未连接" in source
    assert "需要启动本地 API" in source


def test_settings_page_uses_specific_local_api_copy():
    source = SETTINGS_PAGE.read_text()

    assert "本地 API 未连接" in source
    assert "当前可继续使用预览模式" not in source


def test_proactive_touch_is_shown_on_memory_nav_not_chat_canvas():
    main_source = MAIN_TSX.read_text()
    sidebar_css = SIDEBAR_CSS.read_text()

    assert "target === 'Memory'" in main_source
    assert "touchCount" in main_source
    assert ".sidebar-nav-badge" in sidebar_css
    assert "proactive-touch" not in main_source
