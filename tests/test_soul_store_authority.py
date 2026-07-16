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

    assert "projectSoulStoreToAdapter" in main_source
    assert "loadAllMemory" in main_source
    assert "connectLocalApi({ silent: true })" not in main_source[main_source.index("const soulProjectionEvents"):main_source.index("return () =>", main_source.index("const soulProjectionEvents"))]
