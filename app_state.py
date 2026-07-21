from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from config import (
    DEFAULT_KEYBOARD_PAUSE_SHORTCUT,
    DEFAULT_KEYBOARD_PLAY_SHORTCUT,
    DEFAULT_KEYBOARD_STOP_SHORTCUT,
)


@dataclass(frozen=True)
class MidiListRow:
    path: Path
    name: str
    duration: str = "--:--"
    note_range: str = "--"


@dataclass(frozen=True)
class TrackChannelItem:
    track: int
    channel: int
    enabled: bool = True


@dataclass
class AppState:
    language: str = "en"
    color_theme: str = "sky_blue"
    status: str = "waiting.."
    position: float = 0.0
    duration: float = 0.0
    current_mode: str | None = None
    midi_input_running: bool = False
    midi_rows: list[MidiListRow] = field(default_factory=list)
    selected_midi_index: int = -1
    track_channels: list[TrackChannelItem] = field(default_factory=list)
    midi_input_devices: list[str] = field(default_factory=list)
    midi_input_device: str = ""
    countdown_seconds: int = 3
    midi_sound_volume: int = 80
    playback_speed_percent: int = 100
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
    keyboard_play_shortcut: str = DEFAULT_KEYBOARD_PLAY_SHORTCUT
    keyboard_pause_shortcut: str = DEFAULT_KEYBOARD_PAUSE_SHORTCUT
    keyboard_stop_shortcut: str = DEFAULT_KEYBOARD_STOP_SHORTCUT
    shortcut_locked: bool = True
    always_on_top: bool = False
    tray_resident: bool = False
    window_opacity: int = 100
    ui_scale_percent: int = 100
    window_width: int = 900
    window_height: int = 560
    section_visibility: dict[str, bool] = field(
        default_factory=lambda: {
            "midi_input": True,
            "key_playback": True,
            "common_settings": True,
            "player": True,
        }
    )

    @property
    def keyboard_playing(self) -> bool:
        return self.current_mode == "keys"

    @property
    def keyboard_paused(self) -> bool:
        return self.current_mode == "keys_paused"

    @property
    def sound_playing(self) -> bool:
        return self.current_mode == "sound"
