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
