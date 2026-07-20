from __future__ import annotations

import threading
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

    def should_suppress(self, token: Hashable, event_time: float) -> bool:
        with self._lock:
            if not self._enabled:
                return False

            event_time = float(event_time)
            previous_time = self._last_accepted_at.get(token)
            if previous_time is not None:
                elapsed = event_time - previous_time
                if 0.0 <= elapsed < self._min_interval_seconds:
                    return True

            self._last_accepted_at[token] = event_time
            return False
