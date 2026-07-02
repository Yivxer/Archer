def test_connector_links_distinct_memories_with_shared_explicit_tag():
    from core.connector import find_memory_connections

    connections = find_memory_connections(
        [
            {"id": 1, "content": "Archer 要先保持稳定", "type": "project", "tags": "Archer,稳定"},
            {"id": 2, "content": "写作时先抓本质", "type": "preference", "tags": "稳定,写作"},
        ]
    )

    assert len(connections) == 1
    assert connections[0].left_id == 1
    assert connections[0].right_id == 2
    assert connections[0].shared_tags == ("稳定",)
    assert connections[0].score == 0.6


def test_connector_ignores_unrelated_or_same_memory_pairs():
    from core.connector import find_memory_connections

    connections = find_memory_connections(
        [
            {"id": 1, "content": "项目", "tags": "Archer"},
            {"id": 1, "content": "重复 id", "tags": "Archer"},
            {"id": 2, "content": "运动", "tags": "健身"},
        ]
    )

    assert connections == []


def test_connector_ranks_more_shared_tags_first_and_limits_results():
    from core.connector import find_memory_connections

    connections = find_memory_connections(
        [
            {"id": 1, "content": "A", "tags": "Archer,长期,写作"},
            {"id": 2, "content": "B", "tags": "Archer,长期"},
            {"id": 3, "content": "C", "tags": "Archer"},
        ],
        limit=1,
    )

    assert len(connections) == 1
    assert (connections[0].left_id, connections[0].right_id) == (1, 2)
    assert connections[0].shared_tags == ("Archer", "长期")
    assert connections[0].score == 0.7
