from __future__ import annotations

import random
import threading
import time
from collections import defaultdict
from collections.abc import Callable

from auto_sustain import AUTO_SUSTAIN_EVENT_KIND, plan_auto_sustain
from chord_optimization import ChordOptimizationPlan
from chord_optimization_planner import ChordOptimizationPlanner, ChordOptimizationRequest
from config import (
    MAX_OCTAVE_SHIFT,
    MAX_TRANSPOSE_SEMITONES,
    MIN_OCTAVE_SHIFT,
    MIN_TRANSPOSE_SEMITONES,
    OCTAVE_DOWN_KEY,
    OCTAVE_SWITCH_SETTLE_SECONDS,
    OCTAVE_UP_KEY,
    SUSTAIN_KEY,
    fit_note_to_base_range,
    midi_note_to_key,
    normalized_key_bindings,
    shift_midi_note,
)
from keyboard_output import KeyboardOutput
from midi_parser import MidiEvent
from playback_timing import PlaybackClock, PlaybackTimeline, prepare_playback_events
from repeat_guard import RapidRepeatGuard


StateCallback = Callable[[str], None]
CompletionCallback = Callable[[], None]
ErrorCallback = Callable[[str], None]
PositionCallback = Callable[[float], None]
OptimizationProgressCallback = Callable[[int | None], None]
CountdownCallback = Callable[[int], None]
OutputNoteCallback = Callable[[int, bool], None]
OutputSourceNoteCallback = Callable[[int, int, int, bool], None]
EnabledChannelsCallback = Callable[[], set[int]]
EnabledSourcesCallback = Callable[[], set[tuple[int, int]]]
NoteOwner = tuple[int, int, int]


class MidiKeyboardPlayer:
    def __init__(
        self,
        output: KeyboardOutput,
        on_state: StateCallback | None = None,
        on_complete: CompletionCallback | None = None,
        on_error: ErrorCallback | None = None,
        on_position: PositionCallback | None = None,
        on_optimization_progress: OptimizationProgressCallback | None = None,
        on_output_note: OutputNoteCallback | None = None,
        on_output_source_note: OutputSourceNoteCallback | None = None,
        enabled_channels: EnabledChannelsCallback | None = None,
        enabled_sources: EnabledSourcesCallback | None = None,
        auto_fit_note_range: bool = False,
        transpose_semitones: int = 0,
        octave_shift: int = 0,
        humanize_timing: bool = False,
        chord_optimization: bool = False,
        chord_strum: bool = False,
        auto_sustain: bool = False,
        repeat_prevention: bool = False,
        playback_speed_percent: int = 100,
        key_bindings: dict[int, str] | None = None,
        sustain_key: str = SUSTAIN_KEY,
        octave_down_key: str = OCTAVE_DOWN_KEY,
        octave_up_key: str = OCTAVE_UP_KEY,
    ):
        self.output = output
        self.on_state = on_state or (lambda _state: None)
        self.on_complete = on_complete or (lambda: None)
        self.on_error = on_error or (lambda _message: None)
        self.on_position = on_position or (lambda _position: None)
        self.on_optimization_progress = (
            on_optimization_progress or (lambda _progress: None)
        )
        self.on_output_note = on_output_note or (lambda _note, _pressed: None)
        self.on_output_source_note = (
            on_output_source_note
            or (lambda _note, _track, _channel, _pressed: None)
        )
        self.enabled_channels = enabled_channels
        self.enabled_sources = enabled_sources
        self.auto_fit_note_range = auto_fit_note_range
        self.transpose_semitones = max(
            MIN_TRANSPOSE_SEMITONES,
            min(MAX_TRANSPOSE_SEMITONES, int(transpose_semitones)),
        )
        self.note_octave_shift = max(
            MIN_OCTAVE_SHIFT,
            min(MAX_OCTAVE_SHIFT, int(octave_shift)),
        )
        self.humanize_timing = humanize_timing
        self.chord_optimization = bool(chord_optimization)
        self.chord_strum = chord_strum
        self.auto_sustain = auto_sustain
        self._repeat_guard = RapidRepeatGuard(enabled=repeat_prevention)
        self.playback_speed_percent = playback_speed_percent
        self.key_bindings = normalized_key_bindings(key_bindings)
        self.sustain_key = str(sustain_key)
        self.octave_down_key = str(octave_down_key)
        self.octave_up_key = str(octave_up_key)
        self._config_lock = threading.Lock()
        self._random = random.Random()
        self._clock: PlaybackClock | None = None
        self._stop_event = threading.Event()
        self._release_requested = threading.Event()
        self._thread: threading.Thread | None = None
        self._active_notes: dict[NoteOwner, list[str]] = defaultdict(list)
        self._active_key_owner: dict[str, NoteOwner] = {}
        self._active_key_note: dict[str, int] = {}
        self._sustain_channels: set[tuple[int, int]] = set()
        self._auto_sustain_channels: set[tuple[int, int]] = set()
        self._sustain_lock = threading.RLock()
        self._octave_shift = 0
        self._chord_optimization_plan: ChordOptimizationPlan | None = None
        self._chord_optimization_plan_auto_fit: bool | None = None
        self._chord_optimization_plan_speed: int | None = None
        self._chord_optimization_plan_transpose: int | None = None
        self._chord_optimization_plan_octave: int | None = None
        self._chord_optimization_plan_dirty = True
        self._optimization_generation = 0
        self._current_events: list[MidiEvent] | None = None
        self._optimization_planner = ChordOptimizationPlanner(
            request_provider=self._optimization_request,
            request_is_current=self._optimization_request_is_current,
            commit_plan=self._commit_optimization_plan,
            should_stop=self._stop_event.is_set,
            on_progress=self.on_optimization_progress,
        )

    @property
    def is_playing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def current_chord_optimization_plan(self) -> ChordOptimizationPlan | None:
        with self._config_lock:
            if not self._chord_optimization_plan_is_current_locked():
                return None
            return self._chord_optimization_plan

    def play(self, events: list[MidiEvent], countdown_seconds: int = 0, start_time: float = 0.0) -> None:
        self.play_with_countdown_sound(events, countdown_seconds, start_time, None)

    def play_with_countdown_sound(
        self,
        events: list[MidiEvent],
        countdown_seconds: int = 0,
        start_time: float = 0.0,
        on_countdown_tick: CountdownCallback | None = None,
    ) -> None:
        if self.is_playing:
            raise RuntimeError("Already playing")
        self._stop_event.clear()
        self._release_requested.clear()
        self._repeat_guard.reset()
        with self._config_lock:
            self._current_events = events
            self._mark_chord_optimization_dirty_locked()
        self._thread = threading.Thread(
            target=self._run,
            args=(events, countdown_seconds, max(0.0, start_time), on_countdown_tick),
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def request_release_all(self) -> None:
        self._release_requested.set()

    def set_dry_run(self, enabled: bool) -> None:
        self.output.set_dry_run(enabled)
        self._release_requested.set()

    def set_auto_fit_note_range(self, enabled: bool) -> None:
        with self._config_lock:
            enabled = bool(enabled)
            if self.auto_fit_note_range == enabled:
                return
            self.auto_fit_note_range = enabled
            self._mark_chord_optimization_dirty_locked()
            self._release_requested.set()
        self._schedule_chord_optimization()

    def set_note_shift(self, transpose_semitones: int, octave_shift: int) -> None:
        transpose_semitones = max(
            MIN_TRANSPOSE_SEMITONES,
            min(MAX_TRANSPOSE_SEMITONES, int(transpose_semitones)),
        )
        octave_shift = max(MIN_OCTAVE_SHIFT, min(MAX_OCTAVE_SHIFT, int(octave_shift)))
        with self._config_lock:
            if (
                self.transpose_semitones == transpose_semitones
                and self.note_octave_shift == octave_shift
            ):
                return
            self.transpose_semitones = transpose_semitones
            self.note_octave_shift = octave_shift
            self._mark_chord_optimization_dirty_locked()
            self._release_requested.set()
        self._schedule_chord_optimization()

    def set_humanize_timing(self, enabled: bool) -> None:
        with self._config_lock:
            self.humanize_timing = bool(enabled)

    def _humanize_timing_enabled(self) -> bool:
        with self._config_lock:
            return self.humanize_timing

    def set_chord_optimization(self, enabled: bool) -> None:
        with self._config_lock:
            enabled = bool(enabled)
            if self.chord_optimization == enabled:
                return
            self.chord_optimization = enabled
            self._mark_chord_optimization_dirty_locked()
            self._release_requested.set()
        if enabled:
            self._schedule_chord_optimization()
        else:
            self.on_optimization_progress(None)

    def request_chord_optimization_refresh(self) -> None:
        with self._config_lock:
            self._mark_chord_optimization_dirty_locked()
        self._schedule_chord_optimization()

    def set_chord_strum(self, enabled: bool) -> None:
        with self._config_lock:
            self.chord_strum = bool(enabled)

    def _chord_strum_enabled(self) -> bool:
        with self._config_lock:
            return self.chord_strum

    def set_auto_sustain(self, enabled: bool) -> None:
        with self._config_lock:
            self.auto_sustain = bool(enabled)
        if not enabled:
            self._clear_auto_sustain()

    def _auto_sustain_enabled(self) -> bool:
        with self._config_lock:
            return self.auto_sustain

    def set_repeat_prevention(self, enabled: bool) -> None:
        self._repeat_guard.set_enabled(enabled)

    def set_playback_speed(self, speed_percent: int) -> None:
        with self._config_lock:
            speed_percent = int(speed_percent)
            changed = self.playback_speed_percent != speed_percent
            if changed:
                self.playback_speed_percent = speed_percent
                self._mark_chord_optimization_dirty_locked()
            clock = self._clock
        if clock is not None:
            clock.set_speed_percent(speed_percent)
        if changed:
            self._schedule_chord_optimization()

    def set_key_bindings(self, key_bindings: dict[int, str]) -> None:
        with self._config_lock:
            self.key_bindings = normalized_key_bindings(key_bindings)
            self._release_requested.set()

    def set_special_key_bindings(
        self,
        sustain_key: str,
        octave_down_key: str,
        octave_up_key: str,
    ) -> None:
        with self._config_lock:
            self.sustain_key = str(sustain_key)
            self.octave_down_key = str(octave_down_key)
            self.octave_up_key = str(octave_up_key)
            self._release_requested.set()

    def wait_until_stopped(self, timeout: float = 1.0) -> None:
        if self._thread is None or threading.current_thread() is self._thread:
            return
        self._thread.join(timeout)
        self._optimization_planner.wait(timeout=0.2)

    def current_position(self) -> float | None:
        with self._config_lock:
            clock = self._clock
        return clock.position() if clock is not None else None

    def _run(
        self,
        events: list[MidiEvent],
        countdown_seconds: int,
        start_time: float,
        on_countdown_tick: CountdownCallback | None,
    ) -> None:
        completed_normally = False
        try:
            self._reset_external_octave_to_base_if_needed()
            for remaining in range(countdown_seconds, 0, -1):
                if self._stop_event.is_set():
                    return
                self.on_state(f"playing in {remaining}")
                if on_countdown_tick is not None:
                    on_countdown_tick(remaining)
                if self._stop_event.wait(1.0):
                    return

            self._refresh_chord_optimization_plan(events, force=True)
            if self._stop_event.is_set():
                return
            self.on_state("playing")
            self.on_position(start_time)
            with self._config_lock:
                speed_percent = self.playback_speed_percent
            clock = PlaybackClock(start_time, speed_percent)
            with self._config_lock:
                self._clock = clock
            next_position_report = 0.0
            timeline = PlaybackTimeline(start_time, self._random)
            planned_events = plan_auto_sustain(events)
            for scheduled in prepare_playback_events(
                planned_events,
                self._random,
                self._chord_optimization_timing_offset,
            ):
                event = scheduled.event
                self._consume_release_request()
                if event.time < start_time:
                    continue
                if self._stop_event.is_set():
                    break

                scheduled_time = event.time
                while True:
                    self._consume_release_request()
                    if self._stop_event.is_set():
                        break
                    scheduled_time = timeline.scheduled_time(
                        scheduled,
                        self._humanize_timing_enabled(),
                        self._chord_strum_enabled(),
                        self._chord_optimization_timing_offset(event),
                    )
                    delay = clock.delay_until(scheduled_time)
                    if delay <= 0:
                        break
                    now = time.perf_counter()
                    if now >= next_position_report:
                        self.on_position(clock.position())
                        next_position_report = now + 0.1
                    self._stop_event.wait(min(delay, 0.005))

                if self._stop_event.is_set():
                    break
                timeline.mark_emitted(scheduled_time)
                self._consume_release_request()
                self.on_position(clock.position())
                self._handle_event(event)
            completed_normally = not self._stop_event.is_set()
        except Exception as exc:
            try:
                self.on_error(str(exc) or exc.__class__.__name__)
            except Exception:
                pass
        finally:
            for cleanup in (
                self._release_active_note_keys,
                lambda: self._move_to_octave_shift(0),
                self.output.release_all,
            ):
                try:
                    cleanup()
                except Exception:
                    pass
            self._active_notes.clear()
            self._active_key_owner.clear()
            self._active_key_note.clear()
            self._sustain_channels.clear()
            self._auto_sustain_channels.clear()
            self._octave_shift = 0
            with self._config_lock:
                self._clock = None
                self._current_events = None
                self._optimization_generation += 1
            self.on_state("stopped")
            if completed_normally:
                self.on_complete()

    def _consume_release_request(self) -> None:
        if not self._release_requested.is_set():
            return
        self._release_requested.clear()
        self._release_active_note_keys()
        self.output.release_all()
        self._sustain_channels.clear()
        self._auto_sustain_channels.clear()

    def _handle_event(
        self,
        event: MidiEvent,
        emitted_at: float | None = None,
    ) -> None:
        if event.channel is not None:
            if not self._event_is_enabled(event):
                if event.kind == "note_off" and event.note is not None:
                    self._release_note(event.track, event.channel, event.note)
                elif event.kind == "sustain" and event.value is not None and event.value < 64:
                    self._set_sustain(event.track, event.channel, enabled=False)
                elif (
                    event.kind == AUTO_SUSTAIN_EVENT_KIND
                    and event.value is not None
                    and event.value < 64
                ):
                    self._set_sustain(event.track, event.channel, enabled=False, automatic=True)
                return

        if event.kind == "note_on" and event.note is not None:
            note = self._playable_event_note(event)
            if note is None:
                return
            with self._config_lock:
                key_bindings = self.key_bindings
            mapping = midi_note_to_key(note, key_bindings)
            if mapping is None:
                return
            repeat_token = (mapping.octave_shift, mapping.key)
            if self._repeat_guard.should_suppress(repeat_token, emitted_at):
                return

            self._move_to_octave_shift(mapping.octave_shift)
            owner = self._note_owner(event.track, event.channel, event.note)
            self._press_note_key(
                mapping.key,
                owner=owner,
                output_note=mapping.note,
            )
            self._active_notes[owner].append(mapping.key)

        elif event.kind == "note_off" and event.note is not None:
            self._release_note(event.track, event.channel or 0, event.note)

        elif event.kind == "sustain" and event.value is not None:
            if event.value >= 64:
                self._set_sustain(event.track, event.channel or 0, enabled=True)
            else:
                self._set_sustain(event.track, event.channel or 0, enabled=False)

        elif event.kind == AUTO_SUSTAIN_EVENT_KIND and event.value is not None:
            if not self._auto_sustain_enabled():
                return
            enabled = event.value >= 64
            self._set_sustain(event.track, event.channel or 0, enabled, automatic=True)

    def _event_is_enabled(self, event: MidiEvent) -> bool:
        if event.channel is None:
            return True
        if event.track is not None and self.enabled_sources is not None:
            return (event.track, event.channel) in self.enabled_sources()
        if self.enabled_channels is not None:
            return event.channel in self.enabled_channels()
        return True

    def _playable_note(self, note: int) -> int | None:
        with self._config_lock:
            shifted_note = shift_midi_note(
                note,
                self.transpose_semitones,
                self.note_octave_shift,
            )
            auto_fit_note_range = self.auto_fit_note_range
        if shifted_note is None:
            return None
        if auto_fit_note_range:
            return fit_note_to_base_range(shifted_note)
        return shifted_note

    def _playable_event_note(self, event: MidiEvent) -> int | None:
        with self._config_lock:
            if self._chord_optimization_plan_is_current_locked():
                plan = self._chord_optimization_plan
                if plan is not None:
                    planned, target = plan.target_for(event)
                    if planned:
                        return target
        if event.note is None:
            return None
        return self._playable_note(event.note)

    def _chord_optimization_timing_offset(self, event: MidiEvent) -> float | None:
        with self._config_lock:
            if not self._chord_optimization_plan_is_current_locked():
                return None
            plan = self._chord_optimization_plan
            return None if plan is None else plan.timing_offset_for(event)

    def _refresh_chord_optimization_plan(
        self,
        events: list[MidiEvent],
        force: bool = False,
    ) -> None:
        with self._config_lock:
            if self._current_events is not events:
                self._current_events = events
                self._mark_chord_optimization_dirty_locked()
        if force:
            self._optimization_planner.build_now()
        else:
            self._schedule_chord_optimization()

    def _mark_chord_optimization_dirty_locked(self) -> None:
        self._chord_optimization_plan_dirty = True
        self._optimization_generation += 1

    def _schedule_chord_optimization(self) -> None:
        with self._config_lock:
            should_schedule = (
                self._current_events is not None
                and self.chord_optimization
                and self._chord_optimization_plan_dirty
            )
        if should_schedule:
            self._optimization_planner.schedule()

    def _optimization_request(self) -> ChordOptimizationRequest | None:
        with self._config_lock:
            if (
                not self.chord_optimization
                or not self._chord_optimization_plan_dirty
                or self._current_events is None
            ):
                return None
            return ChordOptimizationRequest(
                generation=self._optimization_generation,
                events=self._current_events,
                options={
                    "auto_fit_note_range": self.auto_fit_note_range,
                    "transpose_semitones": self.transpose_semitones,
                    "octave_shift": self.note_octave_shift,
                    "playback_speed_percent": self.playback_speed_percent,
                    "event_enabled": self._event_is_enabled,
                },
            )

    def _optimization_request_is_current(self, generation: int) -> bool:
        with self._config_lock:
            return self._optimization_request_is_current_locked(generation)

    def _commit_optimization_plan(
        self,
        request: ChordOptimizationRequest,
        plan: ChordOptimizationPlan,
    ) -> bool:
        with self._config_lock:
            if not self._optimization_request_is_current_locked(request.generation):
                return False
            self._chord_optimization_plan = plan
            self._chord_optimization_plan_auto_fit = bool(
                request.options["auto_fit_note_range"]
            )
            self._chord_optimization_plan_speed = int(
                request.options["playback_speed_percent"]
            )
            self._chord_optimization_plan_transpose = int(
                request.options["transpose_semitones"]
            )
            self._chord_optimization_plan_octave = int(request.options["octave_shift"])
            self._chord_optimization_plan_dirty = False
            return True

    def _optimization_request_is_current_locked(self, generation: int) -> bool:
        return (
            not self._stop_event.is_set()
            and self.chord_optimization
            and self._current_events is not None
            and self._optimization_generation == generation
        )

    def _chord_optimization_plan_is_current_locked(self) -> bool:
        return (
            self.chord_optimization
            and self._chord_optimization_plan is not None
            and self._chord_optimization_plan_auto_fit == self.auto_fit_note_range
            and self._chord_optimization_plan_speed == self.playback_speed_percent
            and self._chord_optimization_plan_transpose == self.transpose_semitones
            and self._chord_optimization_plan_octave == self.note_octave_shift
        )

    def _move_to_octave_shift(self, target_shift: int) -> None:
        changed = target_shift != self._octave_shift
        if changed:
            self._release_active_note_keys()
        while self._octave_shift < target_shift:
            self.output.tap(self.octave_up_key)
            self._octave_shift += 1
        while self._octave_shift > target_shift:
            self.output.tap(self.octave_down_key)
            self._octave_shift -= 1
        if changed:
            time.sleep(OCTAVE_SWITCH_SETTLE_SECONDS)

    def _reset_external_octave_to_base(self) -> None:
        self.output.tap(self.octave_down_key)
        self.output.tap(self.octave_down_key)
        self.output.tap(self.octave_up_key)
        self._octave_shift = 0
        time.sleep(OCTAVE_SWITCH_SETTLE_SECONDS)

    def _reset_external_octave_to_base_if_needed(self) -> None:
        with self._config_lock:
            auto_fit_note_range = self.auto_fit_note_range
        if auto_fit_note_range:
            self._octave_shift = 0
            return
        self._reset_external_octave_to_base()

    def _press_note_key(
        self,
        key: str,
        owner: NoteOwner,
        output_note: int,
    ) -> None:
        if key in self._active_key_owner:
            self.output.release(key)
            self._emit_key_released(key)
            time.sleep(0.01)
            self._remove_active_key(key)
        self.output.press(key)
        self._active_key_owner[key] = owner
        self._active_key_note[key] = output_note
        self._emit_output_note(output_note, True, owner)

    def _release_note_key(self, key: str, owner: NoteOwner) -> None:
        current_owner = self._active_key_owner.get(key)
        if current_owner is not None and current_owner != owner:
            output_note = self._active_key_note.get(key)
            self.output.release(key)
            if output_note is not None:
                self._emit_output_note(output_note, False, current_owner)
            time.sleep(0.01)
            self.output.press(key)
            if output_note is not None:
                self._emit_output_note(output_note, True, current_owner)
            return
        self._active_key_owner.pop(key, None)
        self.output.release(key)
        self._emit_key_released(key, current_owner)
        self._remove_active_key(key)

    def _emit_key_released(
        self,
        key: str,
        owner: NoteOwner | None = None,
    ) -> None:
        output_note = self._active_key_note.get(key)
        if output_note is not None:
            self._emit_output_note(
                output_note,
                False,
                owner or self._active_key_owner.get(key),
            )

    def _emit_output_note(
        self,
        note: int,
        pressed: bool,
        owner: NoteOwner | None = None,
    ) -> None:
        try:
            self.on_output_note(note, pressed)
        except Exception:
            pass
        if owner is not None:
            try:
                self.on_output_source_note(
                    note,
                    owner[0],
                    owner[1],
                    pressed,
                )
            except Exception:
                pass

    @staticmethod
    def _note_owner(track: int | None, channel: int | None, note: int) -> NoteOwner:
        return (track if track is not None else -1, channel or 0, note)

    def _release_note(self, track: int | None, channel: int, note: int) -> str | None:
        owner = self._note_owner(track, channel, note)
        keys = self._active_notes.get(owner)
        if not keys:
            return None
        key = keys.pop()
        if not keys:
            self._active_notes.pop(owner, None)
        self._release_note_key(key, owner=owner)
        return key

    def _set_sustain(
        self,
        track: int | None,
        channel: int,
        enabled: bool,
        *,
        automatic: bool = False,
    ) -> None:
        source = (track if track is not None else -1, channel)
        with self._sustain_lock:
            was_inactive = not (self._sustain_channels or self._auto_sustain_channels)
            target = self._auto_sustain_channels if automatic else self._sustain_channels
            if enabled:
                target.add(source)
            else:
                target.discard(source)
            is_inactive = not (self._sustain_channels or self._auto_sustain_channels)
        if enabled and was_inactive:
            self.output.press(self.sustain_key)
        elif not enabled and is_inactive:
            self.output.release(self.sustain_key)

    def _clear_auto_sustain(self) -> None:
        with self._sustain_lock:
            if not self._auto_sustain_channels:
                return
            self._auto_sustain_channels.clear()
            should_release = not self._sustain_channels
        if should_release:
            self.output.release(self.sustain_key)

    def _remove_active_key(self, key: str) -> None:
        self._active_key_owner.pop(key, None)
        self._active_key_note.pop(key, None)
        for note, keys in list(self._active_notes.items()):
            remaining = [active_key for active_key in keys if active_key != key]
            if remaining:
                self._active_notes[note] = remaining
            else:
                self._active_notes.pop(note, None)

    def _release_active_note_keys(self) -> None:
        released: set[str] = set()
        for keys in self._active_notes.values():
            for key in keys:
                if key not in released:
                    self.output.release(key)
                    self._emit_key_released(key)
                    released.add(key)
        self._active_notes.clear()
        self._active_key_owner.clear()
        self._active_key_note.clear()
