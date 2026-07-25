from __future__ import annotations


AUDIO_BUFFER_FRAME_OPTIONS = (128, 256, 512, 1_024, 2_048, 4_096, 8_192)
QT_AUDIO_FRAME_OPTIONS = (128, 256, 512, 1_024, 2_048, 4_096)
AUDIO_RESPONSE_FRAME_OPTIONS = (128, 256, 512)
AUDIO_CHUNK_FRAME_OPTIONS = (256, 512, 1_024)
AUDIO_FALLBACK_INTERVAL_OPTIONS_MS = (2, 4, 8)
DEFAULT_AUDIO_BUFFER_FRAMES = 512
DEFAULT_QT_AUDIO_FRAMES = 1_024
DEFAULT_AUDIO_RESPONSE_FRAMES = 256
DEFAULT_AUDIO_CHUNK_FRAMES = 1_024
DEFAULT_AUDIO_FALLBACK_INTERVAL_MS = 4


def normalize_audio_buffer_frames(value: object) -> int:
    try:
        frames = int(value)
    except (TypeError, ValueError):
        return DEFAULT_AUDIO_BUFFER_FRAMES
    if frames in AUDIO_BUFFER_FRAME_OPTIONS:
        return frames
    return DEFAULT_AUDIO_BUFFER_FRAMES


def normalize_qt_audio_frames(
    value: object,
    *,
    default: int = DEFAULT_QT_AUDIO_FRAMES,
) -> int:
    try:
        frames = int(value)
    except (TypeError, ValueError):
        return default
    if frames in QT_AUDIO_FRAME_OPTIONS:
        return frames
    return default


def normalize_audio_response_frames(value: object) -> int:
    try:
        frames = int(value)
    except (TypeError, ValueError):
        return DEFAULT_AUDIO_RESPONSE_FRAMES
    if frames in AUDIO_RESPONSE_FRAME_OPTIONS:
        return frames
    return DEFAULT_AUDIO_RESPONSE_FRAMES


def normalize_audio_chunk_frames(value: object) -> int:
    try:
        frames = int(value)
    except (TypeError, ValueError):
        return DEFAULT_AUDIO_CHUNK_FRAMES
    if frames in AUDIO_CHUNK_FRAME_OPTIONS:
        return frames
    return DEFAULT_AUDIO_CHUNK_FRAMES


def normalize_audio_fallback_interval_ms(value: object) -> int:
    try:
        interval = int(value)
    except (TypeError, ValueError):
        return DEFAULT_AUDIO_FALLBACK_INTERVAL_MS
    if interval in AUDIO_FALLBACK_INTERVAL_OPTIONS_MS:
        return interval
    return DEFAULT_AUDIO_FALLBACK_INTERVAL_MS
