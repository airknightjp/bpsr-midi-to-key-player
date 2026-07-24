from __future__ import annotations


SOUND_SOURCE_IDS = ("piano", "electric_piano", "organ", "synth")
DEFAULT_SOUND_SOURCE = "piano"


def normalize_sound_source(value: object) -> str:
    if isinstance(value, str) and value in SOUND_SOURCE_IDS:
        return value
    return DEFAULT_SOUND_SOURCE
