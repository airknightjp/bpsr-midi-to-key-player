from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from config import (
    DEFAULT_COUNTDOWN_SECONDS,
    DEFAULT_KEY_BINDINGS,
    MAX_OCTAVE_SHIFT,
    MAX_TRANSPOSE_SEMITONES,
    MIN_OCTAVE_SHIFT,
    MIN_TRANSPOSE_SEMITONES,
    normalized_key_bindings,
)
from i18n import normalize_color_theme, normalize_language
from playback_timing import MAX_PLAYBACK_SPEED_PERCENT, MIN_PLAYBACK_SPEED_PERCENT


APP_DIR_NAME = "BPSR_MIDI_to_KEY_Player"
SETTINGS_FILE_NAME = "settings.json"
_last_settings_error = ""


@dataclass(frozen=True)
class AppSettings:
    countdown_seconds: int = DEFAULT_COUNTDOWN_SECONDS
    midi_sound_volume: int = 80
    dry_run: bool = True
    countdown_sound: bool = False
    game_countdown_sound: bool = False
    auto_fit_note_range: bool = False
    transpose_semitones: int = 0
    octave_shift: int = 0
    humanize_timing: bool = False
    chord_optimization: bool = False
    chord_strum: bool = False
    repeat_prevention: bool = False
    playback_speed_percent: int = 100
    language: str = "en"
    color_theme: str = "sky_blue"
    always_on_top: bool = False
    tray_resident: bool = False
    window_opacity: int = 100
    window_height: int = 560
    last_midi_folder: str = ""
    keyboard_play_shortcut: str = "F5"
    keyboard_stop_shortcut: str = "F6"
    shortcut_locked: bool = True
    midi_input_device: str = ""
    key_bindings: dict[int, str] | None = None

    def resolved_key_bindings(self) -> dict[int, str]:
        return normalized_key_bindings(self.key_bindings)


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
        dry_run=_parse_bool(data.get("dry_run"), default=True),
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
        chord_optimization=_parse_bool(data.get("chord_optimization"), default=False),
        chord_strum=_parse_bool(data.get("chord_strum"), default=False),
        repeat_prevention=_parse_bool(data.get("repeat_prevention"), default=False),
        playback_speed_percent=_clamp_int(
            data.get("playback_speed_percent"),
            minimum=MIN_PLAYBACK_SPEED_PERCENT,
            maximum=MAX_PLAYBACK_SPEED_PERCENT,
            default=100,
        ),
        language=normalize_language(data.get("language")),
        color_theme=normalize_color_theme(data.get("color_theme")),
        always_on_top=_parse_bool(data.get("always_on_top"), default=False),
        tray_resident=_parse_bool(data.get("tray_resident"), default=False),
        window_opacity=_clamp_int(data.get("window_opacity"), minimum=30, maximum=100, default=100),
        window_height=_clamp_int(data.get("window_height"), minimum=480, maximum=2000, default=560),
        last_midi_folder=_parse_str(data.get("last_midi_folder")),
        keyboard_play_shortcut=_parse_shortcut(data.get("keyboard_play_shortcut"), default="F5"),
        keyboard_stop_shortcut=_parse_shortcut(data.get("keyboard_stop_shortcut"), default="F6"),
        shortcut_locked=_parse_bool(data.get("shortcut_locked"), default=True),
        midi_input_device=_parse_str(data.get("midi_input_device")),
        key_bindings=normalized_key_bindings(data.get("key_bindings")),
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
            "dry_run": settings.dry_run,
            "countdown_sound": settings.countdown_sound,
            "game_countdown_sound": settings.game_countdown_sound,
            "auto_fit_note_range": settings.auto_fit_note_range,
            "transpose_semitones": settings.transpose_semitones,
            "octave_shift": settings.octave_shift,
            "humanize_timing": settings.humanize_timing,
            "chord_optimization": settings.chord_optimization,
            "chord_strum": settings.chord_strum,
            "repeat_prevention": settings.repeat_prevention,
            "playback_speed_percent": settings.playback_speed_percent,
            "language": settings.language,
            "color_theme": settings.color_theme,
            "always_on_top": settings.always_on_top,
            "tray_resident": settings.tray_resident,
            "window_opacity": settings.window_opacity,
            "window_height": settings.window_height,
            "last_midi_folder": settings.last_midi_folder,
            "keyboard_play_shortcut": settings.keyboard_play_shortcut,
            "keyboard_stop_shortcut": settings.keyboard_stop_shortcut,
            "shortcut_locked": settings.shortcut_locked,
            "midi_input_device": settings.midi_input_device,
            "key_bindings": {
                str(note): key
                for note, key in normalized_key_bindings(settings.key_bindings).items()
                if DEFAULT_KEY_BINDINGS[note] != key
            },
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


def _settings_path() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_DIR_NAME / SETTINGS_FILE_NAME
    return Path.home() / f".{APP_DIR_NAME}" / SETTINGS_FILE_NAME


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
