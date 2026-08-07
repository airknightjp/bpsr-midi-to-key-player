from __future__ import annotations


STARRA_GUITAR_SOURCE = "star_resonance_guitar"

SOUND_SOURCE_IDS = (
    "piano",
    STARRA_GUITAR_SOURCE,
)
DEFAULT_SOUND_SOURCE = "piano"


def normalize_sound_source(value: object) -> str:
    if isinstance(value, str) and value in SOUND_SOURCE_IDS:
        return value
    return DEFAULT_SOUND_SOURCE
