from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field

from midi_parser import MidiEvent


AUTO_SUSTAIN_EVENT_KIND = "auto_sustain"
CHORD_WINDOW_SECONDS = 0.035
PEDAL_DEPRESSION_DELAY_SECONDS = 0.075
PEDAL_RELEASE_LEAD_SECONDS = 0.025
MIN_PEDALLED_NOTE_SECONDS = 0.09
MIN_HARMONY_REPEDAL_SECONDS = 0.18
MAX_PEDAL_HOLD_SECONDS = 0.60
FINAL_RELEASE_TAIL_SECONDS = 0.18
MAX_RETAINED_NOTES = 6
PERCUSSION_CHANNEL = 9


@dataclass
class _PlannedNote:
    source: tuple[int, int]
    note: int
    onset: float
    release: float | None = None


@dataclass
class _RealtimeChannel:
    held: dict[int, int] = field(default_factory=dict)
    sustained: dict[int, float] = field(default_factory=dict)
    pedal_down: bool = False
    pedal_started_at: float = 0.0
    last_onset_at: float | None = None
    on_timer: threading.Timer | None = None
    off_timer: threading.Timer | None = None
    generation: int = 0


def plan_auto_sustain(events: list[MidiEvent]) -> list[MidiEvent]:
    """Add conservative, synthetic pedal events without replacing source CC64.

    The planner follows legato-pedal timing reported by Repp (1996): pedal
    changes are coordinated with note onsets, with release before a new attack
    and depression after it. Harmony-aware clearing follows the chord-linked
    pop-piano pedal representation used by Wu et al. (ISMIR 2021).
    """
    notes = _pair_notes(events)
    manual_channels = {
        event.channel
        for event in events
        if event.kind == "sustain" and event.channel is not None
    }
    by_source: dict[tuple[int, int], list[_PlannedNote]] = defaultdict(list)
    for note in notes:
        if note.source[1] not in manual_channels and note.source[1] != PERCUSSION_CHANNEL:
            by_source[note.source].append(note)

    transitions: list[MidiEvent] = []
    for source, source_notes in by_source.items():
        transitions.extend(_plan_source(source, source_notes))
    if not transitions:
        return list(events)

    combined = [*events, *transitions]
    combined.sort(key=_event_order)
    return combined


class RealtimeAutoSustain:
    """Causal auto-pedal controller for MIDI input that cannot see future notes."""

    def __init__(
        self,
        on_change: Callable[[int, bool], None],
        *,
        enabled: bool = False,
        time_source: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._on_change = on_change
        self._enabled = bool(enabled)
        self._time_source = time_source
        self._channels: dict[int, _RealtimeChannel] = {}
        self._manual_channels: set[int] = set()
        self._lock = threading.RLock()

    def set_enabled(self, enabled: bool) -> None:
        changes: list[tuple[int, bool]] = []
        with self._lock:
            enabled = bool(enabled)
            if self._enabled == enabled:
                return
            self._enabled = enabled
            if not enabled:
                changes = self._reset_locked(clear_manual=False)
        self._emit(changes)

    def note_on(self, channel: int, note: int, received_at: float | None = None) -> None:
        if channel == PERCUSSION_CHANNEL:
            return
        now = self._now(received_at)
        changes: list[tuple[int, bool]] = []
        with self._lock:
            if not self._enabled or channel in self._manual_channels:
                return
            state = self._channels.setdefault(channel, _RealtimeChannel())
            same_attack = (
                state.last_onset_at is not None
                and now - state.last_onset_at <= CHORD_WINDOW_SECONDS
            )
            retained_notes = list(state.sustained)
            if not same_attack:
                retained_notes.extend(state.held)
            if state.pedal_down and not same_attack and _should_clear_pedal(
                retained_notes,
                [note],
                state.pedal_started_at,
                now,
            ):
                self._set_pedal_locked(channel, state, False)
                changes.append((channel, False))
            state.sustained.pop(note, None)
            state.held[note] = state.held.get(note, 0) + 1
            state.last_onset_at = now
            if not state.pedal_down and state.on_timer is None:
                self._schedule_on_locked(channel, state)
        self._emit(changes)

    def note_off(self, channel: int, note: int, received_at: float | None = None) -> None:
        now = self._now(received_at)
        with self._lock:
            state = self._channels.get(channel)
            if state is None:
                return
            count = state.held.get(note, 0)
            if count <= 1:
                state.held.pop(note, None)
            else:
                state.held[note] = count - 1
            if state.pedal_down:
                state.sustained[note] = now
            elif not state.held:
                self._cancel_timer(state.on_timer)
                state.on_timer = None

    def manual_sustain(self, channel: int) -> None:
        changes: list[tuple[int, bool]] = []
        with self._lock:
            self._manual_channels.add(channel)
            state = self._channels.get(channel)
            if state is not None:
                self._cancel_timers_locked(state)
                if state.pedal_down:
                    state.pedal_down = False
                    changes.append((channel, False))
                state.sustained.clear()
        self._emit(changes)

    def reset(self) -> None:
        with self._lock:
            changes = self._reset_locked(clear_manual=True)
        self._emit(changes)

    def _schedule_on_locked(self, channel: int, state: _RealtimeChannel) -> None:
        state.generation += 1
        generation = state.generation
        timer = threading.Timer(
            PEDAL_DEPRESSION_DELAY_SECONDS,
            self._activate_after_delay,
            args=(channel, generation),
        )
        timer.daemon = True
        state.on_timer = timer
        timer.start()

    def _activate_after_delay(self, channel: int, generation: int) -> None:
        change = False
        with self._lock:
            state = self._channels.get(channel)
            if state is None or state.generation != generation:
                return
            state.on_timer = None
            if (
                not self._enabled
                or channel in self._manual_channels
                or not state.held
                or state.pedal_down
            ):
                return
            state.pedal_down = True
            state.pedal_started_at = self._time_source()
            state.off_timer = threading.Timer(
                MAX_PEDAL_HOLD_SECONDS,
                self._release_after_limit,
                args=(channel, generation),
            )
            state.off_timer.daemon = True
            state.off_timer.start()
            change = True
        if change:
            self._on_change(channel, True)

    def _release_after_limit(self, channel: int, generation: int) -> None:
        change = False
        with self._lock:
            state = self._channels.get(channel)
            if state is None or state.generation != generation:
                return
            state.off_timer = None
            if state.pedal_down:
                state.pedal_down = False
                state.sustained.clear()
                change = True
        if change:
            self._on_change(channel, False)

    def _set_pedal_locked(
        self,
        _channel: int,
        state: _RealtimeChannel,
        enabled: bool,
    ) -> None:
        state.pedal_down = enabled
        if not enabled:
            state.sustained.clear()
            self._cancel_timer(state.off_timer)
            state.off_timer = None
            state.generation += 1

    def _reset_locked(self, *, clear_manual: bool) -> list[tuple[int, bool]]:
        changes: list[tuple[int, bool]] = []
        for channel, state in self._channels.items():
            self._cancel_timers_locked(state)
            if state.pedal_down:
                changes.append((channel, False))
        self._channels.clear()
        if clear_manual:
            self._manual_channels.clear()
        return changes

    def _cancel_timers_locked(self, state: _RealtimeChannel) -> None:
        self._cancel_timer(state.on_timer)
        self._cancel_timer(state.off_timer)
        state.on_timer = None
        state.off_timer = None
        state.generation += 1

    @staticmethod
    def _cancel_timer(timer: threading.Timer | None) -> None:
        if timer is not None:
            timer.cancel()

    def _emit(self, changes: list[tuple[int, bool]]) -> None:
        for channel, enabled in changes:
            self._on_change(channel, enabled)

    def _now(self, received_at: float | None) -> float:
        return self._time_source() if received_at is None else float(received_at)


def _pair_notes(events: list[MidiEvent]) -> list[_PlannedNote]:
    active: dict[tuple[int, int, int], deque[_PlannedNote]] = defaultdict(deque)
    notes: list[_PlannedNote] = []
    for event in events:
        if event.channel is None or event.note is None:
            continue
        source = _source(event)
        owner = (source[0], source[1], event.note)
        if event.kind == "note_on":
            note = _PlannedNote(source, event.note, event.time)
            active[owner].append(note)
            notes.append(note)
        elif event.kind == "note_off" and active[owner]:
            active[owner].popleft().release = event.time
    return notes


def _plan_source(source: tuple[int, int], notes: list[_PlannedNote]) -> list[MidiEvent]:
    groups = _group_notes(notes)
    transitions: list[MidiEvent] = []
    retained: list[_PlannedNote] = []
    pedal_down = False
    pedal_started_at = 0.0
    pedal_expires_at = 0.0

    for group in groups:
        start = min(note.onset for note in group)
        eligible = [
            note
            for note in group
            if note.release is not None
            and note.release - note.onset >= MIN_PEDALLED_NOTE_SECONDS
        ]
        if pedal_down and pedal_expires_at <= start:
            transitions.append(_transition(source, pedal_expires_at, False))
            pedal_down = False
            retained.clear()

        stale = [note.note for note in retained]
        incoming = [note.note for note in group]
        if pedal_down and (
            not eligible
            or _should_clear_pedal(stale, incoming, pedal_started_at, start)
        ):
            release_at = max(pedal_started_at, start - PEDAL_RELEASE_LEAD_SECONDS)
            transitions.append(_transition(source, release_at, False))
            pedal_down = False
            retained.clear()

        if not pedal_down and eligible:
            longest = max((note.release or note.onset) - note.onset for note in eligible)
            depression_delay = min(PEDAL_DEPRESSION_DELAY_SECONDS, longest * 0.45)
            pedal_started_at = start + depression_delay
            pedal_expires_at = pedal_started_at + MAX_PEDAL_HOLD_SECONDS
            transitions.append(_transition(source, pedal_started_at, True))
            pedal_down = True
        if pedal_down:
            retained.extend(
                note
                for note in group
                if note.release is not None and note.release > pedal_started_at
            )

    if pedal_down:
        last_release = max(
            (note.release or note.onset for note in retained),
            default=pedal_started_at,
        )
        transitions.append(
            _transition(
                source,
                min(pedal_expires_at, last_release + FINAL_RELEASE_TAIL_SECONDS),
                False,
            )
        )
    return _deduplicate_transitions(transitions)


def _group_notes(notes: list[_PlannedNote]) -> list[list[_PlannedNote]]:
    groups: list[list[_PlannedNote]] = []
    for note in sorted(notes, key=lambda item: (item.onset, item.note)):
        if not groups or note.onset - groups[-1][0].onset > CHORD_WINDOW_SECONDS:
            groups.append([note])
        else:
            groups[-1].append(note)
    return groups


def _should_clear_pedal(
    sustained_notes: list[int],
    incoming_notes: list[int],
    pedal_started_at: float,
    now: float,
) -> bool:
    if not sustained_notes:
        return False
    pedal_age = now - pedal_started_at
    if pedal_age >= MAX_PEDAL_HOLD_SECONDS:
        return True
    if len(sustained_notes) + len(incoming_notes) > MAX_RETAINED_NOTES:
        return True

    conflicts = 0
    for old in sustained_notes:
        for new in incoming_notes:
            if old == new:
                continue
            interval = abs(new - old) % 12
            distance = min(interval, 12 - interval)
            if distance == 1:
                return True
            if min(old, new) < 48 and distance not in {0, 5}:
                return True
            if distance in {2, 6}:
                conflicts += 1
    if conflicts >= max(2, len(incoming_notes)):
        return True

    if pedal_age >= MIN_HARMONY_REPEDAL_SECONDS:
        retained_pitch_classes = {note % 12 for note in sustained_notes}
        incoming_pitch_classes = {note % 12 for note in incoming_notes}
        if retained_pitch_classes != incoming_pitch_classes:
            if len(retained_pitch_classes) > 1 or len(incoming_pitch_classes) > 1:
                return True
            old_pitch = sustained_notes[-1]
            new_pitch = incoming_notes[0]
            pitch_class_distance = abs(new_pitch - old_pitch) % 12
            pitch_class_distance = min(pitch_class_distance, 12 - pitch_class_distance)
            if pitch_class_distance >= 3:
                return True

    combined = sustained_notes + incoming_notes
    return bool(combined) and max(combined) - min(combined) > 36


def _transition(source: tuple[int, int], at: float, enabled: bool) -> MidiEvent:
    track, channel = source
    return MidiEvent(
        time=max(0.0, at),
        kind=AUTO_SUSTAIN_EVENT_KIND,
        track=None if track < 0 else track,
        channel=channel,
        value=127 if enabled else 0,
    )


def _deduplicate_transitions(events: list[MidiEvent]) -> list[MidiEvent]:
    result: list[MidiEvent] = []
    state = False
    for event in sorted(events, key=lambda item: (item.time, item.value or 0)):
        enabled = bool((event.value or 0) >= 64)
        if enabled == state:
            continue
        result.append(event)
        state = enabled
    return result


def _source(event: MidiEvent) -> tuple[int, int]:
    return (event.track if event.track is not None else -1, event.channel or 0)


def _event_order(event: MidiEvent) -> tuple[float, int, int, int]:
    priority = {
        AUTO_SUSTAIN_EVENT_KIND: 0,
        "note_off": 1,
        "sustain": 2,
        "note_on": 3,
    }.get(event.kind, 4)
    return (
        event.time,
        priority,
        event.track if event.track is not None else -1,
        event.channel if event.channel is not None else -1,
    )
