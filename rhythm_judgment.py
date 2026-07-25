from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class RhythmJudgment:
    note: int
    judgment: str
    timing_error_seconds: float
    released: bool = False


class RhythmJudge:
    """Matches playback and realtime note events without calculating a score."""

    HIT_WINDOW_SECONDS = 0.150
    JUDGMENT_LEVELS = (
        ("PERFECT", 0.050),
        ("GREAT", 0.100),
        ("GOOD", HIT_WINDOW_SECONDS),
    )
    TIMING_EPSILON_SECONDS = 1e-9

    def __init__(self) -> None:
        self._expected: dict[tuple[int, bool], list[float]] = defaultdict(list)
        self._inputs: dict[tuple[int, bool], list[float]] = defaultdict(list)

    def reset(self) -> None:
        self.cancel_pending()

    def cancel_pending(self) -> None:
        self._expected.clear()
        self._inputs.clear()

    def record_expected(
        self,
        note: int,
        timestamp: float,
        *,
        released: bool = False,
    ) -> RhythmJudgment | None:
        timestamp = float(timestamp)
        self._discard_expired(timestamp)
        event_key = (int(note), bool(released))
        matched_at = self._match(self._inputs, event_key, timestamp)
        if matched_at is None:
            self._expected[event_key].append(timestamp)
            return None
        return self._make_judgment(
            note,
            matched_at - timestamp,
            released=released,
        )

    def record_input(
        self,
        note: int,
        timestamp: float,
        *,
        released: bool = False,
    ) -> RhythmJudgment | None:
        timestamp = float(timestamp)
        self._discard_expired(timestamp)
        event_key = (int(note), bool(released))
        matched_at = self._match(self._expected, event_key, timestamp)
        if matched_at is None:
            self._inputs[event_key].append(timestamp)
            return None
        return self._make_judgment(
            note,
            timestamp - matched_at,
            released=released,
        )

    @staticmethod
    def record_automatic_perfect(
        note: int,
        *,
        released: bool = False,
    ) -> RhythmJudgment:
        return RhythmJudgment(
            note=int(note),
            judgment="PERFECT",
            timing_error_seconds=0.0,
            released=bool(released),
        )

    def _discard_expired(self, timestamp: float) -> None:
        cutoff = timestamp - self.HIT_WINDOW_SECONDS
        for pending in (self._expected, self._inputs):
            for event_key, timestamps in tuple(pending.items()):
                remaining = [
                    event_at
                    for event_at in timestamps
                    if event_at + self.TIMING_EPSILON_SECONDS >= cutoff
                ]
                if remaining:
                    pending[event_key] = remaining
                else:
                    pending.pop(event_key, None)

    def _match(
        self,
        pending: dict[tuple[int, bool], list[float]],
        event_key: tuple[int, bool],
        timestamp: float,
    ) -> float | None:
        candidates = pending.get(event_key)
        if not candidates:
            return None
        index, matched_at = min(
            enumerate(candidates),
            key=lambda item: abs(item[1] - timestamp),
        )
        if (
            abs(matched_at - timestamp)
            > self.HIT_WINDOW_SECONDS + self.TIMING_EPSILON_SECONDS
        ):
            return None
        candidates.pop(index)
        if not candidates:
            pending.pop(event_key, None)
        return matched_at

    @classmethod
    def _make_judgment(
        cls,
        note: int,
        timing_error_seconds: float,
        *,
        released: bool,
    ) -> RhythmJudgment:
        absolute_error = abs(float(timing_error_seconds))
        for judgment, limit in cls.JUDGMENT_LEVELS:
            if absolute_error <= limit + cls.TIMING_EPSILON_SECONDS:
                return RhythmJudgment(
                    note=int(note),
                    judgment=judgment,
                    timing_error_seconds=float(timing_error_seconds),
                    released=bool(released),
                )
        raise ValueError("Timing error is outside the judgment window")
