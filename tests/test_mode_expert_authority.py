from pathlib import Path

from terminal.api.profile_routes import _available_experts, _available_modes


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "client/desktop/src/renderer/src/main.tsx"
CHAT = ROOT / "client/desktop/src/renderer/src/pages/ChatPage.tsx"
SETTINGS = ROOT / "client/desktop/src/renderer/src/pages/SettingsPage.tsx"


def test_unknown_mode_and_expert_project_safe_server_fallbacks():
    config = {
        "persona": {
            "mode_auto": False,
            "current_mode": "removed-mode",
            "current_expert": "removed-expert",
        },
    }

    modes = _available_modes(config)
    experts = _available_experts(config)

    assert modes["current"] == "auto"
    assert modes["fallbackApplied"] is True
    assert experts["current"] == "default"
    assert experts["fallbackApplied"] is True


def test_valid_builtin_mode_remains_server_authoritative_without_mode_directory():
    modes = _available_modes({
        "persona": {
            "mode_auto": False,
            "current_mode": "writer",
            "default_mode": "listener",
        },
    })

    assert modes["current"] == "writer"
    assert modes["modeAuto"] is False
    assert modes["fallbackApplied"] is False
    assert next(item for item in modes["modes"] if item["id"] == "writer")["active"] is True


def test_desktop_does_not_persist_mode_or_optimistically_own_expert():
    main = MAIN.read_text(encoding="utf-8")
    chat = CHAT.read_text(encoding="utf-8")
    settings = SETTINGS.read_text(encoding="utf-8")

    assert "archer-conversation-mode" not in main
    assert "localExpertId" not in chat
    assert "setConversationMode" not in settings
    assert "data.modes.current || data.status.mode || 'auto'" in settings
    assert "expertWorkbenchRequestRef" in main


def test_session_save_and_restore_carry_server_mode_and_expert_identity():
    main = MAIN.read_text(encoding="utf-8")
    chat = CHAT.read_text(encoding="utf-8")

    assert "modeId," in chat
    assert "modeLabel:" in chat
    assert "detail.modeId" in main
    assert "await switchLocalMode(detail.modeId)" in main
