import pytest


@pytest.mark.parametrize(
    ("state", "event", "expected"),
    [
        ("engaged", "user_activity", "engaged"),
        ("engaged", "idle_timeout", "idle"),
        ("engaged", "mute", "muted"),
        ("engaged", "unmute", "engaged"),
        ("idle", "user_activity", "engaged"),
        ("idle", "idle_timeout", "idle"),
        ("idle", "mute", "muted"),
        ("idle", "unmute", "idle"),
        ("muted", "user_activity", "muted"),
        ("muted", "idle_timeout", "muted"),
        ("muted", "mute", "muted"),
        ("muted", "unmute", "idle"),
    ],
)
def test_presence_state_machine_exhausts_all_state_event_pairs(state, event, expected):
    from core.presence import transition_presence

    result = transition_presence(state, event)

    assert result.state == expected


def test_presence_state_machine_normalizes_unknown_state_and_ignores_unknown_event():
    from core.presence import transition_presence

    result = transition_presence("unknown", "unrecognized")

    assert result.state == "idle"
    assert result.reason == "ignored_event"


def test_presence_state_can_be_persisted_and_explicitly_unmuted(tmp_path):
    from core.presence import get_presence_state, set_presence_state

    db_path = tmp_path / "archer.db"

    assert get_presence_state(db_path) == "idle"
    assert set_presence_state(db_path, "muted").state == "muted"
    assert get_presence_state(db_path) == "muted"
    assert set_presence_state(db_path, "idle").state == "idle"
    assert get_presence_state(db_path) == "idle"
