from __future__ import annotations


AUDIO_BUFFER_FRAME_OPTIONS = (128, 256, 512, 1_024, 2_048, 4_096, 8_192)
DEFAULT_AUDIO_BUFFER_FRAMES = 512
DEFAULT_QT_AUDIO_FRAMES = 1_024


def normalize_audio_buffer_frames(value: object) -> int:
    try:
        frames = int(value)
    except (TypeError, ValueError):
        return DEFAULT_AUDIO_BUFFER_FRAMES
    if frames in AUDIO_BUFFER_FRAME_OPTIONS:
        return frames
    return DEFAULT_AUDIO_BUFFER_FRAMES
