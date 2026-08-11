"""Process-local cooperative cancellation for active Runtime executions."""
from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager


class CancellationToken:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requested = threading.Event()
        self._effect_started = threading.Event()
        self._effect_finished = threading.Event()

    @property
    def requested(self) -> bool:
        return self._requested.is_set()

    @property
    def effect_started(self) -> bool:
        return self._effect_started.is_set()

    @property
    def effect_finished(self) -> bool:
        return self._effect_finished.is_set()

    def request(self) -> None:
        with self._lock:
            self._requested.set()

    @contextmanager
    def request_guard(self) -> Iterator[None]:
        """Hold the cancellation decision lock through persisted state changes."""
        with self._lock:
            self._requested.set()
            yield

    @contextmanager
    def side_effect_guard(self) -> Iterator[bool]:
        with self._lock:
            allowed = not self._requested.is_set()
            if allowed:
                self._effect_started.set()
        if not allowed:
            yield False
            return
        try:
            yield True
        finally:
            self._effect_finished.set()

    @contextmanager
    def finalization_guard(self) -> Iterator[bool]:
        """Serialize the final cancellation decision with Runtime finalization."""
        with self._lock:
            yield self._requested.is_set()


class CancellationRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens: dict[str, CancellationToken] = {}

    def token(self, run_id: str) -> CancellationToken:
        with self._lock:
            token = self._tokens.get(run_id)
            if token is None:
                token = CancellationToken()
                self._tokens[run_id] = token
            return token

    def request(self, run_id: str) -> CancellationToken:
        token = self.token(run_id)
        token.request()
        return token

    def release(self, run_id: str) -> None:
        with self._lock:
            self._tokens.pop(run_id, None)
