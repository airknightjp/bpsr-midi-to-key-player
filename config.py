from __future__ import annotations

from dataclasses import dataclass


NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
BASE_NOTE_MIN = 48
BASE_NOTE_MAX = 83
MIN_TRANSPOSE_SEMITONES = -12
MAX_TRANSPOSE_SEMITONES = 12
MIN_OCTAVE_SHIFT = -3
MAX_OCTAVE_SHIFT = 3


@dataclass(frozen=True)
class KeyMapping:
    note: int
    key: str
    octave_shift: int = 0

    @property
    def note_name(self) -> str:
        octave = self.note // 12 - 1
        return f"{NOTE_NAMES[self.note % 12]}{octave}"


DEFAULT_KEY_BINDINGS: dict[int, str] = {
    # C3-B3
    48: "z",
    49: "1",
    50: "x",
    51: "2",
    52: "c",
    53: "v",
    54: "3",
    55: "b",
    56: "4",
    57: "n",
    58: "5",
    59: "m",
    # C4-B4
    60: "a",
    61: "6",
    62: "s",
    63: "7",
    64: "d",
    65: "f",
    66: "8",
    67: "g",
    68: "9",
    69: "h",
    70: "0",
    71: "j",
    # C5-B5
    72: "q",
    73: "i",
    74: "w",
    75: "o",
    76: "e",
    77: "r",
    78: "p",
    79: "t",
    80: "[",
    81: "y",
    82: "]",
    83: "u",
}

BPSR_BASE_MAP = DEFAULT_KEY_BINDINGS

OCTAVE_DOWN_KEY = "<"
OCTAVE_UP_KEY = ">"
OCTAVE_SWITCH_SETTLE_SECONDS = 0.05
SUSTAIN_KEY = "space"
DEFAULT_COUNTDOWN_SECONDS = 3


def normalized_key_bindings(bindings: object) -> dict[int, str]:
    if not isinstance(bindings, dict):
        return dict(DEFAULT_KEY_BINDINGS)

    normalized = dict(DEFAULT_KEY_BINDINGS)
    for raw_note, raw_key in bindings.items():
        try:
            note = int(raw_note)
        except (TypeError, ValueError):
            continue
        if note not in DEFAULT_KEY_BINDINGS or not isinstance(raw_key, str):
            continue
        key = raw_key.strip().lower()
        if key in SUPPORTED_BINDING_KEYS:
            normalized[note] = key
    return normalized


SUPPORTED_BINDING_KEYS = tuple(
    sorted(
        {
            *DEFAULT_KEY_BINDINGS.values(),
            "space",
        },
        key=lambda key: (len(key), key),
    )
)


def midi_note_to_key(note: int, key_bindings: dict[int, str] | None = None) -> KeyMapping | None:
    """Map a MIDI note to a BPSR key and target octave state."""
    base_map = key_bindings or DEFAULT_KEY_BINDINGS
    if note in base_map:
        return KeyMapping(note=note, key=base_map[note])

    if 21 <= note <= 47:
        shifted_note = note + 36
        return KeyMapping(note=note, key=base_map[shifted_note], octave_shift=-1)

    if 84 <= note <= 108:
        shifted_note = note - 36
        return KeyMapping(note=note, key=base_map[shifted_note], octave_shift=1)

    return None


def fit_note_to_base_range(note: int) -> int:
    """Move a MIDI note by octaves until it fits in C3-B5."""
    fitted = int(note)
    while fitted < BASE_NOTE_MIN:
        fitted += 12
    while fitted > BASE_NOTE_MAX:
        fitted -= 12
    return fitted


def shift_midi_note(
    note: int,
    transpose_semitones: int = 0,
    octave_shift: int = 0,
) -> int | None:
    """Apply the common pitch shift and reject notes outside MIDI's range."""
    shifted = int(note) + int(transpose_semitones) + int(octave_shift) * 12
    if 0 <= shifted <= 127:
        return shifted
    return None
