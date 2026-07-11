from __future__ import annotations

from terminal.api.turn_pipeline import classify_turn


def test_classify_turn_separates_current_user_message_from_history():
    calls = []

    def classifier(query, *, history, llm_fallback):
        calls.append((query, history, llm_fallback))
        return {"intent": "chat", "needs_memory": False, "needs_tools": False}

    result = classify_turn(
        [
            {"role": "system", "content": "thread context"},
            {"role": "user", "content": "earlier"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "continue"},
        ],
        classifier=classifier,
    )

    assert result.query == "continue"
    assert result.prior_history[-1] == {"role": "assistant", "content": "answer"}
    assert calls == [("continue", result.prior_history, False)]
    assert result.intent_info["intent"] == "chat"


def test_classify_turn_uses_latest_user_even_when_history_ends_with_assistant():
    result = classify_turn(
        [
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "answer"},
        ],
        classifier=lambda query, **_: {
            "intent": "chat",
            "query": query,
            "needs_memory": False,
            "needs_tools": False,
        },
    )

    assert result.query == "question"
    assert len(result.prior_history) == 2
