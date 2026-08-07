from __future__ import annotations

import random
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass

from auto_sustain import AUTO_SUSTAIN_EVENT_KIND, plan_auto_sustain
from chord_optimization import ChordOptimizationPlan
from config import (
    DEFAULT_FIT_NOTE_RANGE,
    PIANO_NOTE_MAX,
    PIANO_NOTE_MIN,
    fit_note_to_range,
    shift_midi_note,
)
from midi_parser import MidiEvent
from playback_timing import PlaybackTimeline, prepare_playback_events
from repeat_guard import RAPID_REPEAT_MIN_INTERVAL_SECONDS


@dataclass(frozen=True)
class PianoRollNote:
    start: float
    end: float
    note: int
    source: tuple[int, int] | None = None


def build_output_note_range(
    events: Iterable[MidiEvent],
    *,
    enabled_sources: set[tuple[int, int]] | None = None,
    enabled_channels: set[int] | None = None,
    auto_fit_note_range: bool = False,
    fit_note_range: object = DEFAULT_FIT_NOTE_RANGE,
    transpose_semitones: int = 0,
    octave_shift: int = 0,
    chord_optimization_plan: ChordOptimizationPlan | None = None,
) -> tuple[int, int] | None:
    output_notes: list[int] = []
    for event in events:
        if (
            event.kind != "note_on"
            or event.note is None
            or event.channel is None
            or not _event_enabled(event, enabled_sources, enabled_channels)
        ):
            continue
        note = _visual_note(
            event,
            auto_fit_note_range=auto_fit_note_range,
            fit_note_range=fit_note_range,
            transpose_semitones=transpose_semitones,
            octave_shift=octave_shift,
            chord_optimization_plan=chord_optimization_plan,
        )
        if note is not None:
            output_notes.append(note)
    if not output_notes:
        return None
    return min(output_notes), max(output_notes)


def build_piano_roll_notes(
    events: Iterable[MidiEvent],
    *,
    enabled_sources: set[tuple[int, int]] | None = None,
    enabled_channels: set[int] | None = None,
    auto_fit_note_range: bool = False,
    fit_note_range: object = DEFAULT_FIT_NOTE_RANGE,
    transpose_semitones: int = 0,
    octave_shift: int = 0,
    chord_optimization_plan: ChordOptimizationPlan | None = None,
    humanize_timing: bool = False,
    chord_strum: bool = False,
    auto_sustain: bool = False,
    repeat_prevention: bool = False,
    playback_speed_percent: int = 100,
) -> tuple[PianoRollNote, ...]:
    ordered = list(events)
    planned_events = plan_auto_sustain(ordered) if auto_sustain else ordered
    random_source = random.Random(0)
    prepared_events = prepare_playback_events(
        planned_events,
        random_source,
        (
            chord_optimization_plan.timing_offset_for
            if chord_optimization_plan is not None
            else None
        ),
    )
    timeline = PlaybackTimeline(0.0, random_source)
    fallback_end = max((event.time for event in planned_events), default=0.0)
    active: dict[
        tuple[int, int, int],
        deque[tuple[float, int | None, tuple[int, int]]],
    ] = defaultdict(deque)
    sustained: dict[
        tuple[int, int],
        list[tuple[float, int | None, tuple[int, int]]],
    ] = defaultdict(list)
    manual_sustain_sources: set[tuple[int, int]] = set()
    auto_sustain_sources: set[tuple[int, int]] = set()
    suppressed_note_offs: dict[tuple[int, int, int], int] = defaultdict(int)
    last_output_at: dict[tuple[int, int], float] = {}
    notes: list[PianoRollNote] = []
    speed_ratio = max(0.1, min(2.0, int(playback_speed_percent) / 100.0))

    for scheduled in prepared_events:
        event = scheduled.event
        event_time = timeline.scheduled_time(
            scheduled,
            humanize_timing=humanize_timing,
            chord_strum=chord_strum,
            chord_optimization_offset=(
                chord_optimization_plan.timing_offset_for(event)
                if chord_optimization_plan is not None
                else None
            ),
        )
        timeline.mark_emitted(event_time)
        fallback_end = max(fallback_end, event_time)

        if event.channel is None or not _event_enabled(
            event, enabled_sources, enabled_channels
        ):
            continue
        source = (
            event.track if event.track is not None else -1,
            event.channel,
        )
        owner = (
            source[0],
            event.channel,
            event.note if event.note is not None else -1,
        )

        if event.kind == "note_on" and event.note is not None:
            note = _visual_note(
                event,
                auto_fit_note_range=auto_fit_note_range,
                fit_note_range=fit_note_range,
                transpose_semitones=transpose_semitones,
                octave_shift=octave_shift,
                chord_optimization_plan=chord_optimization_plan,
            )
            if note is not None and repeat_prevention:
                output_at = event_time / speed_ratio
                repeat_token = (event.channel, note)
                previous_output_at = last_output_at.get(repeat_token)
                if (
                    previous_output_at is not None
                    and 0.0 <= output_at - previous_output_at
                    < RAPID_REPEAT_MIN_INTERVAL_SECONDS
                ):
                    suppressed_note_offs[owner] += 1
                    continue
                last_output_at[repeat_token] = output_at
            active[owner].append(
                (
                    event_time,
                    note,
                    source,
                )
            )
        elif event.kind == "note_off" and event.note is not None:
            if suppressed_note_offs.get(owner, 0) > 0:
                suppressed_note_offs[owner] -= 1
                if suppressed_note_offs[owner] <= 0:
                    suppressed_note_offs.pop(owner, None)
                continue
            pending = active.get(owner)
            if not pending:
                continue
            start, note, note_source = pending.popleft()
            if not pending:
                active.pop(owner, None)
            if source in manual_sustain_sources or source in auto_sustain_sources:
                sustained[source].append((start, note, note_source))
            else:
                _append_note(notes, start, event_time, note, note_source)
        elif event.kind == "sustain" and event.value is not None:
            _update_sustain(
                source,
                event.value >= 64,
                manual_sustain_sources,
                auto_sustain_sources,
                sustained,
                notes,
                event_time,
            )
        elif (
            event.kind == AUTO_SUSTAIN_EVENT_KIND
            and event.value is not None
            and auto_sustain
        ):
            _update_sustain(
                source,
                event.value >= 64,
                auto_sustain_sources,
                manual_sustain_sources,
                sustained,
                notes,
                event_time,
            )

    for pending in active.values():
        for start, note, note_source in pending:
            _append_note(notes, start, fallback_end, note, note_source)
    for pending in sustained.values():
        for start, note, note_source in pending:
            _append_note(notes, start, fallback_end, note, note_source)

    return tuple(
        sorted(
            notes,
            key=lambda item: (
                item.start,
                item.note,
                item.end,
                item.source or (-1, -1),
            ),
        )
    )


def _update_sustain(
    source: tuple[int, int],
    enabled: bool,
    target_sources: set[tuple[int, int]],
    other_sources: set[tuple[int, int]],
    sustained: dict[
        tuple[int, int],
        list[tuple[float, int | None, tuple[int, int]]],
    ],
    notes: list[PianoRollNote],
    event_time: float,
) -> None:
    if enabled:
        target_sources.add(source)
        return
    target_sources.discard(source)
    if source in other_sources:
        return
    for start, note, note_source in sustained.pop(source, ()):
        _append_note(notes, start, event_time, note, note_source)


def _append_note(
    notes: list[PianoRollNote],
    start: float,
    end: float,
    note: int | None,
    source: tuple[int, int],
) -> None:
    if note is not None:
        notes.append(
            PianoRollNote(
                start=start,
                end=max(start, end),
                note=note,
                source=source,
            )
        )


def _event_enabled(
    event: MidiEvent,
    enabled_sources: set[tuple[int, int]] | None,
    enabled_channels: set[int] | None,
) -> bool:
    if event.track is not None and enabled_sources is not None:
        return (event.track, event.channel or 0) in enabled_sources
    if enabled_channels is not None:
        return (event.channel or 0) in enabled_channels
    return True


def _visual_note(
    event: MidiEvent,
    *,
    auto_fit_note_range: bool,
    fit_note_range: object = DEFAULT_FIT_NOTE_RANGE,
    transpose_semitones: int,
    octave_shift: int,
    chord_optimization_plan: ChordOptimizationPlan | None = None,
) -> int | None:
    if chord_optimization_plan is not None:
        planned, target = chord_optimization_plan.target_for(event)
        if planned:
            return (
                target
                if target is not None and PIANO_NOTE_MIN <= target <= PIANO_NOTE_MAX
                else None
            )
    shifted = shift_midi_note(event.note or 0, transpose_semitones, octave_shift)
    if shifted is None:
        return None
    if auto_fit_note_range:
        shifted = fit_note_to_range(shifted, fit_note_range)
        if shifted is None:
            return None
    return shifted if PIANO_NOTE_MIN <= shifted <= PIANO_NOTE_MAX else None
