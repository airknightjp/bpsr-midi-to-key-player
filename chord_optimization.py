from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from config import shift_midi_note
from midi_parser import MidiEvent
from playback_timing import MAX_PLAYBACK_SPEED_PERCENT, MIN_PLAYBACK_SPEED_PERCENT


CHORD_GROUP_THRESHOLD_SECONDS = 0.035
RAPID_RANGE_SWITCH_SECONDS = 0.25
PHRASE_BOUNDARY_SECONDS = 0.75
RANGE_SWITCH_COST = 2.5
RAPID_RANGE_SWITCH_COST = 8.0
OCTAVE_MOVE_COST = 4.0
OCCUPIED_KEY_COST = 900.0
VOICE_RANK_MOVE_COST = 0.08
LARGE_VOICE_GAP_SEMITONES = 16
LARGE_VOICE_GAP_COST = 0.22
PHRASE_RANGE_SWITCH_COST_FACTOR = 0.35
EXPRESSIVE_CHORD_MAX_OFFSET_SECONDS = 0.012

EventEnabledCallback = Callable[[MidiEvent], bool]
ProgressCallback = Callable[[int], None]
CancelCallback = Callable[[], bool]
EventTarget = tuple[bool, int | None]
SourceOwner = tuple[int, int, int]

PLAYABLE_WINDOWS = (
    (-1, 21, 47),
    (0, 48, 83),
    (1, 84, 108),
)
BASE_WINDOW = ((0, 48, 83),)


class ChordOptimizationCancelled(Exception):
    pass


@dataclass(frozen=True)
class ChordOptimizationPlan:
    event_targets: dict[int, int | None]
    event_timing_offsets: dict[int, float]

    def target_for(self, event: MidiEvent) -> EventTarget:
        event_id = id(event)
        if event_id not in self.event_targets:
            return False, event.note
        return True, self.event_targets[event_id]

    def timing_offset_for(self, event: MidiEvent) -> float | None:
        return self.event_timing_offsets.get(id(event))


@dataclass(frozen=True)
class _OptimizationEntry:
    event: MidiEvent
    note: int
    velocity: int


@dataclass(frozen=True)
class _GroupChoice:
    targets: tuple[int | None, ...]
    state: int
    cost: float


def build_chord_optimization_plan(
    events: Iterable[MidiEvent],
    *,
    auto_fit_note_range: bool,
    transpose_semitones: int = 0,
    octave_shift: int = 0,
    playback_speed_percent: int = 100,
    event_enabled: EventEnabledCallback | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_callback: CancelCallback | None = None,
) -> ChordOptimizationPlan:
    ordered_events = list(events)
    enabled = event_enabled or (lambda _event: True)
    playback_speed_ratio = max(
        MIN_PLAYBACK_SPEED_PERCENT,
        min(MAX_PLAYBACK_SPEED_PERCENT, int(playback_speed_percent)),
    ) / 100.0
    total_events = len(ordered_events)
    total_work = max(1, total_events * 2)
    last_progress = -1

    def report_progress(completed: int) -> None:
        nonlocal last_progress
        if cancel_callback is not None and cancel_callback():
            raise ChordOptimizationCancelled
        progress = min(100, int(completed * 100 / total_work))
        if progress_callback is not None and progress != last_progress:
            last_progress = progress
            progress_callback(progress)

    report_progress(0)
    shifted_notes: dict[int, int | None] = {}
    eligible_note_ons: list[MidiEvent] = []
    for index, event in enumerate(ordered_events):
        if event.note is not None:
            shifted_notes[id(event)] = shift_midi_note(
                event.note,
                transpose_semitones,
                octave_shift,
            )
        if (
            event.kind == "note_on"
            and event.note is not None
            and event.channel != 9
            and enabled(event)
        ):
            eligible_note_ons.append(event)
        report_progress(index + 1)
    onset_groups = _group_note_ons(eligible_note_ons)
    group_starts = {
        id(group[0]): group
        for group in onset_groups
        if group
    }

    targets: dict[int, int | None] = {}
    timing_offsets: dict[int, float] = {}
    active_by_owner: dict[SourceOwner, list[tuple[int | None, bool, float]]] = defaultdict(list)
    occupied_targets: Counter[int] = Counter()
    current_state = 0
    last_state_change_time: float | None = None
    silence_started_at: float | None = None
    previous_targets: tuple[int, ...] = ()

    for index, event in enumerate(ordered_events):
        event_id = id(event)
        group = group_starts.get(event_id)
        if group is not None:
            group_time = group[0].time / playback_speed_ratio
            phrase_boundary = bool(
                silence_started_at is not None
                and group_time - silence_started_at >= PHRASE_BOUNDARY_SECONDS
                and not occupied_targets
            )
            if phrase_boundary:
                previous_targets = ()
            group_targets, choice = _optimize_group(
                group,
                shifted_notes,
                auto_fit_note_range=auto_fit_note_range,
                current_state=current_state,
                last_state_change_time=last_state_change_time,
                previous_targets=previous_targets,
                occupied_targets=set(occupied_targets),
                playback_speed_ratio=playback_speed_ratio,
                phrase_boundary=phrase_boundary,
            )
            targets.update(group_targets)
            timing_offsets.update(_expressive_group_offsets(group, group_targets))
            if choice.state != current_state:
                current_state = choice.state
                last_state_change_time = group[0].time / playback_speed_ratio
            assigned_targets = tuple(
                target
                for target in choice.targets
                if target is not None
            )
            if assigned_targets:
                previous_targets = assigned_targets

        if event.kind == "note_on" and event.note is not None:
            target = targets.get(event_id, shifted_notes.get(event_id))
            targets[event_id] = target
            counted = bool(enabled(event) and target is not None)
            timing_offset = timing_offsets.setdefault(event_id, 0.0)
            owner = _source_owner(event)
            active_by_owner[owner].append((target, counted, timing_offset))
            if counted and target is not None:
                occupied_targets[target] += 1
                silence_started_at = None
            report_progress(total_events + index + 1)
            continue

        if event.kind == "note_off" and event.note is not None:
            owner = _source_owner(event)
            active = active_by_owner.get(owner)
            if active:
                target, counted, timing_offset = active.pop()
                if not active:
                    active_by_owner.pop(owner, None)
                if counted and target is not None:
                    occupied_targets[target] -= 1
                    if occupied_targets[target] <= 0:
                        occupied_targets.pop(target, None)
                    if not occupied_targets:
                        silence_started_at = event.time / playback_speed_ratio
            else:
                target = shifted_notes.get(event_id)
                timing_offset = 0.0
            targets[event_id] = target
            timing_offsets[event_id] = timing_offset

        report_progress(total_events + index + 1)

    report_progress(total_work)
    return ChordOptimizationPlan(targets, timing_offsets)


def _group_note_ons(note_ons: list[MidiEvent]) -> list[list[MidiEvent]]:
    groups: list[list[MidiEvent]] = []
    current: list[MidiEvent] = []
    anchor_time = 0.0
    for event in note_ons:
        if not current or event.time - anchor_time > CHORD_GROUP_THRESHOLD_SECONDS:
            if current:
                groups.append(current)
            current = [event]
            anchor_time = event.time
        else:
            current.append(event)
    if current:
        groups.append(current)
    return groups


def _optimize_group(
    group: list[MidiEvent],
    shifted_notes: dict[int, int | None],
    *,
    auto_fit_note_range: bool,
    current_state: int,
    last_state_change_time: float | None,
    previous_targets: tuple[int, ...],
    occupied_targets: set[int],
    playback_speed_ratio: float,
    phrase_boundary: bool,
) -> tuple[dict[int, int | None], _GroupChoice]:
    grouped_by_note: dict[int, list[MidiEvent]] = defaultdict(list)
    group_targets: dict[int, int | None] = {}
    for event in group:
        shifted_note = shifted_notes.get(id(event))
        if shifted_note is None:
            group_targets[id(event)] = None
            continue
        grouped_by_note[shifted_note].append(event)

    entries: list[_OptimizationEntry] = []
    group_order = {id(event): index for index, event in enumerate(group)}
    for note, same_pitch_events in grouped_by_note.items():
        representative = max(
            same_pitch_events,
            key=lambda event: (event.velocity or 0, -group_order[id(event)]),
        )
        entries.append(
            _OptimizationEntry(
                event=representative,
                note=note,
                velocity=representative.velocity or 64,
            )
        )
        for event in same_pitch_events:
            if event is not representative:
                group_targets[id(event)] = None
    entries.sort(key=lambda entry: entry.note)

    if not entries:
        return group_targets, _GroupChoice((), current_state, 0.0)

    if auto_fit_note_range:
        windows = BASE_WINDOW
    elif occupied_targets:
        windows = tuple(
            window
            for window in PLAYABLE_WINDOWS
            if window[0] == current_state
        )
    else:
        windows = PLAYABLE_WINDOWS

    choices: list[_GroupChoice] = []
    group_time = group[0].time / playback_speed_ratio
    for state, low, high in windows:
        targets, cost = _assign_to_window(
            entries,
            low,
            high,
            previous_targets,
            occupied_targets,
        )
        if state != current_state:
            switch_cost = RANGE_SWITCH_COST * playback_speed_ratio
            if phrase_boundary:
                switch_cost *= PHRASE_RANGE_SWITCH_COST_FACTOR
            cost += switch_cost
            if (
                last_state_change_time is not None
                and group_time - last_state_change_time < RAPID_RANGE_SWITCH_SECONDS
            ):
                cost += RAPID_RANGE_SWITCH_COST
        choices.append(_GroupChoice(targets, state, cost))

    choice = min(
        choices,
        key=lambda item: (
            item.cost,
            item.state != current_state,
            abs(item.state),
            item.state,
        ),
    )
    for entry, target in zip(entries, choice.targets):
        group_targets[id(entry.event)] = target
    return group_targets, choice


def _assign_to_window(
    entries: list[_OptimizationEntry],
    low: int,
    high: int,
    previous_targets: tuple[int, ...],
    occupied_targets: set[int],
) -> tuple[tuple[int | None, ...], float]:
    states: dict[int, tuple[float, tuple[int | None, ...]]] = {
        low - 1: (0.0, ())
    }
    last_index = len(entries) - 1
    previous_bass = previous_targets[0] if previous_targets else None
    previous_top = previous_targets[-1] if previous_targets else None

    for index, entry in enumerate(entries):
        next_states: dict[int, tuple[float, tuple[int | None, ...]]] = {}
        for last_target, (cost, assigned) in states.items():
            drop_cost = cost + _drop_cost(entry, index, last_index)
            _keep_best(
                next_states,
                last_target,
                drop_cost,
                assigned + (None,),
            )
            for target in _pitch_candidates(entry.note, low, high):
                if target <= last_target:
                    continue
                assign_cost = cost + _target_cost(
                    entry,
                    target,
                    index=index,
                    last_index=last_index,
                    previous_targets=previous_targets,
                    previous_bass=previous_bass,
                    previous_top=previous_top,
                    occupied_targets=occupied_targets,
                )
                if last_target >= low:
                    gap = target - last_target
                    if gap > LARGE_VOICE_GAP_SEMITONES:
                        assign_cost += (
                            gap - LARGE_VOICE_GAP_SEMITONES
                        ) * LARGE_VOICE_GAP_COST
                _keep_best(
                    next_states,
                    target,
                    assign_cost,
                    assigned + (target,),
                )
        states = next_states

    _last_target, (cost, targets) = min(
        states.items(),
        key=lambda item: (
            item[1][0],
            -sum(target is not None for target in item[1][1]),
            item[0],
        ),
    )
    return targets, cost


def _target_cost(
    entry: _OptimizationEntry,
    target: int,
    *,
    index: int,
    last_index: int,
    previous_targets: tuple[int, ...],
    previous_bass: int | None,
    previous_top: int | None,
    occupied_targets: set[int],
) -> float:
    cost = abs(target - entry.note) / 12.0 * OCTAVE_MOVE_COST
    if target in occupied_targets:
        cost += OCCUPIED_KEY_COST
    if previous_targets:
        nearest_distance = min(abs(target - previous) for previous in previous_targets)
        cost += min(nearest_distance, 24) * 0.12
        if target in previous_targets:
            cost -= 3.0
        if last_index > 0:
            previous_index = round(index * (len(previous_targets) - 1) / last_index)
            ranked_previous = previous_targets[previous_index]
            cost += min(abs(target - ranked_previous), 24) * VOICE_RANK_MOVE_COST
    if index == 0 and previous_bass is not None:
        cost += abs(target - previous_bass) * 0.25
    if index == last_index and previous_top is not None:
        cost += abs(target - previous_top) * 0.35
    return cost


def _drop_cost(entry: _OptimizationEntry, index: int, last_index: int) -> float:
    if index == 0 or index == last_index:
        return 1200.0 + entry.velocity
    return 260.0 + entry.velocity * 0.25


def _pitch_candidates(note: int, low: int, high: int) -> tuple[int, ...]:
    first = low + ((note - low) % 12)
    return tuple(range(first, high + 1, 12))


def _expressive_group_offsets(
    group: list[MidiEvent],
    group_targets: dict[int, int | None],
) -> dict[int, float]:
    offsets = {id(event): 0.0 for event in group}
    events_by_time: dict[float, list[MidiEvent]] = defaultdict(list)
    for event in group:
        if group_targets.get(id(event)) is not None:
            events_by_time[event.time].append(event)

    for simultaneous in events_by_time.values():
        if len(simultaneous) < 2:
            continue
        ordered = sorted(
            simultaneous,
            key=lambda event: (
                group_targets[id(event)],
                event.track if event.track is not None else -1,
                event.channel if event.channel is not None else -1,
            ),
        )
        highest_velocity = max(event.velocity or 64 for event in ordered)
        last_index = len(ordered) - 1
        for index, event in enumerate(ordered):
            if index == last_index:
                offsets[id(event)] = 0.0
                continue
            position = index / last_index
            innerness = 1.0 - abs(position * 2.0 - 1.0)
            velocity_delay = max(
                0.0,
                (highest_velocity - (event.velocity or 64)) / 127.0 * 0.003,
            )
            delay = 0.002 + innerness * 0.007 + velocity_delay
            offsets[id(event)] = min(EXPRESSIVE_CHORD_MAX_OFFSET_SECONDS, delay)
    return offsets


def _keep_best(
    states: dict[int, tuple[float, tuple[int | None, ...]]],
    last_target: int,
    cost: float,
    targets: tuple[int | None, ...],
) -> None:
    existing = states.get(last_target)
    candidate_key = (
        cost,
        -sum(target is not None for target in targets),
        tuple(-1 if target is None else target for target in targets),
    )
    if existing is None:
        states[last_target] = (cost, targets)
        return
    existing_key = (
        existing[0],
        -sum(target is not None for target in existing[1]),
        tuple(-1 if target is None else target for target in existing[1]),
    )
    if candidate_key < existing_key:
        states[last_target] = (cost, targets)


def _source_owner(event: MidiEvent) -> SourceOwner:
    return (
        event.track if event.track is not None else -1,
        event.channel if event.channel is not None else 0,
        event.note if event.note is not None else -1,
    )
