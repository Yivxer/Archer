"""Guard removal of duplicate conversation snapshots without accessing user state."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "client/desktop/src/renderer/src"


def test_conversation_lists_have_one_server_projection():
    adapter_type = (ROOT / "types.ts").read_text().split("export type ArcherAdapter = {", 1)[1]
    assert "sessions: SessionItem[]" not in adapter_type
    assert "threads: ConversationThread[]" not in adapter_type
    local = (ROOT / "adapters/localArcher.ts").read_text()
    assert "safeJson('/sessions'" not in local
    assert "safeJson('/threads'" not in local
    sync = (ROOT / "lib/storeSync.ts").read_text()
    assert "mergeSessionItems" not in sync
    assert "mergeThreadItems" not in sync
    for name in ("main.tsx", "pages/ChatPage.tsx", "pages/ProjectsPage.tsx", "pages/ReviewPage.tsx"):
        source = (ROOT / name).read_text()
        assert "data.sessions" not in source
        assert "data.threads" not in source
    main = (ROOT / "main.tsx").read_text()
    assert "summarizeThreadMessages" not in main
    assert "upsertSavedSessionSnapshot" not in main
    for store in ("sessionStore.ts", "threadStore.ts"):
        assert "from '../adapters/conversationAdapter'" in (ROOT / "lib" / store).read_text()


def test_conversation_transport_preserves_http_boundary():
    adapter = (ROOT / "adapters/conversationAdapter.ts").read_text()
    assert "getJson, postJson" in adapter
    for token in ("localStorage", "sqlite", "loadLocalArcher"):
        assert token not in adapter
    assert "threadId?: string" in adapter
