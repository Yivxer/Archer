from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "client/desktop/src/renderer/src/main.tsx"
MEMORY_PAGE = ROOT / "client/desktop/src/renderer/src/pages/MemoryPage.tsx"
REVIEW_PAGE = ROOT / "client/desktop/src/renderer/src/pages/ReviewPage.tsx"


def test_memory_consumers_use_memory_store_instead_of_direct_adapter_actions():
    main_source = MAIN.read_text()
    memory_source = MEMORY_PAGE.read_text()
    review_source = REVIEW_PAGE.read_text()

    assert "from '../lib/memoryStore'" in memory_source
    assert "useMemoryStore" in memory_source
    assert "resolvePendingMemoryAction" in memory_source
    assert "batchResolvePendingMemoryAction" in memory_source
    assert "updateMemoryAction" in memory_source
    assert "from '../adapters/localArcher'" not in memory_source

    assert "from '../lib/memoryStore'" in review_source
    assert "useMemoryStore" in review_source
    assert "resolvePendingMemoryAction" in review_source
    assert "from '../adapters/localArcher'" not in review_source

    assert "onMemoryItemsChange" not in main_source
    assert "patchMemoryItems" not in main_source


def test_memory_domain_owns_loading_without_snapshot_injection_or_projection():
    root = ROOT / "client/desktop/src/renderer/src"
    main = (root / "main.tsx").read_text()
    sync = (root / "lib/storeSync.ts").read_text()
    store = (root / "lib/memoryStore.ts").read_text()
    page = (root / "pages/MemoryPage.tsx").read_text()
    settings = (root / "pages/SettingsPage.tsx").read_text()
    local = (root / "adapters/localArcher.ts").read_text()
    adapter = (root / "adapters/memoryAdapter.ts").read_text()
    types = (root / "types.ts").read_text().split("export type ArcherAdapter = {", 1)[1]
    for token in ("projectMemoryStoreToAdapter", "mergeMemoryItems", "adapter.memory"):
        assert token not in sync and token not in main and token not in store
    assert "memory: MemoryItem[]" not in types
    assert "/memory?include_rejected=true" not in local
    assert "from '../adapters/memoryAdapter'" in store
    assert "ArcherAdapter" not in page and "data." not in page
    assert "useMemoryStore" in main and "useMemoryStore" in settings
    assert "data.memory" not in main and "data.memory" not in settings
    for endpoint in ("/memory?include_rejected=true", "/memory/stats", "/memory/groups", "/memory/update", "/memory/evolve"):
        assert endpoint in adapter
    for token in ("localStorage", "sqlite", "loadLocalArcher"):
        assert token not in adapter
