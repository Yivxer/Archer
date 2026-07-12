from terminal.api.turn_receipt import MemoryExtractionScheduler, empty_reply_events, memory_compaction_events


def test_empty_reply_distinguishes_tool_activity():
    tool_events = empty_reply_events(had_tool_activity=True, trace_id="t1")
    model_events = empty_reply_events(had_tool_activity=False, trace_id="t1")
    assert tool_events[1]["failureHintEvent"]["keyword"] == "tool_executed_no_summary"
    assert model_events[1]["failureHintEvent"]["keyword"] == "model_empty_response"


def test_memory_compaction_emits_receipt_only_when_archived():
    events = memory_compaction_events(compact=lambda: {"archivedCount": 2, "summaryId": "s1"}, event_factory=lambda *args: {"args": args})
    assert events[0]["args"][1] == "memory.compact"


def test_memory_extraction_scheduler_deduplicates_live_worker():
    import threading
    release = threading.Event()
    scheduler = MemoryExtractionScheduler()
    assert scheduler.schedule([], lambda _: release.wait(1)) is True
    assert scheduler.schedule([], lambda _: None) is False
    release.set()
