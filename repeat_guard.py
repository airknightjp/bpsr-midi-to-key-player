from __future__ import annotations

import threading
import time
from collections.abc import Hashable


RAPID_REPEAT_MIN_INTERVAL_SECONDS = 0.05


class RapidRepeatGuard:
    def __init__(
        self,
        enabled: bool = False,
        min_interval_seconds: float = RAPID_REPEAT_MIN_INTERVAL_SECONDS,
    ):
        self._enabled = bool(enabled)
        self._min_interval_seconds = max(0.0, float(min_interval_seconds))
        self._last_accepted_at: dict[Hashable, float] = {}
        self._lock = threading.RLock()

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            enabled = bool(enabled)
            if enabled != self._enabled:
                self._last_accepted_at.clear()
            self._enabled = enabled

    def reset(self) -> None:
        with self._lock:
            self._last_accepted_at.clear()

    def should_suppress(
        self,
        token: Hashable,
        emitted_at: float | None = None,
    ) -> bool:
        with self._lock:
            if not self._enabled:
                return False

            output_time = time.perf_counter() if emitted_at is None else float(emitted_at)
            previous_time = self._last_accepted_at.get(token)
            if previous_time is not None:
                elapsed = output_time - previous_time
                if 0.0 <= elapsed < self._min_interval_seconds:
                    return True

            self._last_accepted_at[token] = output_time
            return False
