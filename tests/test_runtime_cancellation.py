from __future__ import annotations

import threading

from core.runtime_cancellation import CancellationRegistry, CancellationToken
from core.tool_runtime import invoke
from skills import obsidian_write


def test_cancellation_before_guard_prevents_side_effect() -> None:
    token = CancellationToken()
    token.request()

    with token.side_effect_guard() as allowed:
        assert allowed is False

    assert token.requested is True
    assert token.effect_started is False
    assert token.effect_finished is False


def test_cancellation_during_guard_marks_late_effect() -> None:
    token = CancellationToken()
    entered = threading.Event()
    release = threading.Event()

    def execute() -> None:
        with token.side_effect_guard() as allowed:
            assert allowed is True
            entered.set()
            release.wait(timeout=2)

    worker = threading.Thread(target=execute)
    worker.start()
    assert entered.wait(timeout=2)
    token.request()
    release.set()
    worker.join(timeout=2)

    assert token.requested is True
    assert token.effect_started is True
    assert token.effect_finished is True


def test_registry_reuses_token_until_release() -> None:
    registry = CancellationRegistry()

    first = registry.token("run-1")
    assert registry.request("run-1") is first
    registry.release("run-1")

    assert registry.token("run-1") is not first


def test_finalization_guard_serializes_cancellation_request() -> None:
    token = CancellationToken()
    request_finished = threading.Event()

    with token.finalization_guard() as requested:
        worker = threading.Thread(
            target=lambda: (token.request(), request_finished.set())
        )
        worker.start()
        assert requested is False
        assert request_finished.wait(timeout=0.05) is False

    assert request_finished.wait(timeout=1) is True
    worker.join(timeout=1)
    assert token.requested is True


def test_request_guard_serializes_full_cancellation_transition() -> None:
    token = CancellationToken()
    finalization_finished = threading.Event()

    def finalize() -> None:
        with token.finalization_guard():
            finalization_finished.set()

    with token.request_guard():
        worker = threading.Thread(target=finalize)
        worker.start()
        assert token.requested is True
        assert finalization_finished.wait(timeout=0.05) is False

    assert finalization_finished.wait(timeout=1) is True
    worker.join(timeout=1)


def test_obsidian_cancelable_runner_stops_before_path_resolution() -> None:
    token = CancellationToken()
    token.request()

    result = obsidian_write.run_structured_cancelable(
        {"path": "../outside.md", "content": "must not write"},
        token,
    )

    assert result["ok"] is False
    assert result["output"].startswith("写入已取消")
    assert token.effect_started is False


def test_tool_runtime_passes_cancellation_token_to_supported_skill() -> None:
    token = CancellationToken()

    class CancelableSkill:
        SKILL = {"default_timeout": 1}

        @staticmethod
        def run_structured_cancelable(args: dict, active: CancellationToken) -> dict:
            return {
                "ok": active is token,
                "summary": "token received",
                "output": str(args["value"]),
                "metadata": {},
            }

    result = invoke(
        "cancelable",
        {"value": "ok"},
        {"cancelable": CancelableSkill()},
        cancellation_token=token,
    )

    assert result.ok is True
    assert result.content_preview == "ok"
