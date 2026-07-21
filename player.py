from __future__ import annotations

import random
import threading
import time
from collections import defaultdict
from collections.abc import Callable

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


LogCallback = Callable[[str], None]
StateCallback = Callable[[str], None]
PositionCallback = Callable[[float], None]
OptimizationProgressCallback = Callable[[int | None], None]
CountdownCallback = Callable[[int], None]
EnabledChannelsCallback = Callable[[], set[int]]
EnabledSourcesCallback = Callable[[], set[tuple[int, int]]]
NoteOwner = tuple[int, int, int]


class MidiKeyboardPlayer:
    def __init__(
        self,
        output: KeyboardOutput,
        log: LogCallback | None = None,
        on_state: StateCallback | None = None,
        on_position: PositionCallback | None = None,
        on_optimization_progress: OptimizationProgressCallback | None = None,
        enabled_channels: EnabledChannelsCallback | None = None,
        enabled_sources: EnabledSourcesCallback | None = None,
        auto_fit_note_range: bool = False,
        transpose_semitones: int = 0,
        octave_shift: int = 0,
        humanize_timing: bool = False,
        chord_optimization: bool = False,
        chord_strum: bool = False,
        repeat_prevention: bool = False,
        playback_speed_percent: int = 100,
        key_bindings: dict[int, str] | None = None,
    ):
        self.output = output
        self.log = log or (lambda _message: None)
        self.on_state = on_state or (lambda _state: None)
        self.on_position = on_position or (lambda _position: None)
        self.on_optimization_progress = on_optimization_progress or (lambda _progress: None)
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
        self.chord_optimization = chord_optimization
        self.chord_strum = chord_strum
        self._repeat_guard = RapidRepeatGuard(enabled=repeat_prevention)
        self.playback_speed_percent = playback_speed_percent
        self.key_bindings = normalized_key_bindings(key_bindings)
        self._config_lock = threading.Lock()
        self._random = random.Random()
        self._clock: PlaybackClock | None = None
        self._stop_event = threading.Event()
        self._release_requested = threading.Event()
        self._thread: threading.Thread | None = None
        self._active_notes: dict[NoteOwner, list[str]] = defaultdict(list)
        self._active_key_owner: dict[str, NoteOwner] = {}
        self._sustain_channels: set[tuple[int, int]] = set()
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

    def set_repeat_prevention(self, enabled: bool) -> None:
        self._repeat_guard.set_enabled(enabled)

    def set_playback_speed(self, speed_percent: int) -> None:
        with self._config_lock:
            speed_percent = int(speed_percent)
            if self.playback_speed_percent != speed_percent:
                self.playback_speed_percent = speed_percent
                self._mark_chord_optimization_dirty_locked()
            clock = self._clock
        if clock is not None:
            clock.set_speed_percent(speed_percent)
            self._schedule_chord_optimization()

    def set_key_bindings(self, key_bindings: dict[int, str]) -> None:
        with self._config_lock:
            self.key_bindings = normalized_key_bindings(key_bindings)
            self._release_requested.set()

    def wait_until_stopped(self, timeout: float = 1.0) -> None:
        if self._thread is None or threading.current_thread() is self._thread:
            return
        self._thread.join(timeout)
        self._optimization_planner.wait(timeout=0.2)

    def _run(
        self,
        events: list[MidiEvent],
        countdown_seconds: int,
        start_time: float,
        on_countdown_tick: CountdownCallback | None,
    ) -> None:
        failure: Exception | None = None
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
            for scheduled in prepare_playback_events(
                events,
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
                self._refresh_chord_optimization_plan(events)
                self.on_position(clock.position())
                self._handle_event(event)
        except Exception as exc:
            failure = exc
            self.log(f"Keyboard playback failed: {exc}")
        finally:
            for cleanup in (
                self._release_active_note_keys,
                lambda: self._move_to_octave_shift(0),
                self.output.release_all,
            ):
                try:
                    cleanup()
                except Exception as exc:
                    if failure is None:
                        failure = exc
                        self.log(f"Keyboard playback cleanup failed: {exc}")
            self._active_notes.clear()
            self._active_key_owner.clear()
            self._sustain_channels.clear()
            self._octave_shift = 0
            with self._config_lock:
                self._clock = None
                self._current_events = None
                self._optimization_generation += 1
            self.on_state("stopped")

    def _consume_release_request(self) -> None:
        if not self._release_requested.is_set():
            return
        self._release_requested.clear()
        self._release_active_note_keys()
        self.output.release_all()
        self._sustain_channels.clear()

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
                return

        if event.kind == "note_on" and event.note is not None:
            note = self._playable_event_note(event)
            if note is None:
                self.log(f"{event.time:8.3f}s skip note {event.note}")
                return
            with self._config_lock:
                key_bindings = self.key_bindings
            mapping = midi_note_to_key(note, key_bindings)
            if mapping is None:
                self.log(f"{event.time:8.3f}s skip note {event.note}")
                return
            repeat_token = (mapping.octave_shift, mapping.key)
            if self._repeat_guard.should_suppress(repeat_token, emitted_at):
                self.log(f"{event.time:8.3f}s skip rapid repeat {mapping.note_name:<3} -> {mapping.key}")
                return

            self._move_to_octave_shift(mapping.octave_shift)
            owner = self._note_owner(event.track, event.channel, event.note)
            self._press_note_key(mapping.key, owner=owner)
            self._active_notes[owner].append(mapping.key)
            source = "" if note == event.note else f" from {self._note_name(event.note)}"
            self.log(f"{event.time:8.3f}s on  {mapping.note_name:<3}{source} -> {mapping.key}")

        elif event.kind == "note_off" and event.note is not None:
            key = self._release_note(event.track, event.channel or 0, event.note)
            if key is not None:
                self.log(f"{event.time:8.3f}s off note {event.note} -> {key}")

        elif event.kind == "sustain" and event.value is not None:
            if event.value >= 64:
                self._set_sustain(event.track, event.channel or 0, enabled=True)
                state = "on "
            else:
                self._set_sustain(event.track, event.channel or 0, enabled=False)
                state = "off"
            self.log(f"{event.time:8.3f}s sustain {state}")

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
            chord_optimization = self.chord_optimization
            auto_fit_note_range = self.auto_fit_note_range
            plan = self._chord_optimization_plan
            plan_auto_fit = self._chord_optimization_plan_auto_fit
            plan_transpose = self._chord_optimization_plan_transpose
            plan_octave = self._chord_optimization_plan_octave
            transpose_semitones = self.transpose_semitones
            octave_shift = self.note_octave_shift
        if (
            chord_optimization
            and plan is not None
            and plan_auto_fit == auto_fit_note_range
            and plan_transpose == transpose_semitones
            and plan_octave == octave_shift
        ):
            planned, target = plan.target_for(event)
            if planned:
                return target
        if event.note is None:
            return None
        return self._playable_note(event.note)

    def _chord_optimization_timing_offset(self, event: MidiEvent) -> float | None:
        with self._config_lock:
            if not self.chord_optimization or self._chord_optimization_plan is None:
                return None
            if (
                self._chord_optimization_plan_auto_fit != self.auto_fit_note_range
                or self._chord_optimization_plan_transpose != self.transpose_semitones
                or self._chord_optimization_plan_octave != self.note_octave_shift
            ):
                return None
            plan = self._chord_optimization_plan
        return plan.timing_offset_for(event)

    def _refresh_chord_optimization_plan(
        self,
        events: list[MidiEvent],
        force: bool = False,
    ) -> None:
        with self._config_lock:
            if self._current_events is None:
                self._current_events = events
        if force:
            self._optimization_planner.build_now()
        else:
            self._optimization_planner.schedule()

    def _mark_chord_optimization_dirty_locked(self) -> None:
        self._chord_optimization_plan_dirty = True
        self._optimization_generation += 1

    def _schedule_chord_optimization(self) -> None:
        with self._config_lock:
            should_schedule = (
                self._clock is not None
                and self._current_events is not None
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
            return (
                not self._stop_event.is_set()
                and self.chord_optimization
                and self._current_events is not None
                and self._optimization_generation == generation
            )

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

    @staticmethod
    def _note_name(note: int) -> str:
        names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
        return f"{names[note % 12]}{note // 12 - 1}"

    def _move_to_octave_shift(self, target_shift: int) -> None:
        changed = target_shift != self._octave_shift
        if changed:
            self._release_active_note_keys()
        while self._octave_shift < target_shift:
            self.output.tap(OCTAVE_UP_KEY)
            self._octave_shift += 1
            self.log(f"octave up -> {self._octave_shift}")
        while self._octave_shift > target_shift:
            self.output.tap(OCTAVE_DOWN_KEY)
            self._octave_shift -= 1
            self.log(f"octave down -> {self._octave_shift}")
        if changed:
            time.sleep(OCTAVE_SWITCH_SETTLE_SECONDS)

    def _reset_external_octave_to_base(self) -> None:
        self.output.tap(OCTAVE_DOWN_KEY)
        self.output.tap(OCTAVE_DOWN_KEY)
        self.output.tap(OCTAVE_UP_KEY)
        self._octave_shift = 0
        time.sleep(OCTAVE_SWITCH_SETTLE_SECONDS)

    def _reset_external_octave_to_base_if_needed(self) -> None:
        with self._config_lock:
            auto_fit_note_range = self.auto_fit_note_range
        if auto_fit_note_range:
            self._octave_shift = 0
            return
        self._reset_external_octave_to_base()

    def _press_note_key(self, key: str, owner: NoteOwner) -> None:
        if key in self._active_key_owner:
            self.output.release(key)
            time.sleep(0.01)
            self._remove_active_key(key)
        self.output.press(key)
        self._active_key_owner[key] = owner

    def _release_note_key(self, key: str, owner: NoteOwner) -> None:
        current_owner = self._active_key_owner.get(key)
        if current_owner is not None and current_owner != owner:
            self.output.release(key)
            time.sleep(0.01)
            self.output.press(key)
            return
        self._active_key_owner.pop(key, None)
        self.output.release(key)
        self._remove_active_key(key)

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

    def _set_sustain(self, track: int | None, channel: int, enabled: bool) -> None:
        source = (track if track is not None else -1, channel)
        if enabled:
            was_inactive = not self._sustain_channels
            self._sustain_channels.add(source)
            if was_inactive:
                self.output.press(SUSTAIN_KEY)
            return
        self._sustain_channels.discard(source)
        if not self._sustain_channels:
            self.output.release(SUSTAIN_KEY)

    def _remove_active_key(self, key: str) -> None:
        self._active_key_owner.pop(key, None)
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
                    released.add(key)
        self._active_notes.clear()
        self._active_key_owner.clear()
