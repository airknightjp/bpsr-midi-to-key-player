from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from audio_buffer import DEFAULT_AUDIO_BUFFER_FRAMES, DEFAULT_QT_AUDIO_FRAMES
from config import (
    DEFAULT_INPUT_CONVERSION_MODE,
    DEFAULT_KEYBOARD_PAUSE_SHORTCUT,
    DEFAULT_KEYBOARD_PLAY_SHORTCUT,
    DEFAULT_KEYBOARD_STOP_SHORTCUT,
    DEFAULT_MIDI_COLUMN_WIDTHS,
    DEFAULT_PANEL_ORDER,
    DEFAULT_SECTION_VISIBILITY,
    DEFAULT_SOUND_PLAYBACK_MODE,
)


@dataclass(frozen=True)
class MidiListRow:
    path: Path
    name: str
    folder: str = ""
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
    input_conversion_mode: str = DEFAULT_INPUT_CONVERSION_MODE
    active_output_notes: frozenset[int] = field(default_factory=frozenset)
    output_note_retrigger_events: tuple[tuple[int, int], ...] = ()
    output_note_retrigger_serial: int = 0
    realtime_output_notes: frozenset[int] = field(default_factory=frozenset)
    realtime_note_trigger_events: tuple[tuple[int, int], ...] = ()
    realtime_note_trigger_serial: int = 0
    realtime_visible_output_notes: frozenset[int] = field(default_factory=frozenset)
    realtime_output_retrigger_events: tuple[tuple[int, int], ...] = ()
    realtime_output_retrigger_serial: int = 0
    rhythm_score: int = 0
    rhythm_combo: int = 0
    rhythm_judgment: str = ""
    rhythm_multiplier_tenths: int = 10
    rhythm_hit_events: tuple[tuple[int, int, str, bool], ...] = ()
    midi_rows: list[MidiListRow] = field(default_factory=list)
    selected_midi_index: int = -1
    track_channels: list[TrackChannelItem] = field(default_factory=list)
    midi_input_devices: list[str] = field(default_factory=list)
    midi_input_device: str = ""
    countdown_seconds: int = 3
    midi_sound_volume: int = 80
    sound_source: str = "piano"
    audio_qt_frames: int = DEFAULT_QT_AUDIO_FRAMES
    audio_buffer_frames: int = DEFAULT_AUDIO_BUFFER_FRAMES
    playback_speed_percent: int = 100
    sound_playback_mode: str = DEFAULT_SOUND_PLAYBACK_MODE
    dry_run: bool = True
    countdown_sound: bool = False
    game_countdown_sound: bool = False
    auto_fit_note_range: bool = False
    transpose_semitones: int = 0
    octave_shift: int = 0
    humanize_timing: bool = False
    chord_optimization: bool = False
    chord_strum: bool = False
    auto_sustain: bool = False
    sustain_key: str = "space"
    octave_down_key: str = "<"
    octave_up_key: str = ">"
    repeat_prevention: bool = False
    keyboard_play_shortcut: str = DEFAULT_KEYBOARD_PLAY_SHORTCUT
    keyboard_pause_shortcut: str = DEFAULT_KEYBOARD_PAUSE_SHORTCUT
    keyboard_stop_shortcut: str = DEFAULT_KEYBOARD_STOP_SHORTCUT
    shortcut_locked: bool = True
    always_on_top: bool = False
    tray_resident: bool = False
    hide_release_notes_on_startup: bool = False
    window_opacity: int = 100
    ui_scale_percent: int = 100
    window_width: int = 900
    window_height: int = 560
    midi_column_widths: tuple[int, int, int, int] = DEFAULT_MIDI_COLUMN_WIDTHS
    section_visibility: dict[str, bool] = field(
        default_factory=lambda: dict(DEFAULT_SECTION_VISIBILITY)
    )
    panel_order: tuple[str, ...] = DEFAULT_PANEL_ORDER

    @property
    def keyboard_playing(self) -> bool:
        return self.current_mode == "keys"

    @property
    def keyboard_paused(self) -> bool:
        return self.current_mode == "keys_paused"

    @property
    def sound_playing(self) -> bool:
        return self.current_mode == "sound"

    @property
    def sound_paused(self) -> bool:
        return self.current_mode == "sound_paused"
