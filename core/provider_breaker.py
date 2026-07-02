"""B6.1 Provider 熔断器（进程内）。

契约（Archer 稳定性框架.md §三-B B6）：
- 连续 3 次 provider_connection_failed → 自动切回 default profile（lite）
- 熔断后恢复：超时自动 half-open + doctor clear 手动复位

设计：
- 进程内 dict 存熔断状态（单进程 FastAPI，重启清零可接受）
- 只计 provider 连接/超时失败，不计 401/403（配置错）和 429（限流）
- 成功一次清零（标准 circuit breaker 语义）
- half-open：熔断后 T 秒（默认 300s）允许一次 probe，成功则复位
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 3
DEFAULT_RECOVERY_SECONDS = 300  # 5 分钟后半开


@dataclass
class BreakerState:
    """单个 profile 的熔断状态。"""
    consecutive_failures: int = 0
    tripped: bool = False
    tripped_at: float = 0.0
    last_error: str = ""
    last_failure_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "consecutive_failures": self.consecutive_failures,
            "tripped": self.tripped,
            "tripped_at": self.tripped_at,
            "last_error": self.last_error,
            "last_failure_at": self.last_failure_at,
        }


@dataclass
class _BreakerStore:
    states: dict[str, BreakerState] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def get(self, profile_id: str) -> BreakerState:
        return self.states.setdefault(profile_id, BreakerState())


_store = _BreakerStore()


def record_failure(
    profile_id: str,
    error: str,
    *,
    threshold: int = DEFAULT_THRESHOLD,
    recovery_seconds: int = DEFAULT_RECOVERY_SECONDS,
) -> bool:
    """记录一次 provider 失败。

    返回 True 表示这次失败触发了熔断（达到阈值）。
    返回 False 表示未触发熔断（计数累加但未达阈值）。

    半开状态下失败 → 重新熔断，重置 tripped_at。
    """
    profile_id = str(profile_id or "").strip() or "unknown"
    with _store.lock:
        state = _store.get(profile_id)
        # 半开状态检查：如果已熔断且超过 recovery_seconds，允许 probe
        # probe 失败 → 重新熔断
        state.consecutive_failures += 1
        state.last_error = str(error)[:300]
        state.last_failure_at = time.time()

        if state.consecutive_failures >= threshold:
            was_tripped = state.tripped
            state.tripped = True
            state.tripped_at = time.time()
            if not was_tripped:
                logger.warning(
                    "Provider '%s' 熔断：连续 %d 次失败（%s）",
                    profile_id, state.consecutive_failures, state.last_error[:120],
                )
            return True
        return False


def record_success(profile_id: str) -> None:
    """记录一次 provider 成功，清零失败计数（half-open probe 成功 → 复位）。"""
    profile_id = str(profile_id or "").strip() or "unknown"
    with _store.lock:
        state = _store.get(profile_id)
        if state.consecutive_failures > 0 or state.tripped:
            logger.info("Provider '%s' 恢复：成功一次，清零熔断状态", profile_id)
        state.consecutive_failures = 0
        state.tripped = False
        state.tripped_at = 0.0
        state.last_error = ""


def is_tripped(
    profile_id: str,
    *,
    recovery_seconds: int = DEFAULT_RECOVERY_SECONDS,
) -> bool:
    """检查 profile 是否熔断。

    半开语义：如果已熔断且超过 recovery_seconds，返回 False（允许 probe）。
    """
    profile_id = str(profile_id or "").strip() or "unknown"
    with _store.lock:
        state = _store.get(profile_id)
        if not state.tripped:
            return False
        # 半开：超过 recovery_seconds 允许一次 probe
        if time.time() - state.tripped_at > recovery_seconds:
            return False
        return True


def clear(profile_id: str | None = None) -> None:
    """手动复位熔断状态。

    profile_id=None 表示清除所有 profile 的熔断状态（doctor clear 用）。
    """
    with _store.lock:
        if profile_id is None:
            for pid, state in _store.states.items():
                if state.tripped:
                    logger.info("Provider '%s' 手动复位", pid)
                _store.states[pid] = BreakerState()
        else:
            profile_id = str(profile_id).strip() or "unknown"
            state = _store.get(profile_id)
            if state.tripped:
                logger.info("Provider '%s' 手动复位", profile_id)
            _store.states[profile_id] = BreakerState()


def get_state(profile_id: str | None = None) -> dict:
    """读取熔断状态（doctor / 诊断用）。

    profile_id=None 返回所有 profile 状态。
    """
    with _store.lock:
        if profile_id is None:
            return {pid: state.to_dict() for pid, state in _store.states.items()}
        profile_id = str(profile_id).strip() or "unknown"
        return _store.get(profile_id).to_dict()


def is_provider_connection_error(error: Exception) -> bool:
    """判断异常是否为 provider 连接/超时失败（应计入熔断）。

    不计 401/403（配置错，切档没用）和 429（限流，切档可能有用但语义不同）。
    """
    text = str(error).lower()
    # _connection_hint 抛的 RuntimeError 含 "无法连接 llm api"
    if "无法连接" in str(error) or "llm api" in text:
        return True
    # 超时
    if "timeout" in text or "超时" in str(error):
        return True
    # 连接错误
    if "connection" in text or "连接" in str(error):
        return True
    return False
