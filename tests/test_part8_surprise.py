def test_surprise_turns_strong_unseen_connection_into_explainable_draft():
    from core.connector import MemoryConnection
    from core.surprise import propose_surprise

    draft = propose_surprise(
        MemoryConnection(left_id=1, right_id=2, shared_tags=("Archer", "长期"), score=0.7)
    )

    assert draft is not None
    assert draft.connection_key == "1:2"
    assert "Archer" in draft.message
    assert "长期" in draft.message


def test_surprise_ignores_weak_or_already_seen_connection():
    from core.connector import MemoryConnection
    from core.surprise import propose_surprise

    weak = MemoryConnection(left_id=1, right_id=2, shared_tags=("Archer",), score=0.6)
    seen = MemoryConnection(left_id=3, right_id=4, shared_tags=("写作", "长期"), score=0.7)

    assert propose_surprise(weak) is None
    assert propose_surprise(seen, seen_connection_keys={"3:4"}) is None


def test_surprise_uses_stable_key_for_reversed_connection_ids():
    from core.connector import MemoryConnection
    from core.surprise import propose_surprise

    draft = propose_surprise(
        MemoryConnection(left_id=9, right_id=2, shared_tags=("稳定", "复盘"), score=0.7)
    )

    assert draft is not None
    assert draft.connection_key == "2:9"
