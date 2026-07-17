from terminal.api.session_routes import session_meta_from_payload


def test_session_route_metadata_filters_invalid_ids_and_truncates_label():
    meta = session_meta_from_payload({
        "expertId": "expert_1",
        "expertLabel": "x" * 100,
        "threadId": "../invalid",
        "modeId": "writer",
        "modeLabel": "写作",
    })

    assert meta == {
        "expertId": "expert_1",
        "expertLabel": "x" * 64,
        "modeId": "writer",
        "modeLabel": "写作",
    }
