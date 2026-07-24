from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class RhythmHit:
    note: int
    judgment: str
    timing_error_seconds: float
    base_points: int
    multiplier_tenths: int
    awarded_points: int
    combo: int
    released: bool = False


@dataclass
class _ActiveHold:
    note: int
    started_at: float
    automatic: bool = False
    scored_ticks: int = 0
    expected_released_at: float | None = None
    input_released_at: float | None = None


class RhythmScorer:
    """Matches final MIDI playback notes with final realtime input notes."""

    HIT_WINDOW_SECONDS = 0.150
    JUDGMENT_LEVELS = (
        ("PERFECT", 0.050, 100),
        ("GREAT", 0.100, 70),
        ("GOOD", HIT_WINDOW_SECONDS, 40),
    )
    TIMING_EPSILON_SECONDS = 1e-9
    COMBO_STEP = 10
    MAX_MULTIPLIER_TENTHS = 20
    HOLD_TICK_SECONDS = 0.100
    HOLD_TICK_BASE_POINTS = 10
    MISS_EXPIRY_EPSILON_SECONDS = 0.000_001

    def __init__(self) -> None:
        self.score = 0
        self.combo = 0
        self.judgment = ""
        self.multiplier_tenths = 10
        self._expected: dict[tuple[int, bool], list[float]] = defaultdict(list)
        self._inputs: dict[tuple[int, bool], list[float]] = defaultdict(list)
        self._active_holds: dict[int, list[_ActiveHold]] = defaultdict(list)
        self._missed_events: list[tuple[int, bool]] = []

    def reset(self) -> bool:
        changed = (
            self.score != 0
            or self.combo != 0
            or bool(self.judgment)
            or self.multiplier_tenths != 10
        )
        self.score = 0
        self.combo = 0
        self.judgment = ""
        self.multiplier_tenths = 10
        self.cancel_pending()
        return changed

    def cancel_pending(self) -> None:
        self._expected.clear()
        self._inputs.clear()
        self._active_holds.clear()
        self._missed_events.clear()

    def record_expected(
        self,
        note: int,
        timestamp: float,
        *,
        released: bool = False,
    ) -> RhythmHit | None:
        self.expire(timestamp)
        if released:
            self._mark_hold_release(
                note,
                timestamp,
                expected=True,
            )
        event_key = (int(note), bool(released))
        matched_at = self._match(self._inputs, event_key, timestamp)
        if matched_at is not None:
            hit = self._record_hit(
                note,
                matched_at - timestamp,
                released=released,
            )
            if not released:
                self._start_hold(note, max(timestamp, matched_at))
            self._remove_finished_holds(note)
            return hit
        self._expected[event_key].append(timestamp)
        self._remove_finished_holds(note)
        return None

    def record_input(
        self,
        note: int,
        timestamp: float,
        *,
        released: bool = False,
    ) -> RhythmHit | None:
        self.expire(timestamp)
        if released:
            self._mark_hold_release(
                note,
                timestamp,
                expected=False,
            )
        event_key = (int(note), bool(released))
        matched_at = self._match(self._expected, event_key, timestamp)
        if matched_at is not None:
            hit = self._record_hit(
                note,
                timestamp - matched_at,
                released=released,
            )
            if not released:
                self._start_hold(note, max(timestamp, matched_at))
            self._remove_finished_holds(note)
            return hit
        self._inputs[event_key].append(timestamp)
        self._remove_finished_holds(note)
        return None

    def record_automatic_perfect(
        self,
        note: int,
        *,
        released: bool = False,
        timestamp: float | None = None,
    ) -> RhythmHit:
        if timestamp is not None:
            self.advance(timestamp)
            if released:
                self._mark_automatic_hold_release(note, timestamp)
            else:
                self._start_hold(note, timestamp, automatic=True)
        hit = self._record_hit(note, 0.0, released=released)
        self._remove_finished_holds(note)
        return hit

    def expire(self, timestamp: float) -> bool:
        changed = self.advance(timestamp)
        cutoff = timestamp - self.HIT_WINDOW_SECONDS
        missed = self._expire_before(self._expected, cutoff)
        wrong = self._expire_before(self._inputs, cutoff)
        if not missed and not wrong:
            return changed
        self._missed_events.extend(
            (int(event_key[0]), bool(event_key[1]))
            for event_key in (*missed, *wrong)
        )
        self.combo = 0
        self.judgment = "MISS"
        self.multiplier_tenths = 10
        self._remove_stale_holds(cutoff)
        return True

    def take_missed_events(self) -> tuple[tuple[int, bool], ...]:
        missed_events = tuple(self._missed_events)
        self._missed_events.clear()
        return missed_events

    def take_missed_notes(self) -> tuple[int, ...]:
        return tuple(
            note
            for note, _released in self.take_missed_events()
        )

    def advance(self, timestamp: float) -> bool:
        changed = False
        for holds in tuple(self._active_holds.values()):
            for hold in holds:
                end_at = float(timestamp)
                if hold.expected_released_at is not None:
                    end_at = min(end_at, hold.expected_released_at)
                if hold.input_released_at is not None:
                    end_at = min(end_at, hold.input_released_at)
                elapsed = max(0.0, end_at - hold.started_at)
                target_ticks = int(
                    (
                        elapsed + self.TIMING_EPSILON_SECONDS
                    )
                    / self.HOLD_TICK_SECONDS
                )
                new_ticks = max(0, target_ticks - hold.scored_ticks)
                if not new_ticks:
                    continue
                hold.scored_ticks += new_ticks
                points_per_tick = (
                    self.HOLD_TICK_BASE_POINTS
                    * self.multiplier_tenths
                    // 10
                )
                self.score += points_per_tick * new_ticks
                changed = True
        return changed

    @property
    def has_active_holds(self) -> bool:
        return any(
            hold.expected_released_at is None
            and hold.input_released_at is None
            for holds in self._active_holds.values()
            for hold in holds
        )

    def next_hold_tick_delay_ms(self, timestamp: float) -> int | None:
        next_ticks = [
            hold.started_at
            + (hold.scored_ticks + 1) * self.HOLD_TICK_SECONDS
            for holds in self._active_holds.values()
            for hold in holds
            if hold.expected_released_at is None
            and hold.input_released_at is None
        ]
        if not next_ticks:
            return None
        remaining = max(0.0, min(next_ticks) - float(timestamp))
        return self._delay_ms(remaining)

    def next_update_delay_ms(self, timestamp: float) -> int | None:
        due_times = [
            hold.started_at
            + (hold.scored_ticks + 1) * self.HOLD_TICK_SECONDS
            for holds in self._active_holds.values()
            for hold in holds
            if hold.expected_released_at is None
            and hold.input_released_at is None
        ]
        due_times.extend(
            event_at
            + self.HIT_WINDOW_SECONDS
            + self.MISS_EXPIRY_EPSILON_SECONDS
            for pending in (self._expected, self._inputs)
            for timestamps in pending.values()
            for event_at in timestamps
        )
        if not due_times:
            return None
        remaining = max(0.0, min(due_times) - float(timestamp))
        return self._delay_ms(remaining)

    @staticmethod
    def _delay_ms(remaining_seconds: float) -> int:
        return max(1, math.ceil(remaining_seconds * 1000 - 0.000_001))

    def _record_hit(
        self,
        note: int,
        timing_error_seconds: float,
        *,
        released: bool,
    ) -> RhythmHit:
        absolute_error = abs(timing_error_seconds)
        judgment, base_points = self._judgment_for_error(absolute_error)
        self.combo += 1
        self.multiplier_tenths = min(
            self.MAX_MULTIPLIER_TENTHS,
            10 + self.combo // self.COMBO_STEP,
        )
        awarded_points = base_points * self.multiplier_tenths // 10
        self.score += awarded_points
        self.judgment = judgment
        return RhythmHit(
            note=note,
            judgment=judgment,
            timing_error_seconds=timing_error_seconds,
            base_points=base_points,
            multiplier_tenths=self.multiplier_tenths,
            awarded_points=awarded_points,
            combo=self.combo,
            released=bool(released),
        )

    def _start_hold(
        self,
        note: int,
        timestamp: float,
        *,
        automatic: bool = False,
    ) -> None:
        self._active_holds[int(note)].append(
            _ActiveHold(
                note=int(note),
                started_at=float(timestamp),
                automatic=bool(automatic),
            )
        )

    def _mark_hold_release(
        self,
        note: int,
        timestamp: float,
        *,
        expected: bool,
    ) -> None:
        holds = self._active_holds.get(int(note), ())
        for hold in holds:
            if hold.automatic:
                continue
            released_at = (
                hold.expected_released_at
                if expected
                else hold.input_released_at
            )
            if released_at is not None:
                continue
            if expected:
                hold.expected_released_at = float(timestamp)
            else:
                hold.input_released_at = float(timestamp)
            return

    def _mark_automatic_hold_release(
        self,
        note: int,
        timestamp: float,
    ) -> None:
        for hold in self._active_holds.get(int(note), ()):
            if (
                hold.automatic
                and hold.expected_released_at is None
                and hold.input_released_at is None
            ):
                hold.expected_released_at = float(timestamp)
                hold.input_released_at = float(timestamp)
                return

    def _remove_finished_holds(self, note: int) -> None:
        note = int(note)
        remaining = [
            hold
            for hold in self._active_holds.get(note, ())
            if (
                hold.expected_released_at is None
                or hold.input_released_at is None
            )
        ]
        if remaining:
            self._active_holds[note] = remaining
        else:
            self._active_holds.pop(note, None)

    def _remove_stale_holds(self, cutoff: float) -> None:
        for note, holds in tuple(self._active_holds.items()):
            remaining = [
                hold
                for hold in holds
                if not (
                    (
                        hold.expected_released_at is not None
                        and hold.expected_released_at < cutoff
                    )
                    or (
                        hold.input_released_at is not None
                        and hold.input_released_at < cutoff
                    )
                )
            ]
            if remaining:
                self._active_holds[note] = remaining
            else:
                self._active_holds.pop(note, None)

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
    def _judgment_for_error(cls, error_seconds: float) -> tuple[str, int]:
        for judgment, limit, points in cls.JUDGMENT_LEVELS:
            if error_seconds <= limit + cls.TIMING_EPSILON_SECONDS:
                return judgment, points
        raise ValueError("Timing error is outside the hit window")

    @staticmethod
    def _expire_before(
        pending: dict[tuple[int, bool], list[float]],
        cutoff: float,
    ) -> tuple[tuple[int, bool], ...]:
        expired: list[tuple[int, bool]] = []
        for event_key, timestamps in tuple(pending.items()):
            remaining = [timestamp for timestamp in timestamps if timestamp >= cutoff]
            expired.extend(
                event_key
                for _ in range(len(timestamps) - len(remaining))
            )
            if remaining:
                pending[event_key] = remaining
            else:
                pending.pop(event_key, None)
        return tuple(expired)
