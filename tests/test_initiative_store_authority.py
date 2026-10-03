"""Desktop observation has one owner and preserves server delivery policy."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "client/desktop/src/renderer/src"


def test_overall_adapter_and_sse_cannot_backfill_initiative_reports() -> None:
    for relative in ("adapters/localArcher.ts", "adapters/mockArcher.ts", "lib/brainConnection.ts"):
        assert "initiativeShadow:" not in (ROOT / relative).read_text()
    main = (ROOT / "main.tsx").read_text()
    assert "syncStoresFromAdapter" not in main
    assert "mergeInitiativeShadowEvent" not in main
    assert "mergeSseInitiativeEvent(event)" in main
    store = (ROOT / "lib/initiativeStore.ts").read_text()
    assert "api.fetchInitiativeReview()" in store
    assert "await loadAllInitiative({ force: true })" in store
    assert "generation !== loadGeneration" in store
    assert "epoch !== resetGeneration" in store


def test_pages_gate_actions_on_domain_readiness_and_skip_overall_refresh() -> None:
    hook = (ROOT / "lib/useShadowFeedback.ts").read_text()
    assert "loadState === 'ready' && !storeBusy" in hook
    assert "await onRefresh" not in hook
    assert "await onRefresh" not in (ROOT / "components/ThreadClueActions.tsx").read_text()
    today = (ROOT / "pages/TodayPage.tsx").read_text()
    assert "const canManage = feedback.canControl" in today
    assert "disabled={!canManage" in today
    workspace = (ROOT / "components/WorkspaceContextPanel.tsx").read_text()
    assert "canControl={shadowFeedback.canControl}" in workspace
    adapter = (ROOT / "adapters/initiativeAdapter.ts").read_text()
    assert "Promise.all" in adapter
    assert "part.ok !== true" in adapter
    assert "getJson, postJson" in adapter
    assert "localStorage" not in adapter
