from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from config import (
    DEFAULT_COUNTDOWN_SECONDS,
    DEFAULT_INPUT_CONVERSION_MODE,
    DEFAULT_KEY_BINDINGS,
    DEFAULT_KEYBOARD_PAUSE_SHORTCUT,
    DEFAULT_KEYBOARD_PLAY_SHORTCUT,
    DEFAULT_KEYBOARD_STOP_SHORTCUT,
    DEFAULT_MIDI_COLUMN_WIDTHS,
    DEFAULT_PANEL_ORDER,
    DEFAULT_SECTION_VISIBILITY,
    DEFAULT_SOUND_PLAYBACK_MODE,
    MAX_OCTAVE_SHIFT,
    MAX_TRANSPOSE_SEMITONES,
    MIN_OCTAVE_SHIFT,
    MIN_TRANSPOSE_SEMITONES,
    normalized_key_bindings,
    normalize_special_binding,
    normalize_input_conversion_mode,
    normalize_midi_column_widths,
    normalize_panel_order,
    normalize_section_visibility,
    normalize_sound_playback_mode,
)
from i18n import normalize_color_theme, normalize_language
from playback_timing import MAX_PLAYBACK_SPEED_PERCENT, MIN_PLAYBACK_SPEED_PERCENT
from audio_buffer import (
    DEFAULT_AUDIO_BUFFER_FRAMES,
    DEFAULT_AUDIO_CHUNK_FRAMES,
    DEFAULT_AUDIO_FALLBACK_INTERVAL_MS,
    DEFAULT_AUDIO_RESPONSE_FRAMES,
    DEFAULT_QT_AUDIO_FRAMES,
    normalize_audio_buffer_frames,
    normalize_audio_chunk_frames,
    normalize_audio_fallback_interval_ms,
    normalize_audio_response_frames,
    normalize_qt_audio_frames,
)
from sound_sources import DEFAULT_SOUND_SOURCE, normalize_sound_source
from piano_arrangement_models import normalize_arrangement_quality


SETTINGS_FILE_NAME = "settings.json"
_last_settings_error = ""


@dataclass(frozen=True)
class AppSettings:
    countdown_seconds: int = DEFAULT_COUNTDOWN_SECONDS
    midi_sound_volume: int = 80
    sound_source: str = DEFAULT_SOUND_SOURCE
    arrangement_quality: str = "beta"
    use_piano_arrangement: bool = True
    play_sound: bool = True
    countdown_sound: bool = False
    game_countdown_sound: bool = False
    auto_fit_note_range: bool = False
    transpose_semitones: int = 0
    octave_shift: int = 0
    humanize_timing: bool = False
    chord_optimization: bool = False
    chord_strum: bool = False
    auto_sustain: bool = False
    repeat_prevention: bool = False
    playback_speed_percent: int = 100
    sound_playback_mode: str = DEFAULT_SOUND_PLAYBACK_MODE
    language: str = "en"
    color_theme: str = "sky_blue"
    always_on_top: bool = False
    tray_resident: bool = False
    run_as_administrator: bool = False
    hide_release_notes_on_startup: bool = False
    window_opacity: int = 100
    ui_scale_percent: int = 100
    window_width: int = 900
    window_height: int = 560
    midi_column_widths: tuple[int, int, int] = DEFAULT_MIDI_COLUMN_WIDTHS
    playlist_name_width: int = 240
    last_midi_folder: str = ""
    keyboard_play_shortcut: str = DEFAULT_KEYBOARD_PLAY_SHORTCUT
    keyboard_pause_shortcut: str = DEFAULT_KEYBOARD_PAUSE_SHORTCUT
    keyboard_stop_shortcut: str = DEFAULT_KEYBOARD_STOP_SHORTCUT
    shortcut_locked: bool = True
    midi_input_device: str = ""
    input_conversion_mode: str = DEFAULT_INPUT_CONVERSION_MODE
    key_bindings: dict[int, str] | None = None
    sustain_key: str = "space"
    octave_down_key: str = "<"
    octave_up_key: str = ">"
    panel_order: tuple[str, ...] = DEFAULT_PANEL_ORDER
    section_visibility: dict[str, bool] = field(
        default_factory=lambda: dict(DEFAULT_SECTION_VISIBILITY)
    )
    last_update_check_at: int = 0
    audio_qt_frames: int = DEFAULT_QT_AUDIO_FRAMES
    audio_buffer_frames: int = DEFAULT_AUDIO_BUFFER_FRAMES
    audio_response_frames: int = DEFAULT_AUDIO_RESPONSE_FRAMES
    audio_chunk_frames: int = DEFAULT_AUDIO_CHUNK_FRAMES
    audio_fallback_interval_ms: int = DEFAULT_AUDIO_FALLBACK_INTERVAL_MS

def load_settings() -> AppSettings:
    global _last_settings_error
    _last_settings_error = ""
    path = _settings_path()
    temporary_path = _temporary_settings_path(path)
    candidates = [
        candidate
        for candidate in (path, temporary_path)
        if candidate.exists()
    ]
    if not candidates:
        return AppSettings()

    data: object | None = None
    errors: list[str] = []
    for candidate in candidates:
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            if candidate == temporary_path:
                _last_settings_error = "Recovered settings from an interrupted save"
                try:
                    os.replace(temporary_path, path)
                except OSError:
                    pass
            elif temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass
            break
        except Exception as exc:
            errors.append(f"{candidate.name}: {exc}")
    if not isinstance(data, dict):
        _last_settings_error = "Settings could not be loaded: " + "; ".join(errors)
        return AppSettings()

    keyboard_shortcuts = (
        _parse_shortcut(
            data.get("keyboard_play_shortcut"),
            default=DEFAULT_KEYBOARD_PLAY_SHORTCUT,
        ),
        _parse_shortcut(
            data.get("keyboard_pause_shortcut"),
            default=DEFAULT_KEYBOARD_PAUSE_SHORTCUT,
        ),
        _parse_shortcut(
            data.get("keyboard_stop_shortcut"),
            default=DEFAULT_KEYBOARD_STOP_SHORTCUT,
        ),
    )
    if keyboard_shortcuts == ("F5", "F7", "F6"):
        keyboard_shortcuts = (
            DEFAULT_KEYBOARD_PLAY_SHORTCUT,
            DEFAULT_KEYBOARD_PAUSE_SHORTCUT,
            DEFAULT_KEYBOARD_STOP_SHORTCUT,
        )

    settings = AppSettings(
        countdown_seconds=_clamp_int(
            data.get("countdown_seconds"),
            minimum=0,
            maximum=10,
            default=DEFAULT_COUNTDOWN_SECONDS,
        ),
        midi_sound_volume=_clamp_int(
            data.get("midi_sound_volume"),
            minimum=0,
            maximum=100,
            default=80,
        ),
        sound_source=normalize_sound_source(data.get("sound_source")),
        arrangement_quality=normalize_arrangement_quality(
            data.get("arrangement_quality")
        ).value,
        use_piano_arrangement=_parse_bool(
            data.get("use_piano_arrangement"),
            default=True,
        ),
        play_sound=_parse_bool(data.get("play_sound"), default=True),
        countdown_sound=_parse_bool(data.get("countdown_sound"), default=False),
        game_countdown_sound=_parse_bool(data.get("game_countdown_sound"), default=False),
        auto_fit_note_range=_parse_bool(data.get("auto_fit_note_range"), default=False),
        transpose_semitones=_clamp_int(
            data.get("transpose_semitones"),
            minimum=MIN_TRANSPOSE_SEMITONES,
            maximum=MAX_TRANSPOSE_SEMITONES,
            default=0,
        ),
        octave_shift=_clamp_int(
            data.get("octave_shift"),
            minimum=MIN_OCTAVE_SHIFT,
            maximum=MAX_OCTAVE_SHIFT,
            default=0,
        ),
        humanize_timing=_parse_bool(data.get("humanize_timing"), default=False),
        chord_optimization=_parse_bool(
            data.get("chord_optimization"),
            default=False,
        ),
        chord_strum=_parse_bool(data.get("chord_strum"), default=False),
        auto_sustain=_parse_bool(data.get("auto_sustain"), default=False),
        repeat_prevention=_parse_bool(data.get("repeat_prevention"), default=False),
        playback_speed_percent=_clamp_int(
            data.get("playback_speed_percent"),
            minimum=MIN_PLAYBACK_SPEED_PERCENT,
            maximum=MAX_PLAYBACK_SPEED_PERCENT,
            default=100,
        ),
        sound_playback_mode=normalize_sound_playback_mode(
            data.get("sound_playback_mode")
        ),
        language=normalize_language(data.get("language")),
        color_theme=normalize_color_theme(data.get("color_theme")),
        always_on_top=_parse_bool(data.get("always_on_top"), default=False),
        tray_resident=_parse_bool(data.get("tray_resident"), default=False),
        run_as_administrator=_parse_bool(
            data.get("run_as_administrator"),
            default=False,
        ),
        hide_release_notes_on_startup=_parse_bool(
            data.get("hide_release_notes_on_startup"),
            default=False,
        ),
        window_opacity=_clamp_int(data.get("window_opacity"), minimum=30, maximum=100, default=100),
        ui_scale_percent=_clamp_int(data.get("ui_scale_percent"), minimum=100, maximum=200, default=100),
        window_width=_clamp_int(data.get("window_width"), minimum=1, maximum=10000, default=900),
        window_height=_clamp_int(data.get("window_height"), minimum=1, maximum=2000, default=560),
        midi_column_widths=normalize_midi_column_widths(
            data.get("midi_column_widths")
        ),
        playlist_name_width=_clamp_int(
            data.get("playlist_name_width"),
            minimum=80,
            maximum=2000,
            default=240,
        ),
        last_midi_folder=_parse_str(data.get("last_midi_folder")),
        keyboard_play_shortcut=keyboard_shortcuts[0],
        keyboard_pause_shortcut=keyboard_shortcuts[1],
        keyboard_stop_shortcut=keyboard_shortcuts[2],
        shortcut_locked=_parse_bool(data.get("shortcut_locked"), default=True),
        midi_input_device=_parse_str(data.get("midi_input_device")),
        input_conversion_mode=normalize_input_conversion_mode(
            data.get("input_conversion_mode")
        ),
        key_bindings=normalized_key_bindings(data.get("key_bindings")),
        sustain_key=normalize_special_binding(data.get("sustain_key"), "space"),
        octave_down_key=normalize_special_binding(data.get("octave_down_key"), "<"),
        octave_up_key=normalize_special_binding(data.get("octave_up_key"), ">"),
        panel_order=normalize_panel_order(data.get("panel_order")),
        section_visibility=normalize_section_visibility(
            data.get("section_visibility")
        ),
        last_update_check_at=_parse_nonnegative_int(
            data.get("last_update_check_at")
        ),
        audio_qt_frames=normalize_qt_audio_frames(
            data.get("audio_qt_frames")
        ),
        audio_buffer_frames=normalize_audio_buffer_frames(
            data.get("audio_buffer_frames")
        ),
        audio_response_frames=normalize_audio_response_frames(
            data.get("audio_response_frames")
        ),
        audio_chunk_frames=normalize_audio_chunk_frames(
            data.get("audio_chunk_frames")
        ),
        audio_fallback_interval_ms=normalize_audio_fallback_interval_ms(
            data.get("audio_fallback_interval_ms")
        ),
    )
    return settings


def save_settings(settings: AppSettings) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = _temporary_settings_path(path)
    payload = json.dumps(
        {
            "countdown_seconds": settings.countdown_seconds,
            "midi_sound_volume": settings.midi_sound_volume,
            "sound_source": settings.sound_source,
            "arrangement_quality": normalize_arrangement_quality(
                settings.arrangement_quality
            ).value,
            "use_piano_arrangement": settings.use_piano_arrangement,
            "play_sound": settings.play_sound,
            "countdown_sound": settings.countdown_sound,
            "game_countdown_sound": settings.game_countdown_sound,
            "auto_fit_note_range": settings.auto_fit_note_range,
            "transpose_semitones": settings.transpose_semitones,
            "octave_shift": settings.octave_shift,
            "humanize_timing": settings.humanize_timing,
            "chord_optimization": settings.chord_optimization,
            "chord_strum": settings.chord_strum,
            "auto_sustain": settings.auto_sustain,
            "repeat_prevention": settings.repeat_prevention,
            "playback_speed_percent": settings.playback_speed_percent,
            "sound_playback_mode": normalize_sound_playback_mode(
                settings.sound_playback_mode
            ),
            "language": settings.language,
            "color_theme": settings.color_theme,
            "always_on_top": settings.always_on_top,
            "tray_resident": settings.tray_resident,
            "run_as_administrator": settings.run_as_administrator,
            "hide_release_notes_on_startup": (
                settings.hide_release_notes_on_startup
            ),
            "window_opacity": settings.window_opacity,
            "ui_scale_percent": settings.ui_scale_percent,
            "window_width": settings.window_width,
            "window_height": settings.window_height,
            "midi_column_widths": list(
                normalize_midi_column_widths(settings.midi_column_widths)
            ),
            "playlist_name_width": _clamp_int(
                settings.playlist_name_width,
                minimum=80,
                maximum=2000,
                default=240,
            ),
            "last_midi_folder": settings.last_midi_folder,
            "keyboard_play_shortcut": settings.keyboard_play_shortcut,
            "keyboard_pause_shortcut": settings.keyboard_pause_shortcut,
            "keyboard_stop_shortcut": settings.keyboard_stop_shortcut,
            "shortcut_locked": settings.shortcut_locked,
            "midi_input_device": settings.midi_input_device,
            "input_conversion_mode": normalize_input_conversion_mode(
                settings.input_conversion_mode
            ),
            "key_bindings": {
                str(note): key
                for note, key in normalized_key_bindings(settings.key_bindings).items()
                if DEFAULT_KEY_BINDINGS[note] != key
            },
            "sustain_key": settings.sustain_key,
            "octave_down_key": settings.octave_down_key,
            "octave_up_key": settings.octave_up_key,
            "panel_order": list(normalize_panel_order(settings.panel_order)),
            "section_visibility": normalize_section_visibility(
                settings.section_visibility
            ),
            "last_update_check_at": _parse_nonnegative_int(
                settings.last_update_check_at
            ),
            "audio_qt_frames": normalize_qt_audio_frames(
                settings.audio_qt_frames
            ),
            "audio_buffer_frames": normalize_audio_buffer_frames(
                settings.audio_buffer_frames
            ),
            "audio_response_frames": normalize_audio_response_frames(
                settings.audio_response_frames
            ),
            "audio_chunk_frames": normalize_audio_chunk_frames(
                settings.audio_chunk_frames
            ),
            "audio_fallback_interval_ms": normalize_audio_fallback_interval_ms(
                settings.audio_fallback_interval_ms
            ),
        },
        indent=2,
        ensure_ascii=False,
    )
    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    except Exception:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def consume_settings_error() -> str:
    global _last_settings_error
    error = _last_settings_error
    _last_settings_error = ""
    return error


def _parse_nonnegative_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _settings_path() -> Path:
    return _application_directory() / SETTINGS_FILE_NAME


def _application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def application_directory() -> Path:
    return _application_directory()


def _temporary_settings_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.tmp")


def _clamp_int(value: object, minimum: int, maximum: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _parse_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def _parse_str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _parse_shortcut(value: object, default: str) -> str:
    if not isinstance(value, str):
        return default
    shortcut = value.strip()
    return shortcut or default
