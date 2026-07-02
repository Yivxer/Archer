"""B6.1 Provider 熔断器测试。

覆盖：
- core.provider_breaker: record_failure / record_success / is_tripped / clear / get_state
- 连续 N 次失败触发熔断
- 成功一次清零
- 半开状态（recovery_seconds 后允许 probe）
- is_provider_connection_error 判定
- terminal.api._tools._failure_hint_event 的 provider_connection_failed keyword
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from core.provider_breaker import (
    DEFAULT_THRESHOLD,
    BreakerState,
    clear,
    get_state,
    is_provider_connection_error,
    is_tripped,
    record_failure,
    record_success,
)


@pytest.fixture(autouse=True)
def _reset_breaker():
    """每个测试前清零熔断状态，避免测试间污染。"""
    clear()
    yield
    clear()


# ── record_failure / is_tripped ──

def test_record_failure_below_threshold_does_not_trip():
    """失败次数未达阈值不熔断。"""
    assert record_failure("lite", "err1") is False
    assert record_failure("lite", "err2") is False
    assert is_tripped("lite") is False
    state = get_state("lite")
    assert state["consecutive_failures"] == 2
    assert state["tripped"] is False


def test_record_failure_at_threshold_trips():
    """连续 N 次失败触发熔断。"""
    threshold = DEFAULT_THRESHOLD
    for i in range(threshold - 1):
        assert record_failure("lite", f"err{i}") is False
    # 第 N 次触发熔断
    assert record_failure("lite", f"err{threshold - 1}") is True
    assert is_tripped("lite") is True
    state = get_state("lite")
    assert state["tripped"] is True
    assert state["consecutive_failures"] == threshold
    assert state["tripped_at"] > 0


def test_record_failure_different_profiles_independent():
    """不同 profile 的熔断状态独立。"""
    record_failure("lite", "err")
    record_failure("pro", "err")
    record_failure("pro", "err")
    record_failure("pro", "err")
    assert is_tripped("lite") is False
    assert is_tripped("pro") is True


# ── record_success ──

def test_record_success_clears_failures():
    """成功一次清零失败计数。"""
    record_failure("lite", "err")
    record_failure("lite", "err")
    record_success("lite")
    state = get_state("lite")
    assert state["consecutive_failures"] == 0
    assert state["tripped"] is False


def test_record_success_after_trip_resets():
    """熔断后成功一次复位。"""
    for _ in range(DEFAULT_THRESHOLD):
        record_failure("lite", "err")
    assert is_tripped("lite") is True
    record_success("lite")
    assert is_tripped("lite") is False
    state = get_state("lite")
    assert state["tripped"] is False


# ── 半开状态 ──

def test_is_tripped_half_open_after_recovery_seconds():
    """熔断后超过 recovery_seconds 进入半开状态，允许 probe。"""
    for _ in range(DEFAULT_THRESHOLD):
        record_failure("lite", "err")
    assert is_tripped("lite") is True

    # 模拟时间流逝（recovery_seconds=0 立即半开）
    assert is_tripped("lite", recovery_seconds=0) is False


def test_is_tripped_still_tripped_within_recovery_window():
    """熔断后未超过 recovery_seconds 仍熔断。"""
    for _ in range(DEFAULT_THRESHOLD):
        record_failure("lite", "err")
    # recovery_seconds 很大，仍熔断
    assert is_tripped("lite", recovery_seconds=3600) is True


# ── clear ──

def test_clear_specific_profile():
    """clear 特定 profile 复位。"""
    for _ in range(DEFAULT_THRESHOLD):
        record_failure("lite", "err")
    for _ in range(DEFAULT_THRESHOLD):
        record_failure("pro", "err")
    clear("lite")
    assert is_tripped("lite") is False
    assert is_tripped("pro") is True


def test_clear_all_profiles():
    """clear() 无参数清除所有 profile。"""
    for _ in range(DEFAULT_THRESHOLD):
        record_failure("lite", "err")
    for _ in range(DEFAULT_THRESHOLD):
        record_failure("pro", "err")
    clear()
    assert is_tripped("lite") is False
    assert is_tripped("pro") is False


# ── get_state ──

def test_get_state_all_profiles():
    """get_state() 无参数返回所有 profile 状态。"""
    record_failure("lite", "err")
    record_failure("pro", "err")
    state = get_state()
    assert "lite" in state
    assert "pro" in state
    assert state["lite"]["consecutive_failures"] == 1
    assert state["pro"]["consecutive_failures"] == 1


def test_get_state_unknown_profile_returns_default():
    """get_state 未知 profile 返回默认状态。"""
    state = get_state("unknown")
    assert state["consecutive_failures"] == 0
    assert state["tripped"] is False


# ── is_provider_connection_error ──

def test_is_provider_connection_error_connection_hint():
    """_connection_hint 抛的 RuntimeError 应被识别。"""
    err = RuntimeError("无法连接 LLM API。base_url=...；底层错误：connection refused")
    assert is_provider_connection_error(err) is True


def test_is_provider_connection_error_timeout():
    """超时错误应被识别。"""
    assert is_provider_connection_error(TimeoutError("connect timeout")) is True
    assert is_provider_connection_error(RuntimeError("请求超时")) is True


def test_is_provider_connection_error_generic():
    """普通错误不被识别为 provider 连接错误。"""
    assert is_provider_connection_error(ValueError("invalid input")) is False
    assert is_provider_connection_error(RuntimeError("some other error")) is False


# ── _failure_hint_event provider_connection_failed keyword ──

class TestFailureHintProviderKeyword:
    """验证 _failure_hint_event 对 provider 失败发出正确 keyword。"""

    def test_connection_hint_emits_provider_keyword(self):
        from terminal.api._tools import _failure_hint_event
        err = RuntimeError("无法连接 LLM API。base_url=...；底层错误：connection refused")
        event = _failure_hint_event(err, stage="model_stream")
        assert event["keyword"] == "provider_connection_failed"
        assert event["recoverable"] is True

    def test_status_hint_auth_emits_provider_keyword(self):
        from terminal.api._tools import _failure_hint_event
        err = RuntimeError("模型 API 鉴权失败：当前模型档位的 API key 缺失、无效或无权限。")
        event = _failure_hint_event(err, stage="model_stream")
        assert event["keyword"] == "provider_connection_failed"

    def test_status_hint_rate_limit_emits_provider_keyword(self):
        from terminal.api._tools import _failure_hint_event
        err = RuntimeError("模型 API 额度或频率受限：当前请求被服务商限流。")
        event = _failure_hint_event(err, stage="model_stream")
        assert event["keyword"] == "provider_connection_failed"

    def test_generic_timeout_emits_command_timeout(self):
        """非 model_stream stage 的 timeout 仍走 command_timeout。"""
        from terminal.api._tools import _failure_hint_event
        err = TimeoutError("command timeout")
        event = _failure_hint_event(err, stage="shell_execute")
        assert event["keyword"] == "command_timeout"


# ── 集成测试：llm.py 失败记录到熔断器 ──

class TestLlmBreakerIntegration:
    """验证 core/llm.py 失败时记录到熔断器，成功时清零。"""

    def test_stream_chat_failure_records_to_breaker(self, monkeypatch):
        """stream_chat 连接失败应记录到熔断器。"""
        from openai import APIConnectionError
        from core import llm as llm_mod

        # mock _get_client 抛 APIConnectionError
        def boom_create(*args, **kwargs):
            raise APIConnectionError(request=None)

        # mock cfg
        fake_cfg = {"api": {"active_profile": "test_lite", "model": "m", "base_url": "x", "api_key": "k"}}

        monkeypatch.setattr(llm_mod, "_get_client", lambda: (None, fake_cfg))
        monkeypatch.setattr(llm_mod, "is_provider_connection_error", lambda e: True)

        # 让 OpenAI client.chat.completions.create 抛 APIConnectionError
        class FakeClient:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kwargs):
                        raise APIConnectionError(request=None)

        monkeypatch.setattr(llm_mod, "_get_client", lambda: (FakeClient(), fake_cfg))

        clear()
        # stream_chat 把 APIConnectionError 包成 RuntimeError（_connection_hint）
        import pytest as _pytest
        with _pytest.raises(RuntimeError):
            gen = llm_mod.stream_chat([{"role": "user", "content": "hi"}])
            next(gen)  # 触发异常

        # 熔断器应记录 1 次失败
        state = get_state("test_lite")
        assert state["consecutive_failures"] >= 1

    def test_call_with_tools_failure_records_to_breaker(self, monkeypatch):
        """call_with_tools 连接失败应记录到熔断器。"""
        from openai import APIConnectionError
        from core import llm as llm_mod

        fake_cfg = {"api": {"active_profile": "test_pro", "model": "m", "base_url": "x", "api_key": "k"}}

        class FakeClient:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kwargs):
                        raise APIConnectionError(request=None)

        monkeypatch.setattr(llm_mod, "_get_client", lambda: (FakeClient(), fake_cfg))
        monkeypatch.setattr(llm_mod, "is_provider_connection_error", lambda e: True)

        clear()
        import pytest as _pytest
        with _pytest.raises(RuntimeError):
            llm_mod.call_with_tools([], [])

        state = get_state("test_pro")
        assert state["consecutive_failures"] >= 1
