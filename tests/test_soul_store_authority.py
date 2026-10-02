from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "client/desktop/src/renderer/src/main.tsx"
SOUL_PAGE = ROOT / "client/desktop/src/renderer/src/pages/SoulPage.tsx"


def test_soul_page_uses_soul_store_and_cross_memory_projection_is_domain_scoped():
    main_source = MAIN.read_text()
    soul_source = SOUL_PAGE.read_text()

    assert "from '../lib/soulStore'" in soul_source
    assert "useSoulStore" in soul_source
    assert "importSoulAction" in soul_source
    assert "loadAllSoul" in soul_source
    assert "from '../adapters/localArcher'" not in soul_source
    assert "onRefresh" not in soul_source

    assert "projectSoulStoreToAdapter" not in main_source
    assert "getSoulStoreState" not in main_source
    assert "loadAllSoul()" in main_source
    assert "ArcherAdapter" not in soul_source
    assert "data." not in soul_source
    assert "connected={apiState === 'connected'}" in main_source
    assert "loadAllMemory" in main_source
    events = main_source[main_source.index("const soulMemoryEvents"):main_source.index("return () =>", main_source.index("const soulMemoryEvents"))]
    assert "connectLocalApi" not in events


def test_soul_domain_cannot_be_loaded_or_projected_by_compatibility_snapshots():
    source_root = ROOT / "client/desktop/src/renderer/src"
    local = (source_root / "adapters/localArcher.ts").read_text()
    sync = (source_root / "lib/storeSync.ts").read_text()
    store = (source_root / "lib/soulStore.ts").read_text()
    types = (source_root / "types.ts").read_text().split("export type ArcherAdapter = {", 1)[1]
    review = (source_root / "pages/ReviewPage.tsx").read_text()
    adapter = (source_root / "adapters/soulAdapter.ts").read_text()

    for token in ("soulProfile", "soulFiles", "/soul-profile", "/soul-files"):
        assert token not in local
        assert token not in sync
        assert token not in types
    assert "mergeSoul" not in store
    assert "from '../adapters/soulAdapter'" in store
    assert "useSoulStore" in review and "data.soulProfile" not in review
    for endpoint in ("/soul-profile", "/soul-files", "/vault/reflection/recent", "/soul/import"):
        assert endpoint in adapter
    for token in ("localStorage", "sqlite", "mergeSoul", "loadLocalArcher"):
        assert token not in adapter
