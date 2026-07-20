from __future__ import annotations

import random
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass

from midi_parser import MidiEvent


HUMANIZE_MAX_JITTER_SECONDS = 0.018
CHORD_STRUM_MAX_OFFSET_SECONDS = 0.012
CHORD_STRUM_MIN_NOTES = 2
MIN_PLAYBACK_SPEED_PERCENT = 50
MAX_PLAYBACK_SPEED_PERCENT = 200


@dataclass(frozen=True)
class ScheduledMidiEvent:
    event: MidiEvent
    strum_offset: float = 0.0


def prepare_playback_events(
    events: list[MidiEvent],
    random_source: random.Random | None = None,
) -> list[ScheduledMidiEvent]:
    if random_source is None:
        random_source = random.Random()
    ordered: list[ScheduledMidiEvent] = []
    index = 0
    while index < len(events):
        group_time = events[index].time
        end = index + 1
        while end < len(events) and events[end].time == group_time:
            end += 1

        group = events[index:end]
        note_ons = [
            event
            for event in group
            if event.kind == "note_on" and event.note is not None
        ]
        other_events = [event for event in group if event not in note_ons]
        distinct_notes = sorted({event.note for event in note_ons if event.note is not None})
        if len(distinct_notes) < CHORD_STRUM_MIN_NOTES:
            note_offsets = {note: 0.0 for note in distinct_notes}
        else:
            raw_offsets = {
                note: random_source.uniform(0.0, CHORD_STRUM_MAX_OFFSET_SECONDS)
                for note in distinct_notes
            }
            earliest_offset = min(raw_offsets.values())
            note_offsets = {
                note: offset - earliest_offset
                for note, offset in raw_offsets.items()
            }

        ordered.extend(ScheduledMidiEvent(event) for event in other_events)
        ordered.extend(
            ScheduledMidiEvent(event, note_offsets.get(event.note, 0.0))
            for event in sorted(
                note_ons,
                key=lambda event: (
                    note_offsets.get(event.note, 0.0),
                    event.note if event.note is not None else -1,
                    event.track if event.track is not None else -1,
                    event.channel if event.channel is not None else -1,
                ),
            )
        )
        index = end

    active_offsets: dict[tuple[int, int, int], deque[float]] = defaultdict(deque)
    prepared: list[ScheduledMidiEvent] = []
    for scheduled in ordered:
        event = scheduled.event
        owner = (
            event.track if event.track is not None else -1,
            event.channel if event.channel is not None else 0,
            event.note if event.note is not None else -1,
        )
        if event.kind == "note_on" and event.note is not None:
            active_offsets[owner].append(scheduled.strum_offset)
            prepared.append(scheduled)
        elif event.kind == "note_off" and event.note is not None:
            offsets = active_offsets.get(owner)
            offset = offsets.popleft() if offsets else 0.0
            if offsets is not None and not offsets:
                active_offsets.pop(owner, None)
            prepared.append(ScheduledMidiEvent(event, offset))
        else:
            prepared.append(scheduled)
    return prepared


class PlaybackTimeline:
    def __init__(self, start_time: float, random_source: random.Random):
        self.start_time = max(0.0, start_time)
        self.random_source = random_source
        self._source_group_time: float | None = None
        self._group_jitter = 0.0
        self._previous_scheduled_time = self.start_time

    def scheduled_time(
        self,
        scheduled: ScheduledMidiEvent | MidiEvent,
        humanize_timing: bool = False,
        chord_strum: bool = False,
    ) -> float:
        if isinstance(scheduled, MidiEvent):
            scheduled = ScheduledMidiEvent(scheduled)
        event = scheduled.event
        if event.kind == "end":
            return max(self._previous_scheduled_time, event.time)

        if self._source_group_time is None or event.time != self._source_group_time:
            self._source_group_time = event.time
            self._group_jitter = self.random_source.triangular(
                -HUMANIZE_MAX_JITTER_SECONDS,
                HUMANIZE_MAX_JITTER_SECONDS,
                0.0,
            )

        jitter = self._group_jitter if humanize_timing else 0.0
        strum_offset = scheduled.strum_offset if chord_strum else 0.0
        return max(
            self.start_time,
            self._previous_scheduled_time,
            event.time + jitter + strum_offset,
        )

    def mark_emitted(self, scheduled_time: float) -> None:
        self._previous_scheduled_time = max(
            self._previous_scheduled_time,
            scheduled_time,
        )


class PlaybackClock:
    def __init__(
        self,
        start_position: float,
        speed_percent: int = 100,
        time_source: Callable[[], float] = time.perf_counter,
    ):
        self._time_source = time_source
        self._lock = threading.Lock()
        self._anchor_time = time_source()
        self._anchor_position = max(0.0, start_position)
        self._speed = self._clamp_speed(speed_percent) / 100.0

    def position(self) -> float:
        with self._lock:
            return self._position_unlocked(self._time_source())

    def delay_until(self, target_position: float) -> float:
        with self._lock:
            remaining = target_position - self._position_unlocked(self._time_source())
            return max(0.0, remaining / self._speed)

    def set_speed_percent(self, speed_percent: int) -> None:
        with self._lock:
            now = self._time_source()
            self._anchor_position = self._position_unlocked(now)
            self._anchor_time = now
            self._speed = self._clamp_speed(speed_percent) / 100.0

    def _position_unlocked(self, now: float) -> float:
        return self._anchor_position + (now - self._anchor_time) * self._speed

    @staticmethod
    def _clamp_speed(speed_percent: int) -> int:
        return max(
            MIN_PLAYBACK_SPEED_PERCENT,
            min(MAX_PLAYBACK_SPEED_PERCENT, int(speed_percent)),
        )
