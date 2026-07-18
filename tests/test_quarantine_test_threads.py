from __future__ import annotations

from scripts.quarantine_test_threads import is_test_thread


def test_test_thread_markers_do_not_match_normal_user_title() -> None:
    assert is_test_thread({"title": "Journey 7 history"}) is True
    assert is_test_thread({"title": "测试对话 1"}) is True
    assert is_test_thread({"title": "Archer 上下文记忆改进"}) is False
