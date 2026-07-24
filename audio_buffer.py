from __future__ import annotations


AUDIO_BUFFER_FRAME_OPTIONS = (128, 256, 512, 1_024, 2_048, 4_096, 8_192)
QT_AUDIO_FRAME_OPTIONS = (128, 256, 512, 1_024, 2_048, 4_096)
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


def qt_audio_frame_ceiling(value: object) -> int:
    try:
        frames = max(1, int(value))
    except (TypeError, ValueError):
        return DEFAULT_QT_AUDIO_FRAMES
    return next(
        (
            option
            for option in QT_AUDIO_FRAME_OPTIONS
            if option >= frames
        ),
        QT_AUDIO_FRAME_OPTIONS[-1],
    )
