from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import sqrt

from midi_parser import MidiEvent


MelodySource = tuple[int, int]

MELODY_ONSET_WINDOW_SECONDS = 0.05
MELODY_COVERAGE_BINS = 16


@dataclass(frozen=True)
class _MelodyFeatures:
    source: MelodySource
    note_count: int
    onset_count: int
    mean_pitch: float
    mean_velocity: float
    top_voice_ratio: float
    monophony_ratio: float
    coverage_ratio: float
    continuity_ratio: float


def detect_melody_source(events: list[MidiEvent]) -> MelodySource | None:
    """Select the most likely melodic track/channel from symbolic note data."""
    note_ons = sorted(
        (
            event
            for event in events
            if (
                event.kind == "note_on"
                and event.note is not None
                and event.channel is not None
                and event.channel != 9
            )
        ),
        key=lambda event: (
            event.time,
            event.track if event.track is not None else 0,
            event.channel if event.channel is not None else 0,
            event.note if event.note is not None else -1,
        ),
    )
    if not note_ons:
        return None

    notes_by_source: dict[MelodySource, list[MidiEvent]] = defaultdict(list)
    for event in note_ons:
        notes_by_source[_event_source(event)].append(event)
    if len(notes_by_source) == 1:
        return next(iter(notes_by_source))

    top_voice_hits: dict[MelodySource, int] = defaultdict(int)
    for group in _group_note_ons(note_ons):
        highest_note = max(event.note or 0 for event in group)
        for event in group:
            if event.note == highest_note:
                top_voice_hits[_event_source(event)] += 1

    intervals_by_source = _note_intervals(events)
    global_start = note_ons[0].time
    global_end = max(event.time for event in note_ons)
    global_span = max(0.001, global_end - global_start)
    occupied_bins = {
        _coverage_bin(event.time, global_start, global_span)
        for event in note_ons
    }

    features: list[_MelodyFeatures] = []
    for source, source_notes in notes_by_source.items():
        source_groups = _group_note_ons(source_notes)
        onset_monophony = sum(
            1.0 / max(1, len({event.note for event in group}))
            for group in source_groups
        ) / max(1, len(source_groups))
        duration_monophony = _duration_monophony(
            intervals_by_source.get(source, ())
        )
        monophony_ratio = (
            onset_monophony
            if duration_monophony is None
            else duration_monophony * 0.6 + onset_monophony * 0.4
        )
        contour = [
            max(event.note or 0 for event in group)
            for group in source_groups
        ]
        source_bins = {
            _coverage_bin(event.time, global_start, global_span)
            for event in source_notes
        }
        features.append(
            _MelodyFeatures(
                source=source,
                note_count=len(source_notes),
                onset_count=len(source_groups),
                mean_pitch=sum(event.note or 0 for event in source_notes)
                / len(source_notes),
                mean_velocity=sum(event.velocity or 64 for event in source_notes)
                / len(source_notes),
                top_voice_ratio=top_voice_hits[source] / len(source_notes),
                monophony_ratio=monophony_ratio,
                coverage_ratio=len(source_bins) / max(1, len(occupied_bins)),
                continuity_ratio=_contour_continuity(contour),
            )
        )

    pitch_values = [item.mean_pitch for item in features]
    velocity_values = [item.mean_velocity for item in features]
    largest_onset_count = max(item.onset_count for item in features)

    def score(item: _MelodyFeatures) -> tuple[float, float, int, int, int]:
        support = min(
            1.0,
            sqrt(item.onset_count / max(1, largest_onset_count)),
        )
        total = (
            item.top_voice_ratio * support * 3.0
            + item.monophony_ratio * 3.0
            + _relative_value(item.mean_pitch, pitch_values) * 2.0
            + item.coverage_ratio * 2.0
            + item.continuity_ratio
            + support * 1.5
            + _relative_value(item.mean_velocity, velocity_values) * 0.5
        )
        return (
            total,
            item.mean_pitch,
            item.note_count,
            -item.source[0],
            -item.source[1],
        )

    return max(features, key=score).source


def _event_source(event: MidiEvent) -> MelodySource:
    return (
        event.track if event.track is not None else 0,
        event.channel if event.channel is not None else 0,
    )


def _group_note_ons(note_ons: list[MidiEvent]) -> list[list[MidiEvent]]:
    groups: list[list[MidiEvent]] = []
    current: list[MidiEvent] = []
    anchor_time = 0.0
    for event in note_ons:
        if (
            not current
            or event.time - anchor_time > MELODY_ONSET_WINDOW_SECONDS
        ):
            if current:
                groups.append(current)
            current = [event]
            anchor_time = event.time
        else:
            current.append(event)
    if current:
        groups.append(current)
    return groups


def _note_intervals(
    events: list[MidiEvent],
) -> dict[MelodySource, tuple[tuple[float, float], ...]]:
    active: dict[tuple[MelodySource, int], list[float]] = defaultdict(list)
    intervals: dict[MelodySource, list[tuple[float, float]]] = defaultdict(list)
    ordered = sorted(
        events,
        key=lambda event: (
            event.time,
            0 if event.kind == "note_off" else 1,
        ),
    )
    final_time = max((event.time for event in ordered), default=0.0)
    for event in ordered:
        if (
            event.note is None
            or event.channel is None
            or event.channel == 9
            or event.kind not in {"note_on", "note_off"}
        ):
            continue
        source = _event_source(event)
        key = (source, event.note)
        if event.kind == "note_on":
            active[key].append(event.time)
            continue
        starts = active.get(key)
        if not starts:
            continue
        start = starts.pop()
        if not starts:
            active.pop(key, None)
        if event.time > start:
            intervals[source].append((start, event.time))

    for (source, _note), starts in active.items():
        for start in starts:
            if final_time > start:
                intervals[source].append((start, final_time))
    return {
        source: tuple(source_intervals)
        for source, source_intervals in intervals.items()
    }


def _duration_monophony(
    intervals: tuple[tuple[float, float], ...],
) -> float | None:
    if not intervals:
        return None
    deltas: dict[float, int] = defaultdict(int)
    for start, end in intervals:
        if end <= start:
            continue
        deltas[start] += 1
        deltas[end] -= 1
    if len(deltas) < 2:
        return None

    active = 0
    occupied_duration = 0.0
    overlapping_duration = 0.0
    previous_time = min(deltas)
    for current_time in sorted(deltas):
        duration = current_time - previous_time
        if active > 0:
            occupied_duration += duration
        if active > 1:
            overlapping_duration += duration
        active += deltas[current_time]
        previous_time = current_time
    if occupied_duration <= 0:
        return None
    return max(0.0, 1.0 - overlapping_duration / occupied_duration)


def _coverage_bin(time_value: float, start: float, span: float) -> int:
    position = max(0.0, min(0.999999, (time_value - start) / span))
    return min(
        MELODY_COVERAGE_BINS - 1,
        int(position * MELODY_COVERAGE_BINS),
    )


def _contour_continuity(notes: list[int]) -> float:
    if len(notes) < 2:
        return 0.5
    return sum(
        max(0.0, 1.0 - abs(current - previous) / 24.0)
        for previous, current in zip(notes, notes[1:])
    ) / (len(notes) - 1)


def _relative_value(value: float, values: list[float]) -> float:
    low = min(values)
    high = max(values)
    if high <= low:
        return 0.5
    return (value - low) / (high - low)
