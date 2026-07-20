from __future__ import annotations

import ctypes
import random
import threading
import time
from collections import defaultdict
from collections.abc import Callable

from config import (
    MAX_OCTAVE_SHIFT,
    MAX_TRANSPOSE_SEMITONES,
    MIN_OCTAVE_SHIFT,
    MIN_TRANSPOSE_SEMITONES,
    fit_note_to_base_range,
    shift_midi_note,
)
from midi_parser import MidiEvent
from playback_timing import PlaybackClock, PlaybackTimeline, prepare_playback_events
from repeat_guard import RapidRepeatGuard


StateCallback = Callable[[str], None]
LogCallback = Callable[[str], None]
PositionCallback = Callable[[float], None]
ChannelProvider = Callable[[], set[int]]
SourceProvider = Callable[[], set[tuple[int, int]]]
MIDI_MAPPER = 0xFFFFFFFF
MMSYSERR_NOERROR = 0


class MidiSoundPlayer:
    def __init__(
        self,
        log: LogCallback | None = None,
        on_state: StateCallback | None = None,
        on_position: PositionCallback | None = None,
        enabled_channels: ChannelProvider | None = None,
        enabled_sources: SourceProvider | None = None,
        volume: int = 100,
        auto_fit_note_range: bool = False,
        transpose_semitones: int = 0,
        octave_shift: int = 0,
        humanize_timing: bool = False,
        chord_strum: bool = False,
        repeat_prevention: bool = False,
        playback_speed_percent: int = 100,
    ):
        self.log = log or (lambda _message: None)
        self.on_state = on_state or (lambda _state: None)
        self.on_position = on_position or (lambda _position: None)
        self.enabled_channels = enabled_channels or (lambda: set(range(16)))
        self.enabled_sources = enabled_sources
        self._volume = self._clamp_volume(volume)
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
        self.chord_strum = chord_strum
        self._repeat_guard = RapidRepeatGuard(enabled=repeat_prevention)
        self.playback_speed_percent = playback_speed_percent
        self._random = random.Random()
        self._clock: PlaybackClock | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._pending_seek: float | None = None
        self._pending_switch: tuple[list[MidiEvent], float] | None = None
        self._release_requested = threading.Event()
        self._midi_handle = ctypes.c_void_p()
        self._active_notes: set[tuple[int, int]] = set()
        self._active_note_owner: dict[tuple[int, int], int] = {}
        self._active_note_velocity: dict[tuple[int, int], int] = {}
        self._sustain_channels: set[int] = set()
        self._suppressed_note_offs: dict[tuple[int, int, int], int] = defaultdict(int)

    @property
    def is_playing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def play(self, events: list[MidiEvent], start_time: float = 0.0) -> None:
        if self.is_playing:
            raise RuntimeError("MIDI sound is already playing")
        self._stop_event.clear()
        self._release_requested.clear()
        self._repeat_guard.reset()
        with self._lock:
            self._pending_seek = None
            self._pending_switch = None
        self._thread = threading.Thread(
            target=self._run,
            args=(events, max(0.0, start_time)),
            daemon=True,
        )
        self._thread.start()

    def set_volume(self, volume: int) -> None:
        with self._state_lock:
            self._volume = self._clamp_volume(volume)

    def set_auto_fit_note_range(self, enabled: bool) -> None:
        with self._state_lock:
            self.auto_fit_note_range = bool(enabled)
            self._release_requested.set()

    def set_note_shift(self, transpose_semitones: int, octave_shift: int) -> None:
        transpose_semitones = max(
            MIN_TRANSPOSE_SEMITONES,
            min(MAX_TRANSPOSE_SEMITONES, int(transpose_semitones)),
        )
        octave_shift = max(MIN_OCTAVE_SHIFT, min(MAX_OCTAVE_SHIFT, int(octave_shift)))
        with self._state_lock:
            if (
                self.transpose_semitones == transpose_semitones
                and self.note_octave_shift == octave_shift
            ):
                return
            self.transpose_semitones = transpose_semitones
            self.note_octave_shift = octave_shift
            self._release_requested.set()

    def set_humanize_timing(self, enabled: bool) -> None:
        with self._state_lock:
            self.humanize_timing = bool(enabled)

    def _humanize_timing_enabled(self) -> bool:
        with self._state_lock:
            return self.humanize_timing

    def set_chord_strum(self, enabled: bool) -> None:
        with self._state_lock:
            self.chord_strum = bool(enabled)

    def _chord_strum_enabled(self) -> bool:
        with self._state_lock:
            return self.chord_strum

    def set_repeat_prevention(self, enabled: bool) -> None:
        self._repeat_guard.set_enabled(enabled)

    def set_playback_speed(self, speed_percent: int) -> None:
        with self._state_lock:
            self.playback_speed_percent = int(speed_percent)
            clock = self._clock
        if clock is not None:
            clock.set_speed_percent(speed_percent)

    def seek(self, position: float) -> None:
        position = max(0.0, position)
        with self._lock:
            self._pending_seek = position
        self.on_position(position)

    def switch(self, events: list[MidiEvent], start_time: float = 0.0) -> None:
        start_time = max(0.0, start_time)
        with self._lock:
            self._pending_seek = None
            self._pending_switch = (events, start_time)
        self.on_position(start_time)

    def release_all(self) -> None:
        if self.is_playing and threading.current_thread() is not self._thread:
            self._release_requested.set()
            return
        self._release_all_now()

    def _release_all_now(self) -> None:
        with self._state_lock:
            affected_channels = set(self._sustain_channels)
            affected_channels.update(channel for channel, _note in self._active_notes)
            for channel in list(self._sustain_channels):
                self._send_control_change(channel, 64, 0)
            self._sustain_channels.clear()
            for channel, note in list(self._active_notes):
                self._send_note_off(channel, note)
            for channel in affected_channels:
                self._send_control_change(channel, 123, 0)
            self._active_notes.clear()
            self._active_note_owner.clear()
            self._active_note_velocity.clear()
            self._suppressed_note_offs.clear()

    def stop(self) -> None:
        self._stop_event.set()

    def wait_until_stopped(self, timeout: float = 1.0) -> None:
        if self._thread is None or threading.current_thread() is self._thread:
            return
        self._thread.join(timeout)

    def _run(self, events: list[MidiEvent], start_time: float) -> None:
        if not self._open_midi():
            self.log("MIDI sound playback failed: could not open MIDI output")
            self.on_state("sound stopped")
            return

        failure: Exception | None = None
        try:
            self.log(f"MIDI sound playback started (volume {self._volume}%)")
            self.on_state("sound playing")
            current_events = events
            current_start_time = start_time

            while not self._stop_event.is_set():
                current_start_time = self._play_from(current_events, current_start_time)
                pending_switch = self._pop_pending_switch()
                if pending_switch is not None:
                    self._release_all_now()
                    current_events, current_start_time = pending_switch
                    continue
                pending_seek = self._pop_pending_seek()
                if pending_seek is None:
                    break
                self._release_all_now()
                current_start_time = pending_seek
        except Exception as exc:
            failure = exc
            self.log(f"MIDI sound playback failed: {exc}")
        finally:
            try:
                self._release_all_now()
            except Exception as exc:
                if failure is None:
                    self.log(f"MIDI sound cleanup failed: {exc}")
            try:
                self._close_midi()
            except Exception as exc:
                self.log(f"MIDI output close failed: {exc}")
            with self._state_lock:
                self._clock = None
            if self._stop_event.is_set():
                self.on_state("sound stopped")
            else:
                self.on_state("sound ended")

    def _play_from(self, events: list[MidiEvent], start_time: float) -> float:
        with self._state_lock:
            speed_percent = self.playback_speed_percent
        clock = PlaybackClock(start_time, speed_percent)
        with self._state_lock:
            self._clock = clock
        last_position = start_time
        timeline = PlaybackTimeline(start_time, self._random)
        for scheduled in prepare_playback_events(events, self._random):
            event = scheduled.event
            if self._stop_event.is_set():
                return last_position

            self._consume_release_request()
            if self._has_pending_switch():
                return last_position

            pending_seek = self._pop_pending_seek()
            if pending_seek is not None:
                with self._lock:
                    self._pending_seek = pending_seek
                return last_position

            if event.time < start_time:
                continue

            scheduled_time = event.time
            while not self._stop_event.is_set():
                self._consume_release_request()
                if self._has_pending_switch():
                    return last_position
                pending_seek = self._pop_pending_seek()
                if pending_seek is not None:
                    with self._lock:
                        self._pending_seek = pending_seek
                    return last_position
                scheduled_time = timeline.scheduled_time(
                    scheduled,
                    self._humanize_timing_enabled(),
                    self._chord_strum_enabled(),
                )
                delay = clock.delay_until(scheduled_time)
                if delay <= 0:
                    break
                self.on_position(clock.position())
                self._stop_event.wait(min(delay, 0.01))

            if self._stop_event.is_set():
                return last_position
            timeline.mark_emitted(scheduled_time)
            last_position = event.time
            self.on_position(clock.position())
            self._handle_event(event)

        return last_position

    def _handle_event(self, event: MidiEvent) -> None:
        with self._state_lock:
            if event.channel is None:
                return
            if (
                event.kind == "note_off"
                and event.note is not None
                and self._consume_suppressed_note_off(
                    event.track,
                    event.channel,
                    event.note,
                )
            ):
                return
            if not self._event_is_enabled(event):
                if event.track is not None and self.enabled_sources is not None:
                    return
                if event.kind == "note_off" and event.note is not None:
                    playable_note = self._playable_note(event.note)
                    if playable_note is not None:
                        self._send_note_off(event.channel, playable_note)
                elif event.kind == "sustain" and event.value is not None and event.value < 64:
                    self._send_control_change(event.channel, 64, 0)
                    self._sustain_channels.discard(event.channel)
                return

            if event.kind == "note_on" and event.note is not None:
                playable_note = self._playable_note(event.note)
                if playable_note is None:
                    return
                repeat_token = (event.channel, playable_note)
                if self._repeat_guard.should_suppress(repeat_token, event.time):
                    source_track = event.track if event.track is not None else -1
                    self._suppressed_note_offs[
                        (source_track, event.channel, event.note)
                    ] += 1
                    return
                velocity = int((event.velocity or 64) * self._volume / 100)
                if velocity <= 0:
                    return
                self._send_note_on(event.channel, playable_note, velocity, owner_note=event.note)
            elif event.kind == "note_off" and event.note is not None:
                playable_note = self._playable_note(event.note)
                if playable_note is not None:
                    self._send_note_off(event.channel, playable_note, owner_note=event.note)
            elif event.kind == "sustain" and event.value is not None:
                self._send_control_change(event.channel, 64, event.value)
                if event.value >= 64:
                    self._sustain_channels.add(event.channel)
                else:
                    self._sustain_channels.discard(event.channel)

    def _event_is_enabled(self, event: MidiEvent) -> bool:
        if event.channel is None:
            return True
        if event.track is not None and self.enabled_sources is not None:
            return (event.track, event.channel) in self.enabled_sources()
        return event.channel in self.enabled_channels()

    def _consume_suppressed_note_off(
        self,
        track: int | None,
        channel: int,
        note: int,
    ) -> bool:
        owner = (track if track is not None else -1, channel, note)
        count = self._suppressed_note_offs.get(owner, 0)
        if count <= 0:
            return False
        if count == 1:
            self._suppressed_note_offs.pop(owner, None)
        else:
            self._suppressed_note_offs[owner] = count - 1
        return True

    def _playable_note(self, note: int) -> int | None:
        shifted_note = shift_midi_note(
            note,
            self.transpose_semitones,
            self.note_octave_shift,
        )
        if shifted_note is None:
            return None
        if self.auto_fit_note_range:
            return fit_note_to_base_range(shifted_note)
        return shifted_note

    def _send_note_on(self, channel: int, note: int, velocity: int, owner_note: int | None = None) -> None:
        active_note = (channel, note)
        if active_note in self._active_notes:
            self._send_short_message(0x80 | channel, note, 0)
            time.sleep(0.01)
        self._send_short_message(0x90 | channel, note, velocity)
        self._active_notes.add(active_note)
        self._active_note_velocity[active_note] = velocity
        if owner_note is not None:
            self._active_note_owner[active_note] = owner_note

    def _send_note_off(self, channel: int, note: int, owner_note: int | None = None) -> None:
        active_note = (channel, note)
        current_owner = self._active_note_owner.get(active_note)
        if owner_note is not None and current_owner is not None and current_owner != owner_note:
            velocity = self._active_note_velocity.get(active_note, 64)
            self._send_short_message(0x80 | channel, note, 0)
            time.sleep(0.01)
            self._send_short_message(0x90 | channel, note, velocity)
            return
        self._active_note_owner.pop(active_note, None)
        self._active_note_velocity.pop(active_note, None)
        self._send_short_message(0x80 | channel, note, 0)
        self._active_notes.discard(active_note)

    def _send_control_change(self, channel: int, control: int, value: int) -> None:
        self._send_short_message(0xB0 | channel, control, value)

    def _send_short_message(self, status: int, data1: int, data2: int) -> None:
        if not self._midi_handle:
            return
        message = status | (data1 << 8) | (data2 << 16)
        result = ctypes.windll.winmm.midiOutShortMsg(self._midi_handle, message)
        if result != MMSYSERR_NOERROR:
            raise RuntimeError(f"MIDI output send failed ({result})")

    def _open_midi(self) -> bool:
        result = ctypes.windll.winmm.midiOutOpen(
            ctypes.byref(self._midi_handle),
            MIDI_MAPPER,
            0,
            0,
            0,
        )
        return result == MMSYSERR_NOERROR

    def _close_midi(self) -> None:
        if self._midi_handle:
            handle = self._midi_handle
            self._midi_handle = ctypes.c_void_p()
            reset_result = ctypes.windll.winmm.midiOutReset(handle)
            close_result = ctypes.windll.winmm.midiOutClose(handle)
            if reset_result != MMSYSERR_NOERROR:
                raise RuntimeError(f"MIDI output reset failed ({reset_result})")
            if close_result != MMSYSERR_NOERROR:
                raise RuntimeError(f"MIDI output close failed ({close_result})")

    def _consume_release_request(self) -> None:
        if self._release_requested.is_set():
            self._release_requested.clear()
            self._release_all_now()

    def _pop_pending_seek(self) -> float | None:
        with self._lock:
            pending_seek = self._pending_seek
            self._pending_seek = None
        return pending_seek

    def _pop_pending_switch(self) -> tuple[list[MidiEvent], float] | None:
        with self._lock:
            pending_switch = self._pending_switch
            self._pending_switch = None
        return pending_switch

    def _has_pending_switch(self) -> bool:
        with self._lock:
            return self._pending_switch is not None

    @staticmethod
    def _clamp_volume(volume: int) -> int:
        return max(0, min(100, int(volume)))


class RealtimeMidiSoundOutput:
    def __init__(
        self,
        volume: int = 100,
        log: LogCallback | None = None,
        transpose_semitones: int = 0,
        octave_shift: int = 0,
    ):
        self.log = log or (lambda _message: None)
        self._volume = self._clamp_volume(volume)
        self.transpose_semitones = max(
            MIN_TRANSPOSE_SEMITONES,
            min(MAX_TRANSPOSE_SEMITONES, int(transpose_semitones)),
        )
        self.note_octave_shift = max(
            MIN_OCTAVE_SHIFT,
            min(MAX_OCTAVE_SHIFT, int(octave_shift)),
        )
        self._enabled = False
        self._midi_handle = ctypes.c_void_p()
        self._active_notes: set[tuple[int, int]] = set()
        self._sustain_channels: set[int] = set()
        self._lock = threading.RLock()

    @property
    def is_enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def set_enabled(self, enabled: bool) -> bool:
        with self._lock:
            enabled = bool(enabled)
            if enabled:
                if not self._midi_handle and not self._open_midi():
                    self._enabled = False
                    self.log("Realtime MIDI sound failed: could not open MIDI output")
                    return False
                self._enabled = True
                return True

            self._enabled = False
            self._release_and_close()
            return True

    def set_volume(self, volume: int) -> None:
        with self._lock:
            self._volume = self._clamp_volume(volume)

    def set_note_shift(self, transpose_semitones: int, octave_shift: int) -> None:
        transpose_semitones = max(
            MIN_TRANSPOSE_SEMITONES,
            min(MAX_TRANSPOSE_SEMITONES, int(transpose_semitones)),
        )
        octave_shift = max(MIN_OCTAVE_SHIFT, min(MAX_OCTAVE_SHIFT, int(octave_shift)))
        with self._lock:
            if (
                self.transpose_semitones == transpose_semitones
                and self.note_octave_shift == octave_shift
            ):
                return
            if self._midi_handle:
                self._release_all_now()
            self.transpose_semitones = transpose_semitones
            self.note_octave_shift = octave_shift

    def process_message(self, event_type: int, channel: int, data1: int, data2: int) -> None:
        with self._lock:
            if not self._enabled or not self._midi_handle:
                return
            try:
                if event_type == 0x90 and data2 > 0:
                    note = shift_midi_note(
                        data1,
                        self.transpose_semitones,
                        self.note_octave_shift,
                    )
                    if note is None:
                        return
                    velocity = int(data2 * self._volume / 100)
                    if velocity > 0:
                        self._send_note_on(channel, note, velocity)
                elif event_type in {0x80, 0x90}:
                    note = shift_midi_note(
                        data1,
                        self.transpose_semitones,
                        self.note_octave_shift,
                    )
                    if note is not None:
                        self._send_note_off(channel, note)
                elif event_type == 0xB0 and data1 == 64:
                    self._send_control_change(channel, 64, data2)
                    if data2 >= 64:
                        self._sustain_channels.add(channel)
                    else:
                        self._sustain_channels.discard(channel)
            except Exception as exc:
                self.log(f"Realtime MIDI sound failed: {exc}")
                self._enabled = False
                self._release_and_close()

    def close(self) -> None:
        with self._lock:
            self._enabled = False
            self._release_and_close()

    def _send_note_on(self, channel: int, note: int, velocity: int) -> None:
        active_note = (channel, note)
        if active_note in self._active_notes:
            self._send_short_message(0x80 | channel, note, 0)
            time.sleep(0.01)
        self._send_short_message(0x90 | channel, note, velocity)
        self._active_notes.add(active_note)

    def _send_note_off(self, channel: int, note: int) -> None:
        self._send_short_message(0x80 | channel, note, 0)
        self._active_notes.discard((channel, note))

    def _send_control_change(self, channel: int, control: int, value: int) -> None:
        self._send_short_message(0xB0 | channel, control, value)

    def _release_all_now(self) -> None:
        affected_channels = set(self._sustain_channels)
        affected_channels.update(channel for channel, _note in self._active_notes)
        for channel in list(self._sustain_channels):
            self._send_control_change(channel, 64, 0)
        for channel, note in list(self._active_notes):
            self._send_note_off(channel, note)
        for channel in affected_channels:
            self._send_control_change(channel, 123, 0)
        self._sustain_channels.clear()
        self._active_notes.clear()

    def _release_and_close(self) -> None:
        try:
            if self._midi_handle:
                self._release_all_now()
        except Exception as exc:
            self.log(f"Realtime MIDI sound cleanup failed: {exc}")
        finally:
            self._active_notes.clear()
            self._sustain_channels.clear()
            try:
                self._close_midi()
            except Exception as exc:
                self.log(f"Realtime MIDI output close failed: {exc}")

    def _send_short_message(self, status: int, data1: int, data2: int) -> None:
        if not self._midi_handle:
            return
        message = status | (data1 << 8) | (data2 << 16)
        result = ctypes.windll.winmm.midiOutShortMsg(self._midi_handle, message)
        if result != MMSYSERR_NOERROR:
            raise RuntimeError(f"MIDI output send failed ({result})")

    def _open_midi(self) -> bool:
        result = ctypes.windll.winmm.midiOutOpen(
            ctypes.byref(self._midi_handle),
            MIDI_MAPPER,
            0,
            0,
            0,
        )
        return result == MMSYSERR_NOERROR

    def _close_midi(self) -> None:
        if not self._midi_handle:
            return
        handle = self._midi_handle
        self._midi_handle = ctypes.c_void_p()
        reset_result = ctypes.windll.winmm.midiOutReset(handle)
        close_result = ctypes.windll.winmm.midiOutClose(handle)
        if reset_result != MMSYSERR_NOERROR:
            raise RuntimeError(f"MIDI output reset failed ({reset_result})")
        if close_result != MMSYSERR_NOERROR:
            raise RuntimeError(f"MIDI output close failed ({close_result})")

    @staticmethod
    def _clamp_volume(volume: int) -> int:
        return max(0, min(100, int(volume)))
