from __future__ import annotations

import ctypes
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from ctypes import wintypes

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


MAXPNAMELEN = 32
CALLBACK_FUNCTION = 0x00030000
MIM_DATA = 0x3C3
MMSYSERR_NOERROR = 0

LogCallback = Callable[[str], None]
StateCallback = Callable[[str], None]
MidiMessageCallback = Callable[[int, int, int, int], None]
NoteOwner = tuple[int, int]


class MIDIINCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", wintypes.WORD),
        ("wPid", wintypes.WORD),
        ("vDriverVersion", wintypes.DWORD),
        ("szPname", wintypes.WCHAR * MAXPNAMELEN),
        ("dwSupport", wintypes.DWORD),
    ]


MidiInCallback = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE,
    wintypes.UINT,
    ctypes.c_size_t,
    ctypes.c_size_t,
    ctypes.c_size_t,
)


def list_midi_input_devices() -> list[tuple[int, str]]:
    count = ctypes.windll.winmm.midiInGetNumDevs()
    devices: list[tuple[int, str]] = []
    for device_id in range(count):
        caps = MIDIINCAPSW()
        result = ctypes.windll.winmm.midiInGetDevCapsW(
            device_id,
            ctypes.byref(caps),
            ctypes.sizeof(caps),
        )
        if result == MMSYSERR_NOERROR:
            devices.append((device_id, caps.szPname))
    return devices


class MidiInputKeyboardBridge:
    def __init__(
        self,
        device_id: int,
        output: KeyboardOutput,
        log: LogCallback | None = None,
        on_state: StateCallback | None = None,
        on_midi_message: MidiMessageCallback | None = None,
        auto_fit_note_range: bool = False,
        transpose_semitones: int = 0,
        octave_shift: int = 0,
        key_bindings: dict[int, str] | None = None,
    ):
        self.device_id = device_id
        self.output = output
        self.log = log or (lambda _message: None)
        self.on_state = on_state or (lambda _state: None)
        self.on_midi_message = on_midi_message or (
            lambda _event_type, _channel, _data1, _data2: None
        )
        self.auto_fit_note_range = auto_fit_note_range
        self.transpose_semitones = max(
            MIN_TRANSPOSE_SEMITONES,
            min(MAX_TRANSPOSE_SEMITONES, int(transpose_semitones)),
        )
        self.note_octave_shift = max(
            MIN_OCTAVE_SHIFT,
            min(MAX_OCTAVE_SHIFT, int(octave_shift)),
        )
        self.key_bindings = normalized_key_bindings(key_bindings)
        self._handle = ctypes.c_void_p()
        self._callback = MidiInCallback(self._midi_callback)
        self._lock = threading.RLock()
        self._running = False
        self._active_notes: dict[NoteOwner, list[str]] = defaultdict(list)
        self._active_key_owner: dict[str, NoteOwner] = {}
        self._sustain_channels: set[int] = set()
        self._octave_shift = 0

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def start(self) -> None:
        with self._lock:
            if self._running:
                raise RuntimeError("MIDI input is already running")
        result = ctypes.windll.winmm.midiInOpen(
            ctypes.byref(self._handle),
            self.device_id,
            self._callback,
            0,
            CALLBACK_FUNCTION,
        )
        if result != MMSYSERR_NOERROR:
            raise RuntimeError(f"Could not open MIDI input device ({result})")

        result = ctypes.windll.winmm.midiInStart(self._handle)
        if result != MMSYSERR_NOERROR:
            ctypes.windll.winmm.midiInClose(self._handle)
            self._handle = ctypes.c_void_p()
            raise RuntimeError(f"Could not start MIDI input device ({result})")

        try:
            with self._lock:
                self._reset_external_octave_to_base_if_needed()
                self._running = True
        except Exception:
            self._shutdown_input()
            raise
        self.on_state("midi input running")
        self.log("MIDI keyboard input started")

    def stop(self) -> None:
        with self._lock:
            if not self._running and not self._handle:
                return
            self._running = False
        self._shutdown_input()
        self.on_state("midi input stopped")
        self.log("MIDI keyboard input stopped")

    def set_auto_fit_note_range(self, enabled: bool) -> None:
        with self._lock:
            self._release_active_note_keys()
            self.output.release_all()
            self._sustain_channels.clear()
            self.auto_fit_note_range = bool(enabled)

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
            self._release_active_note_keys()
            self.output.release_all()
            self._sustain_channels.clear()
            self.transpose_semitones = transpose_semitones
            self.note_octave_shift = octave_shift

    def set_key_bindings(self, key_bindings: dict[int, str]) -> None:
        with self._lock:
            self._release_active_note_keys()
            self.output.release_all()
            self._sustain_channels.clear()
            self.key_bindings = normalized_key_bindings(key_bindings)

    def _shutdown_input(self) -> None:
        with self._lock:
            self._running = False
            handle = self._handle
            self._handle = ctypes.c_void_p()

        errors: list[Exception] = []
        if handle:
            winmm = ctypes.windll.winmm
            for operation in (winmm.midiInStop, winmm.midiInReset, winmm.midiInClose):
                try:
                    result = operation(handle)
                    if result != MMSYSERR_NOERROR:
                        errors.append(RuntimeError(f"MIDI input shutdown failed ({result})"))
                except Exception as exc:
                    errors.append(exc)

        with self._lock:
            for cleanup in (
                self._release_active_note_keys,
                lambda: self._move_to_octave_shift(0),
                self.output.release_all,
            ):
                try:
                    cleanup()
                except Exception as exc:
                    errors.append(exc)
            self._active_notes.clear()
            self._active_key_owner.clear()
            self._sustain_channels.clear()
            self._octave_shift = 0
        for error in errors:
            self.log(f"MIDI input cleanup failed: {error}")

    def _midi_callback(
        self,
        _handle: wintypes.HANDLE,
        message: int,
        _instance: int,
        param1: int,
        _param2: int,
    ) -> None:
        if message != MIM_DATA:
            return
        status = param1 & 0xFF
        data1 = (param1 >> 8) & 0xFF
        data2 = (param1 >> 16) & 0xFF
        event_type = status & 0xF0
        channel = status & 0x0F

        try:
            self.on_midi_message(event_type, channel, data1, data2)
        except Exception as exc:
            self.log(f"Realtime MIDI sound event failed: {exc}")

        try:
            if event_type == 0x90 and data2 > 0:
                self._note_on(channel, data1, data2)
            elif event_type in {0x80, 0x90}:
                self._note_off(channel, data1)
            elif event_type == 0xB0 and data1 == 64:
                self._sustain(channel, data2)
        except Exception as exc:
            self.log(f"MIDI input event failed: {exc}")
            with self._lock:
                self._running = False
                try:
                    self._release_active_note_keys()
                    self.output.release_all()
                except Exception as cleanup_exc:
                    self.log(f"MIDI input cleanup failed: {cleanup_exc}")
            self.on_state("midi input failed")

    def _note_on(self, channel: int, note: int, velocity: int) -> None:
        playable_note = self._playable_note(note)
        if playable_note is None:
            self.log(f"   input ch {channel} skip note {note}")
            return
        with self._lock:
            key_bindings = self.key_bindings
        mapping = midi_note_to_key(playable_note, key_bindings)
        if mapping is None:
            self.log(f"   input ch {channel} skip note {note}")
            return

        with self._lock:
            if not self._running:
                return
            self._move_to_octave_shift(mapping.octave_shift)
            owner = (channel, note)
            self._press_note_key(mapping.key, owner=owner)
            self._active_notes[owner].append(mapping.key)
        source = "" if playable_note == note else f" from {self._note_name(note)}"
        self.log(f"   input ch {channel} on  {mapping.note_name:<3}{source} -> {mapping.key} v{velocity}")

    def _note_off(self, channel: int, note: int) -> None:
        with self._lock:
            if not self._running:
                return
            owner = (channel, note)
            keys = self._active_notes.get(owner)
            if not keys:
                return
            key = keys.pop()
            if not keys:
                self._active_notes.pop(owner, None)
            self._release_note_key(key, owner=owner)
        self.log(f"   input ch {channel} off note {note} -> {key}")

    def _sustain(self, channel: int, value: int) -> None:
        with self._lock:
            if not self._running:
                return
            if value >= 64:
                was_inactive = not self._sustain_channels
                self._sustain_channels.add(channel)
                if was_inactive:
                    self.output.press(SUSTAIN_KEY)
                state = "on "
            else:
                self._sustain_channels.discard(channel)
                if not self._sustain_channels:
                    self.output.release(SUSTAIN_KEY)
                state = "off"
        self.log(f"   input ch {channel} sustain {state}")

    def _playable_note(self, note: int) -> int | None:
        with self._lock:
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
            self.log(f"   input octave up -> {self._octave_shift}")
        while self._octave_shift > target_shift:
            self.output.tap(OCTAVE_DOWN_KEY)
            self._octave_shift -= 1
            self.log(f"   input octave down -> {self._octave_shift}")
        if changed:
            time.sleep(OCTAVE_SWITCH_SETTLE_SECONDS)

    def _reset_external_octave_to_base(self) -> None:
        self.output.tap(OCTAVE_DOWN_KEY)
        self.output.tap(OCTAVE_DOWN_KEY)
        self.output.tap(OCTAVE_UP_KEY)
        self._octave_shift = 0
        time.sleep(OCTAVE_SWITCH_SETTLE_SECONDS)

    def _reset_external_octave_to_base_if_needed(self) -> None:
        if self.auto_fit_note_range:
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
