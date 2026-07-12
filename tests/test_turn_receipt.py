from terminal.api.turn_receipt import empty_reply_events


def test_empty_reply_distinguishes_tool_activity():
    tool_events = empty_reply_events(had_tool_activity=True, trace_id="t1")
    model_events = empty_reply_events(had_tool_activity=False, trace_id="t1")
    assert tool_events[1]["failureHintEvent"]["keyword"] == "tool_executed_no_summary"
    assert model_events[1]["failureHintEvent"]["keyword"] == "model_empty_response"
