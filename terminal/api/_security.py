"""API 安全模块：认证、限流、请求验证。"""
from __future__ import annotations
import hmac
import time
import threading
from datetime import datetime, timezone


# ── 恒定时间比较 ───────────────────────────────────────────────────────────────

def constant_time_compare(received: str, expected: str) -> bool:
    """恒定时间比较，防止时序攻击。"""
    return hmac.compare_digest(received, expected)


# ── 令牌桶限流 ────────────────────────────────────────────────────────────────

class TokenBucketRateLimiter:
    """令牌桶限流器。线程安全。"""

    def __init__(self, max_tokens: int = 30, refill_per_sec: float = 2.0):
        self._max = max_tokens
        self._refill = refill_per_sec
        self._buckets: dict[str, list[float]] = {}  # ip → [tokens, last_refill]
        self._lock = threading.Lock()

    def allow(self, client_ip: str) -> bool:
        """检查是否允许请求。"""
        with self._lock:
            now = time.monotonic()
            if client_ip not in self._buckets:
                self._buckets[client_ip] = [float(self._max), now]
                return True
            tokens, last = self._buckets[client_ip]
            elapsed = now - last
            tokens = min(self._max, tokens + elapsed * self._refill)
            self._buckets[client_ip] = [tokens, now]
            if tokens >= 1.0:
                self._buckets[client_ip][0] = tokens - 1.0
                return True
            return False


# 全局限流实例
_rate_limiter = TokenBucketRateLimiter(max_tokens=30, refill_per_sec=2.0)
_chat_limiter = TokenBucketRateLimiter(max_tokens=6, refill_per_sec=0.5)


def check_rate_limit(client_ip: str, endpoint: str = "") -> bool:
    """返回 True = 允许，False = 超限。"""
    if endpoint == "/chat/stream":
        return _chat_limiter.allow(client_ip)
    return _rate_limiter.allow(client_ip)


# ── 请求体验证 ─────────────────────────────────────────────────────────────────

MAX_CONTENT_LENGTH = 128_000  # 128KB


def validate_content_length(headers) -> tuple[bool, int]:
    """验证 Content-Length。返回 (ok, length)。"""
    try:
        length = int(headers.get("Content-Length", "0"))
    except (ValueError, TypeError):
        return False, 0
    return length <= MAX_CONTENT_LENGTH, length


# ── 统一错误响应 ──────────────────────────────────────────────────────────────

def error_response(status: int, error_code: str, message: str = "") -> tuple[int, dict]:
    """统一的错误响应格式。"""
    return status, {
        "error": error_code,
        "message": message or error_code,
        "detail": message or error_code,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def normalize_error_payload(status: int, payload: dict | list) -> dict | list:
    """Ensure API error responses expose error/message/detail consistently."""
    if status < 400 or not isinstance(payload, dict):
        return payload
    if "error" not in payload:
        return payload

    normalized = dict(payload)
    error = str(normalized.get("error") or "error")
    message = str(normalized.get("message") or error)
    detail = str(
        normalized.get("detail")
        or normalized.get("path")
        or normalized.get("id")
        or message
    )
    normalized["error"] = error
    normalized["message"] = message
    normalized["detail"] = detail
    return normalized
