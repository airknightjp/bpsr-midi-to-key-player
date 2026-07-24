from __future__ import annotations

import queue
import threading
import time
import winsound
from dataclasses import replace
from pathlib import Path
from typing import Callable, Protocol

from audio_buffer import (
    normalize_audio_buffer_frames,
    normalize_qt_audio_frames,
)
from app_state import AppState, MidiListRow, TrackChannelItem
from chord_optimization import ChordOptimizationPlan
from config import (
    INPUT_CONVERSION_MIDI_FILE,
    INPUT_CONVERSION_REALTIME,
    DEFAULT_KEY_BINDINGS,
    DEFAULT_KEYBOARD_PAUSE_SHORTCUT,
    DEFAULT_KEYBOARD_PLAY_SHORTCUT,
    DEFAULT_KEYBOARD_STOP_SHORTCUT,
    OCTAVE_DOWN_KEY,
    OCTAVE_UP_KEY,
    SUSTAIN_KEY,
    MAX_OCTAVE_SHIFT,
    MAX_TRANSPOSE_SEMITONES,
    MIN_OCTAVE_SHIFT,
    MIN_TRANSPOSE_SEMITONES,
    PIANO_NOTE_MAX,
    PIANO_NOTE_MIN,
    SOUND_PLAYBACK_MODE_CONTINUOUS,
    SOUND_PLAYBACK_MODE_OFF,
    SOUND_PLAYBACK_MODE_REPEAT_ONE,
    SOUND_PLAYBACK_MODES,
    normalized_key_bindings,
    normalize_special_binding,
    normalize_input_conversion_mode,
    normalize_panel_order,
    normalize_section_visibility,
    normalize_sound_playback_mode,
)
from global_hotkeys import GlobalHotkeyManager, shortcut_to_hotkey_spec
from i18n import TEXT, normalize_color_theme, normalize_language
from keyboard_output import KeyboardOutput
from live_midi_input import MidiInputKeyboardBridge, list_midi_input_devices
from midi_parser import MidiEvent, MidiSummary, parse_midi
from playback_timing import MAX_PLAYBACK_SPEED_PERCENT, MIN_PLAYBACK_SPEED_PERCENT
from player import MidiKeyboardPlayer
from rhythm_scoring import RhythmHit, RhythmScorer
from settings import AppSettings, consume_settings_error, load_settings, save_settings
from sound_sources import normalize_sound_source
from sound_player import MidiSoundPlayer, RealtimeMidiSoundOutput


GAME_COUNTDOWN_KEY_HOLD_SECONDS = 0.12
OUTPUT_NOTE_MIN_VISIBLE_SECONDS = 0.075
RHYTHM_HIT_EVENT_HISTORY_LIMIT = 128
UI_SCALE_PERCENT_OPTIONS = (100, 110, 125, 150, 175, 200)


class ControllerView(Protocol):
    def render(self, state: AppState) -> None: ...

    def append_log(self, message: str) -> None: ...

    def clear_log(self) -> None: ...

    def show_message(self, level: str, title: str, message: str) -> None: ...

    def schedule_output_note_release(self, delay_ms: int) -> None: ...

    def schedule_rhythm_score_update(self, delay_ms: int | None) -> None: ...


class NullView:
    def render(self, _state: AppState) -> None:
        pass

    def append_log(self, _message: str) -> None:
        pass

    def clear_log(self) -> None:
        pass

    def show_message(self, _level: str, _title: str, _message: str) -> None:
        pass

    def schedule_output_note_release(self, _delay_ms: int) -> None:
        pass

    def schedule_rhythm_score_update(self, _delay_ms: int | None) -> None:
        pass


class AppController:
    """UI-independent application state and orchestration layer."""

    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or load_settings()
        self.settings_load_error = consume_settings_error()
        self.state = AppState(
            language=self.settings.language,
            color_theme=self.settings.color_theme,
            status=TEXT[self.settings.language]["waiting"],
            countdown_seconds=self.settings.countdown_seconds,
            midi_sound_volume=self.settings.midi_sound_volume,
            sound_source=self.settings.sound_source,
            playback_speed_percent=self.settings.playback_speed_percent,
            sound_playback_mode=normalize_sound_playback_mode(
                self.settings.sound_playback_mode
            ),
            dry_run=self.settings.dry_run,
            countdown_sound=self.settings.countdown_sound,
            game_countdown_sound=self.settings.game_countdown_sound,
            auto_fit_note_range=self.settings.auto_fit_note_range,
            transpose_semitones=self.settings.transpose_semitones,
            octave_shift=self.settings.octave_shift,
            humanize_timing=self.settings.humanize_timing,
            chord_optimization=self.settings.chord_optimization,
            chord_strum=self.settings.chord_strum,
            auto_sustain=self.settings.auto_sustain,
            repeat_prevention=self.settings.repeat_prevention,
            sustain_key=self.settings.sustain_key,
            octave_down_key=self.settings.octave_down_key,
            octave_up_key=self.settings.octave_up_key,
            keyboard_play_shortcut=self.settings.keyboard_play_shortcut,
            keyboard_pause_shortcut=self.settings.keyboard_pause_shortcut,
            keyboard_stop_shortcut=self.settings.keyboard_stop_shortcut,
            shortcut_locked=self.settings.shortcut_locked,
            always_on_top=self.settings.always_on_top,
            tray_resident=self.settings.tray_resident,
            hide_release_notes_on_startup=(
                self.settings.hide_release_notes_on_startup
            ),
            window_opacity=self.settings.window_opacity,
            ui_scale_percent=self._normalize_ui_scale(self.settings.ui_scale_percent),
            window_width=max(1, self.settings.window_width),
            window_height=max(1, self.settings.window_height),
            midi_input_device=self.settings.midi_input_device,
            input_conversion_mode=normalize_input_conversion_mode(
                self.settings.input_conversion_mode
            ),
            section_visibility=normalize_section_visibility(
                self.settings.section_visibility
            ),
            panel_order=normalize_panel_order(self.settings.panel_order),
            audio_buffer_frames=normalize_audio_buffer_frames(
                self.settings.automatic_audio_buffer_frames
            ),
        )
        self.view: ControllerView = NullView()
        self.events: list[MidiEvent] = []
        self.summary: MidiSummary | None = None
        self.midi_files: list[Path] = []
        self.last_midi_folder = self.settings.last_midi_folder
        self.last_update_check_at = self.settings.last_update_check_at
        self.minimum_stable_qt_frames = (
            self.settings.minimum_stable_qt_frames
        )
        self.qt_audio_environment = self.settings.qt_audio_environment
        self.key_bindings = normalized_key_bindings(self.settings.key_bindings)
        self.enabled_sources_snapshot: frozenset[tuple[int, int]] = frozenset()
        self.enabled_channels_snapshot: frozenset[int] = frozenset()
        self._source_lock = threading.RLock()
        self.player: MidiKeyboardPlayer | None = None
        self.sound_player: MidiSoundPlayer | None = None
        self.midi_input_bridge: MidiInputKeyboardBridge | None = None
        self.realtime_sound_output: RealtimeMidiSoundOutput | None = None
        self.worker_queue: queue.Queue[tuple[object, ...]] = queue.Queue()
        self.metadata_queue: queue.Queue[tuple[int, Path, str, str]] = queue.Queue()
        self._event_notifier: Callable[[], None] | None = None
        self._event_notification_lock = threading.Lock()
        self._event_notification_pending = False
        self.metadata_cancel = threading.Event()
        self.metadata_scan_id = 0
        self.playback_id = 0
        self.position_generation = 0
        self.midi_input_id = 0
        self._active_output_notes_by_source: dict[tuple[str, int], set[int]] = {}
        self._output_note_visible_until: dict[int, float] = {}
        self._output_note_release_due: dict[int, float] = {}
        self._realtime_note_visible_until: dict[int, float] = {}
        self._realtime_note_release_due: dict[int, float] = {}
        self._rhythm_scorer = RhythmScorer()
        self._rhythm_hit_serial = 0
        self.seeking_keys = False
        self.global_hotkeys: GlobalHotkeyManager | None = None
        self.hotkey_failure_signature: tuple[str, ...] = ()
        self.settings_save_error = ""
        self._settings_dirty = False
        self.exiting = False

    def attach_view(self, view: ControllerView) -> None:
        self.view = view
        if self.settings_load_error:
            self._log(self.settings_load_error)
        self.refresh_midi_input_devices(notify=False)
        self._notify()

    def set_event_notifier(self, notifier: Callable[[], None] | None) -> None:
        callback: Callable[[], None] | None = None
        with self._event_notification_lock:
            self._event_notifier = notifier
            if notifier is None:
                self._event_notification_pending = False
            elif (
                not self._event_notification_pending
                and (not self.worker_queue.empty() or not self.metadata_queue.empty())
            ):
                self._event_notification_pending = True
                callback = notifier
        if callback is not None:
            self._emit_event_notification(callback)

    def _queue_worker_message(self, message: tuple[object, ...]) -> None:
        self.worker_queue.put(message)
        self._request_event_dispatch()

    def _queue_metadata_result(self, result: tuple[int, Path, str, str]) -> None:
        self.metadata_queue.put(result)
        self._request_event_dispatch()

    def _request_event_dispatch(self) -> None:
        callback: Callable[[], None] | None = None
        with self._event_notification_lock:
            if (
                not self.exiting
                and not self._event_notification_pending
                and self._event_notifier is not None
            ):
                self._event_notification_pending = True
                callback = self._event_notifier
        if callback is not None:
            self._emit_event_notification(callback)

    def _complete_event_dispatch(self) -> None:
        callback: Callable[[], None] | None = None
        with self._event_notification_lock:
            self._event_notification_pending = False
            if (
                not self.exiting
                and self._event_notifier is not None
                and (not self.worker_queue.empty() or not self.metadata_queue.empty())
            ):
                self._event_notification_pending = True
                callback = self._event_notifier
        if callback is not None:
            self._emit_event_notification(callback)

    def _emit_event_notification(self, callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception:
            with self._event_notification_lock:
                self._event_notification_pending = False

    def start(self) -> None:
        self._bind_global_hotkeys()
        if self.last_midi_folder:
            folder = Path(self.last_midi_folder)
            if folder.is_dir():
                self.load_midi_folder(folder, save_folder=False, show_empty_message=False)

    def text(self, key: str) -> str:
        return TEXT[self.state.language][key]

    def load_midi_folder(
        self,
        folder_path: str | Path,
        *,
        save_folder: bool = True,
        show_empty_message: bool = True,
        preserve_sound_playback: bool = False,
    ) -> None:
        folder = Path(folder_path)
        if not preserve_sound_playback and self.state.current_mode is not None:
            self.stop_playback()
        try:
            files = sorted(
                (
                    path
                    for path in folder.iterdir()
                    if path.is_file() and path.suffix.lower() in {".mid", ".midi"}
                ),
                key=lambda path: path.name.lower(),
            )
        except OSError as exc:
            self._message("error", "load_failed_title", str(exc))
            return

        preserve_sound = preserve_sound_playback and self._sound_playback_is_active()
        self.midi_files = files
        self.state.midi_rows = [MidiListRow(path=path, name=path.name) for path in files]
        self.view.clear_log()
        self._log(self.text("folder_loaded_log").format(folder=str(folder), count=len(files)))
        self._start_metadata_scan(files)
        if save_folder:
            self.last_midi_folder = str(folder)
            self.request_save()

        if not files:
            if not preserve_sound:
                self.events = []
                self.summary = None
                self.state.duration = 0.0
                self.state.position = 0.0
                self.state.selected_midi_index = -1
                self.state.track_channels = []
                self.state.status = self.text("waiting")
                self._set_enabled_sources(())
            self._notify()
            if show_empty_message:
                self._message("info", "no_midi_title", self.text("no_midi_files"))
            return

        if preserve_sound:
            if self.summary is not None:
                self.state.selected_midi_index = self._find_midi_index(self.summary.path)
            self._notify()
            return
        self.select_midi(0)

    def reload_midi_folder(self) -> None:
        if not self.last_midi_folder:
            self._message("info", "no_midi_title", self.text("load_midi_first"))
            return
        folder = Path(self.last_midi_folder)
        if not folder.is_dir():
            self._message("info", "no_midi_title", self.text("no_midi_files"))
            return
        self.load_midi_folder(
            folder,
            save_folder=False,
            show_empty_message=True,
            preserve_sound_playback=True,
        )

    def select_midi(self, index: int) -> None:
        if not 0 <= index < len(self.midi_files):
            return
        selected = self.midi_files[index]
        switch_sound = self._sound_playback_is_active()
        preserve_sound_pause = self.state.sound_paused
        if switch_sound and self.summary is not None and selected == self.summary.path:
            self.state.selected_midi_index = index
            self._notify()
            return
        if preserve_sound_pause:
            self.state.current_mode = None
        if not self._load_midi_file(selected, stop_playback=not switch_sound):
            if preserve_sound_pause:
                self.state.current_mode = "sound_paused"
                self._notify()
            return
        self.state.selected_midi_index = index
        self._update_row_metadata(selected, self.summary)
        if switch_sound and self.sound_player:
            self._next_position_generation()
            self.sound_player.switch(self.events, start_time=0.0)
        elif preserve_sound_pause:
            self.state.current_mode = "sound_paused"
            self.state.status = "sound paused"
        self._notify()

    def _load_midi_file(self, path: Path, *, stop_playback: bool) -> bool:
        if stop_playback and self._playback_mode_is_active():
            self.stop_playback()
        try:
            events, summary = parse_midi(path)
        except Exception as exc:
            self._message("error", "load_failed_title", str(exc))
            return False
        self._reset_rhythm_score()
        self.events = events
        self.summary = summary
        self.state.duration = summary.duration
        self.state.position = 0.0
        self._set_track_channels(summary)
        channels = ", ".join(str(channel + 1) for channel in summary.channels) or self.text("none")
        self._log(
            self.text("loaded_log").format(
                name=path.name,
                event_count=summary.event_count,
                duration=summary.duration,
                channels=channels,
            )
        )
        return True

    def start_keyboard_conversion_from_shortcut(self) -> None:
        if (
            self.state.input_conversion_mode != INPUT_CONVERSION_MIDI_FILE
            or self.state.midi_input_running
            or self.state.sound_playing
            or self.state.keyboard_playing
        ):
            return
        if self.state.keyboard_paused or self.state.sound_paused:
            self.stop_playback()
            self.play_keyboard(start_time=0.0)
        elif self.state.current_mode is None:
            self.play_keyboard()

    def stop_keyboard_conversion_from_shortcut(self) -> None:
        if self.state.keyboard_playing or self.state.keyboard_paused:
            self.stop_playback()

    def toggle_input_conversion(self) -> None:
        if self.state.midi_input_running:
            self.stop_midi_input()
        elif self.state.keyboard_playing or self.state.keyboard_paused:
            self.stop_playback()
        elif self.state.input_conversion_mode == INPUT_CONVERSION_REALTIME:
            self.start_midi_input()
        else:
            if self.state.sound_paused:
                self.stop_playback()
                self.play_keyboard(start_time=0.0)
            else:
                self.play_keyboard()

    def toggle_keyboard_pause(self) -> None:
        if self.state.keyboard_playing:
            player = self.player
            position = self.state.position
            if player:
                current_position = player.current_position()
                if current_position is not None:
                    position = current_position
                self._next_playback_id()
                player.stop()
                player.wait_until_stopped(timeout=2.0)
            self.player = None
            self._cancel_rhythm_scoring_pending()
            self._clear_active_output_notes()
            self.state.current_mode = "keys_paused"
            self.state.position = max(0.0, min(self.state.duration, position))
            self.state.status = "paused"
            self._notify()
        elif self.state.keyboard_paused:
            position = self.state.position
            self.state.current_mode = None
            self.play_keyboard(
                start_time=position,
                countdown=False,
                reset_rhythm_score=False,
            )

    def toggle_sound_playback(self) -> None:
        if self.state.sound_playing or self.state.sound_paused:
            self.stop_playback()
        elif self._midi_sound_can_start():
            self.play_sound()

    def toggle_sound_pause(self) -> None:
        if self.state.sound_playing:
            self.pause_sound()
        elif self.state.sound_paused:
            self.resume_sound()
        elif self._midi_sound_can_start():
            self.play_sound()

    def pause_sound(self) -> None:
        if not self.state.sound_playing:
            return
        player = self.sound_player
        position = self.state.position
        if player:
            current_position = player.current_position()
            if current_position is not None:
                position = current_position
            self._next_playback_id()
            self._next_position_generation()
            player.stop()
            player.wait_until_stopped(timeout=2.0)
        self.sound_player = None
        self._cancel_rhythm_scoring_pending()
        self._clear_active_output_notes("sound")
        self.state.current_mode = "sound_paused"
        self.state.position = max(0.0, min(self.state.duration, position))
        self.state.status = "sound paused"
        self._notify()

    def resume_sound(self) -> None:
        if not self.state.sound_paused:
            return
        position = self.state.position
        self.state.current_mode = None
        self.play_sound(
            start_time=position,
            reset_rhythm_score=False,
        )

    def select_previous_midi(self) -> None:
        self._select_adjacent_midi(-1)

    def select_next_midi(self) -> None:
        self._select_adjacent_midi(1)

    def _select_adjacent_midi(self, offset: int) -> None:
        target = self.state.selected_midi_index + int(offset)
        if not 0 <= target < len(self.midi_files):
            return
        self.select_midi(target)

    def cycle_sound_playback_mode(self) -> None:
        current = normalize_sound_playback_mode(
            self.state.sound_playback_mode
        )
        current_index = SOUND_PLAYBACK_MODES.index(current)
        self.state.sound_playback_mode = SOUND_PLAYBACK_MODES[
            (current_index + 1) % len(SOUND_PLAYBACK_MODES)
        ]
        self.request_save()
        self._notify()

    def play_keyboard(
        self,
        *,
        start_time: float | None = None,
        countdown: bool = True,
        reset_rhythm_score: bool = True,
    ) -> None:
        if self.state.current_mode is not None or self.state.midi_input_running:
            return
        if not self.events:
            self._message("info", "no_midi_title", self.text("load_midi_first"))
            return
        if not self._has_enabled_events():
            self._message("info", "no_events_title", self.text("no_events_enabled"))
            return
        position = self._play_start_position() if start_time is None else start_time
        playback_id = self._next_playback_id()
        output = KeyboardOutput(dry_run=self.state.dry_run)
        self.player = MidiKeyboardPlayer(
            output=output,
            log=lambda message: self._queue_worker_message(("log", message)),
            on_state=lambda status, pid=playback_id: self._queue_worker_message(("key_state", pid, status)),
            on_position=lambda value, pid=playback_id: self._queue_position_message(pid, value),
            on_optimization_progress=lambda progress, pid=playback_id: self._queue_worker_message(
                ("optimization", pid, progress)
            ),
            on_output_note=lambda note, pressed, pid=playback_id: self._queue_worker_message(
                ("key_output_note", pid, note, pressed)
            ),
            enabled_channels=self.enabled_channels,
            enabled_sources=self.enabled_sources,
            auto_fit_note_range=self.state.auto_fit_note_range,
            transpose_semitones=self.state.transpose_semitones,
            octave_shift=self.state.octave_shift,
            humanize_timing=self.state.humanize_timing,
            chord_optimization=self.state.chord_optimization,
            chord_strum=self.state.chord_strum,
            auto_sustain=self.state.auto_sustain,
            repeat_prevention=self.state.repeat_prevention,
            playback_speed_percent=self.state.playback_speed_percent,
            key_bindings=self.current_key_bindings(),
            sustain_key=self.state.sustain_key,
            octave_down_key=self.state.octave_down_key,
            octave_up_key=self.state.octave_up_key,
        )
        try:
            if reset_rhythm_score:
                self._reset_rhythm_score()
            self._clear_active_output_notes()
            self.state.input_conversion_mode = INPUT_CONVERSION_MIDI_FILE
            self.state.current_mode = "keys"
            mode = self.text("dry_run_mode") if self.state.dry_run else self.text("real_keyboard_output")
            self._log(self.text("key_playback_started").format(mode=mode))
            self._notify()
            self.player.play_with_countdown_sound(
                self.events,
                countdown_seconds=self.state.countdown_seconds if countdown else 0,
                start_time=position,
                on_countdown_tick=self._play_countdown_tick if self._countdown_tick_enabled() else None,
            )
        except RuntimeError as exc:
            self.player = None
            self.state.current_mode = None
            self._notify()
            self._message("warning", "already_playing_title", str(exc))

    def play_sound(
        self,
        *,
        start_time: float | None = None,
        reset_rhythm_score: bool = True,
    ) -> None:
        if not self._midi_sound_can_start():
            return
        if self.summary is None:
            self._message("info", "no_midi_title", self.text("load_midi_first"))
            return
        if not self._has_enabled_events():
            self._message("info", "no_events_title", self.text("no_events_enabled"))
            return
        playback_id = self._next_playback_id()
        self.sound_player = MidiSoundPlayer(
            log=lambda message: self._queue_worker_message(("log", message)),
            on_state=lambda status, pid=playback_id: self._queue_worker_message(("sound_state", pid, status)),
            on_position=lambda value, pid=playback_id: self._queue_position_message(pid, value),
            on_optimization_progress=lambda progress, pid=playback_id: self._queue_worker_message(
                ("optimization", pid, progress)
            ),
            on_output_note=lambda note, pressed, pid=playback_id: self._queue_worker_message(
                ("sound_output_note", pid, note, pressed, time.monotonic())
            ),
            on_output_remap=lambda note, pressed, pid=playback_id: self._queue_worker_message(
                ("sound_output_remap", pid, note, pressed)
            ),
            enabled_channels=self.enabled_channels,
            enabled_sources=self.enabled_sources,
            volume=self.state.midi_sound_volume,
            sound_source=self.state.sound_source,
            on_audio_runtime_changed=lambda qt_frames, buffer_frames, reason: self._queue_worker_message(
                ("audio_runtime", qt_frames, buffer_frames, reason)
            ),
            audio_buffer_frames=self.state.audio_buffer_frames,
            minimum_stable_qt_frames=self.minimum_stable_qt_frames,
            qt_audio_environment=self.qt_audio_environment,
            on_qt_learning_changed=lambda frames, environment: self._queue_worker_message(
                ("qt_learning", frames, environment)
            ),
            auto_fit_note_range=self.state.auto_fit_note_range,
            transpose_semitones=self.state.transpose_semitones,
            octave_shift=self.state.octave_shift,
            humanize_timing=self.state.humanize_timing,
            chord_optimization=self.state.chord_optimization,
            chord_strum=self.state.chord_strum,
            auto_sustain=self.state.auto_sustain,
            repeat_prevention=self.state.repeat_prevention,
            playback_speed_percent=self.state.playback_speed_percent,
        )
        try:
            if reset_rhythm_score:
                self._reset_rhythm_score()
            self._clear_active_output_notes("sound")
            self.state.current_mode = "sound"
            self._notify()
            position = (
                self._play_start_position()
                if start_time is None
                else max(0.0, min(self.state.duration, start_time))
            )
            self.sound_player.play(self.events, start_time=position)
        except RuntimeError as exc:
            self.sound_player = None
            self.state.current_mode = None
            self._notify()
            self._message("warning", "already_playing_title", str(exc))

    def stop_playback(self) -> None:
        self._next_playback_id()
        self._next_position_generation()
        player = self.player
        sound_player = self.sound_player
        stopped_mode = self.state.current_mode
        if player:
            player.stop()
            player.wait_until_stopped(timeout=2.0)
        if sound_player:
            sound_player.stop()
            sound_player.wait_until_stopped(timeout=2.0)
        self.player = None
        self.sound_player = None
        self.state.current_mode = None
        self._cancel_rhythm_scoring_pending()
        if stopped_mode in {"keys", "keys_paused"}:
            self._clear_active_output_notes()
        elif stopped_mode in {"sound", "sound_paused"}:
            self._clear_active_output_notes("sound")
        self.seeking_keys = False
        self.state.position = 0.0
        if stopped_mode in {"sound", "sound_paused"}:
            self.state.status = "sound stopped"
            self._log(self.text("sound_playback_stopped"))
        elif stopped_mode in {"keys", "keys_paused"}:
            self.state.status = "stopped"
        self._notify()

    def toggle_midi_input(self) -> None:
        if self.state.midi_input_running:
            self.stop_midi_input()
        else:
            self.start_midi_input()

    def start_midi_input(self) -> None:
        if self.state.keyboard_playing or self.state.keyboard_paused or self.state.midi_input_running:
            return
        device_id = self._selected_midi_input_device_id()
        if device_id is None:
            self._message("info", "no_midi_title", self.text("no_midi_input_devices"))
            return
        input_id = self._next_midi_input_id()
        self._close_realtime_sound_output()
        output = KeyboardOutput(dry_run=self.state.dry_run)
        self.realtime_sound_output = RealtimeMidiSoundOutput(
            volume=self.state.midi_sound_volume,
            sound_source=self.state.sound_source,
            on_audio_runtime_changed=lambda qt_frames, buffer_frames, reason: self._queue_worker_message(
                ("audio_runtime", qt_frames, buffer_frames, reason)
            ),
            audio_buffer_frames=self.state.audio_buffer_frames,
            minimum_stable_qt_frames=self.minimum_stable_qt_frames,
            qt_audio_environment=self.qt_audio_environment,
            on_qt_learning_changed=lambda frames, environment: self._queue_worker_message(
                ("qt_learning", frames, environment)
            ),
            log=lambda message: self._queue_worker_message(("log", message)),
            transpose_semitones=self.state.transpose_semitones,
            octave_shift=self.state.octave_shift,
            auto_sustain=self.state.auto_sustain,
            repeat_prevention=self.state.repeat_prevention,
        )
        self.realtime_sound_output.set_enabled(self.state.dry_run)
        bridge = MidiInputKeyboardBridge(
            device_id=device_id,
            output=output,
            log=lambda message: self._queue_worker_message(("log", message)),
            on_state=lambda status: self._queue_worker_message(("midi_input_state", status)),
            on_midi_message=self.realtime_sound_output.process_message,
            on_output_note=lambda note, pressed, iid=input_id: self._queue_worker_message(
                ("midi_output_note", iid, note, pressed, time.monotonic())
            ),
            auto_fit_note_range=self.state.auto_fit_note_range,
            transpose_semitones=self.state.transpose_semitones,
            octave_shift=self.state.octave_shift,
            auto_sustain=self.state.auto_sustain,
            repeat_prevention=self.state.repeat_prevention,
            sustain_key=self.state.sustain_key,
            octave_down_key=self.state.octave_down_key,
            octave_up_key=self.state.octave_up_key,
            key_bindings=self.current_key_bindings(),
        )
        try:
            bridge.start()
        except Exception as exc:
            bridge.stop()
            self._next_midi_input_id()
            self._close_realtime_sound_output()
            self._message("warning", "load_failed_title", str(exc))
            return
        self.midi_input_bridge = bridge
        self.state.input_conversion_mode = INPUT_CONVERSION_REALTIME
        self.state.midi_input_running = True
        if self.state.sound_playing:
            self._reset_rhythm_score()
        self._clear_active_output_notes("midi")
        self.request_save()
        self._notify()

    def stop_midi_input(self) -> None:
        self._next_midi_input_id()
        bridge = self.midi_input_bridge
        self.midi_input_bridge = None
        if bridge:
            bridge.stop()
        self._close_realtime_sound_output()
        self.state.midi_input_running = False
        self._cancel_rhythm_scoring_pending()
        self._clear_active_output_notes("midi")
        self._notify()

    def refresh_midi_input_devices(self, *, notify: bool = True) -> None:
        previous = self.state.midi_input_device
        try:
            devices = list_midi_input_devices()
        except Exception as exc:
            devices = []
            self._log(f"MIDI input device scan failed: {exc}")
        self.midi_input_devices = devices
        names = [name for _device_id, name in devices]
        self.state.midi_input_devices = names
        self.state.midi_input_device = previous if previous in names else (names[0] if names else "")
        self.request_save()
        if notify:
            self._notify()

    def set_option(self, name: str, value: object) -> None:
        if name in {
            "dry_run",
            "countdown_sound",
            "game_countdown_sound",
            "auto_fit_note_range",
            "humanize_timing",
            "chord_optimization",
            "chord_strum",
            "auto_sustain",
            "repeat_prevention",
            "shortcut_locked",
            "always_on_top",
            "tray_resident",
            "hide_release_notes_on_startup",
        }:
            setattr(self.state, name, bool(value))
        elif name == "countdown_seconds":
            self.state.countdown_seconds = self._clamp_int(value, 0, 10, 3)
        elif name == "midi_sound_volume":
            self.state.midi_sound_volume = self._clamp_int(value, 0, 100, 80)
        elif name == "playback_speed_percent":
            self.state.playback_speed_percent = self._clamp_int(
                value, MIN_PLAYBACK_SPEED_PERCENT, MAX_PLAYBACK_SPEED_PERCENT, 100
            )
        elif name == "sound_playback_mode":
            self.state.sound_playback_mode = normalize_sound_playback_mode(value)
        elif name == "transpose_semitones":
            self.state.transpose_semitones = self._clamp_int(
                value, MIN_TRANSPOSE_SEMITONES, MAX_TRANSPOSE_SEMITONES, 0
            )
        elif name == "octave_shift":
            self.state.octave_shift = self._clamp_int(value, MIN_OCTAVE_SHIFT, MAX_OCTAVE_SHIFT, 0)
        elif name == "window_opacity":
            self.state.window_opacity = self._clamp_int(value, 30, 100, 100)
        elif name == "ui_scale_percent":
            self.state.ui_scale_percent = self._normalize_ui_scale(value)
        elif name == "language":
            self.state.language = normalize_language(value)
            if self.summary is None and self.state.current_mode is None:
                self.state.status = self.text("waiting")
        elif name == "color_theme":
            self.state.color_theme = normalize_color_theme(value)
        elif name == "sound_source":
            self.state.sound_source = normalize_sound_source(value)
        elif name == "midi_input_device":
            self.state.midi_input_device = str(value)
        elif name == "input_conversion_mode":
            self.state.input_conversion_mode = normalize_input_conversion_mode(value)
        elif name == "keyboard_play_shortcut":
            self.state.keyboard_play_shortcut = (
                str(value).strip() or DEFAULT_KEYBOARD_PLAY_SHORTCUT
            )
            self._bind_global_hotkeys()
        elif name == "keyboard_pause_shortcut":
            self.state.keyboard_pause_shortcut = (
                str(value).strip() or DEFAULT_KEYBOARD_PAUSE_SHORTCUT
            )
            self._bind_global_hotkeys()
        elif name == "keyboard_stop_shortcut":
            self.state.keyboard_stop_shortcut = (
                str(value).strip() or DEFAULT_KEYBOARD_STOP_SHORTCUT
            )
            self._bind_global_hotkeys()
        else:
            raise ValueError(f"Unsupported option: {name}")
        self._apply_live_option(name)
        self.request_save()
        self._notify()

    def set_section_visible(self, section: str, visible: bool) -> None:
        if section not in self.state.section_visibility:
            raise ValueError(f"Unknown section: {section}")
        next_visible = bool(visible)
        self.state.section_visibility[section] = next_visible
        if section == "piano_roll" and not next_visible:
            self._cancel_rhythm_scoring_pending()
        self.request_save()
        self._notify()

    def set_panel_order(self, panel_order: object) -> None:
        normalized = normalize_panel_order(panel_order)
        if normalized == self.state.panel_order:
            return
        self.state.panel_order = normalized
        self.request_save()
        self._notify()

    def set_window_geometry(self, width: int, height: int) -> None:
        self.state.window_width = max(1, int(width))
        self.state.window_height = max(1, int(height))
        self.request_save()

    def set_key_binding(self, note: int, key: str) -> None:
        updated = self.current_key_bindings()
        updated[int(note)] = str(key).strip().lower()
        self._apply_key_bindings(updated)

    def reset_key_bindings(self) -> None:
        self._apply_key_bindings(DEFAULT_KEY_BINDINGS)

    def current_special_key_bindings(self) -> dict[str, str]:
        return {
            "sustain": self.state.sustain_key,
            "octave_down": self.state.octave_down_key,
            "octave_up": self.state.octave_up_key,
        }

    def set_special_key_binding(self, name: str, key: str) -> None:
        defaults = {
            "sustain": SUSTAIN_KEY,
            "octave_down": OCTAVE_DOWN_KEY,
            "octave_up": OCTAVE_UP_KEY,
        }
        if name not in defaults:
            raise ValueError(f"Unsupported special binding: {name}")
        setattr(
            self.state,
            f"{name}_key",
            normalize_special_binding(key, defaults[name]),
        )
        self._apply_live_option("special_key_bindings")
        self.request_save()
        self._notify()

    def reset_special_key_bindings(self) -> None:
        for name, key in (
            ("sustain", SUSTAIN_KEY),
            ("octave_down", OCTAVE_DOWN_KEY),
            ("octave_up", OCTAVE_UP_KEY),
        ):
            setattr(self.state, f"{name}_key", key)
        self._apply_live_option("special_key_bindings")
        self.request_save()
        self._notify()

    def current_key_bindings(self) -> dict[int, str]:
        return normalized_key_bindings(self.key_bindings)

    def current_chord_optimization_plan(self) -> ChordOptimizationPlan | None:
        if self.state.sound_playing and self.sound_player:
            return self.sound_player.current_chord_optimization_plan()
        if (self.state.keyboard_playing or self.state.keyboard_paused) and self.player:
            return self.player.current_chord_optimization_plan()
        return None

    def piano_roll_playback_running(self) -> bool:
        if self.state.sound_playing and self.sound_player:
            return self.sound_player.current_position() is not None
        if self.state.keyboard_playing and self.player:
            return self.player.current_position() is not None
        return False

    def toggle_track_channel(self, track: int, channel: int) -> None:
        source = (track, channel)
        with self._source_lock:
            enabled = set(self.enabled_sources_snapshot)
            if source in enabled:
                enabled.remove(source)
            else:
                enabled.add(source)
            self.enabled_sources_snapshot = frozenset(enabled)
            self.enabled_channels_snapshot = frozenset(item[1] for item in enabled)
        self.state.track_channels = [
            replace(item, enabled=(item.track, item.channel) in self.enabled_sources_snapshot)
            for item in self.state.track_channels
        ]
        self._apply_track_channel_change()
        self._notify()

    def toggle_track(self, track: int) -> None:
        track_sources = {
            (item.track, item.channel)
            for item in self.state.track_channels
            if item.track == track
        }
        if not track_sources:
            return
        with self._source_lock:
            enabled = set(self.enabled_sources_snapshot)
            if track_sources.issubset(enabled):
                enabled.difference_update(track_sources)
            else:
                enabled.update(track_sources)
            self.enabled_sources_snapshot = frozenset(enabled)
            self.enabled_channels_snapshot = frozenset(item[1] for item in enabled)
        self.state.track_channels = [
            replace(item, enabled=(item.track, item.channel) in self.enabled_sources_snapshot)
            for item in self.state.track_channels
        ]
        self._apply_track_channel_change()
        self._notify()

    def _apply_track_channel_change(self) -> None:
        if self.state.keyboard_playing and self.player and self.player.is_playing:
            self.player.request_chord_optimization_refresh()
            self.player.request_release_all()
        elif self.state.sound_playing and self.sound_player and self.sound_player.is_playing:
            self.sound_player.request_chord_optimization_refresh()
            self.sound_player.release_all()

    def enabled_channels(self) -> set[int]:
        with self._source_lock:
            return set(self.enabled_channels_snapshot)

    def enabled_sources(self) -> set[tuple[int, int]]:
        with self._source_lock:
            return set(self.enabled_sources_snapshot)

    def seek(self, position: float) -> None:
        value = max(0.0, min(self.state.duration, float(position)))
        self._next_position_generation()
        self.state.position = value
        if self.state.sound_playing and self.sound_player and self.sound_player.is_playing:
            self._reset_rhythm_score()
            self.sound_player.seek(value)
        elif self.state.keyboard_playing and self.player and self.player.is_playing:
            old_player = self.player
            self.seeking_keys = True
            old_player.stop()
            old_player.wait_until_stopped(timeout=2.0)
            if old_player.is_playing:
                self.seeking_keys = False
                self._log("Keyboard playback could not be stopped in time; seek was cancelled")
            else:
                self.player = None
                self.state.current_mode = None
                self.play_keyboard(start_time=value, countdown=False)
                self.seeking_keys = False
        self._notify()

    def process_pending_events(self) -> None:
        try:
            changed = self._drain_metadata_queue()
            released_output_notes: set[int] = set()
            completed_sound_mode: str | None = None
            while True:
                try:
                    message = self.worker_queue.get_nowait()
                except queue.Empty:
                    break
                kind = str(message[0])
                if kind == "log":
                    self._log(str(message[1]))
                    continue
                if kind == "audio_runtime":
                    try:
                        qt_frames = max(1, int(message[1]))
                    except (TypeError, ValueError):
                        qt_frames = self.state.audio_qt_frames
                    buffer_frames = normalize_audio_buffer_frames(message[2])
                    buffer_changed = (
                        buffer_frames != self.state.audio_buffer_frames
                    )
                    if (
                        qt_frames != self.state.audio_qt_frames
                        or buffer_changed
                    ):
                        self.state.audio_qt_frames = qt_frames
                        self.state.audio_buffer_frames = buffer_frames
                        reason = str(message[3])
                        if reason:
                            self._log(reason)
                        changed = True
                        if buffer_changed:
                            self.request_save()
                    continue
                if kind == "qt_learning":
                    minimum_stable_qt_frames = (
                        normalize_qt_audio_frames(message[1])
                        if message[1] is not None
                        else None
                    )
                    audio_environment = str(message[2])
                    if (
                        minimum_stable_qt_frames
                        != self.minimum_stable_qt_frames
                        or audio_environment != self.qt_audio_environment
                    ):
                        self.minimum_stable_qt_frames = (
                            minimum_stable_qt_frames
                        )
                        self.qt_audio_environment = audio_environment
                        self.request_save()
                    continue
                if kind == "hotkey":
                    if message[1] == "play":
                        self.start_keyboard_conversion_from_shortcut()
                    elif message[1] == "pause_resume":
                        self.toggle_keyboard_pause()
                    elif message[1] == "stop":
                        self.stop_keyboard_conversion_from_shortcut()
                    continue
                if kind in {
                    "key_state",
                    "sound_state",
                    "position",
                    "optimization",
                    "key_output_note",
                    "sound_output_note",
                    "sound_output_remap",
                }:
                    if int(message[1]) != self.playback_id:
                        continue
                if kind == "midi_output_note" and int(message[1]) != self.midi_input_id:
                    continue
                if kind == "key_state":
                    status = str(message[2])
                    self.state.status = status
                    if status == "stopped" and not self.seeking_keys and self.state.keyboard_playing:
                        self.state.current_mode = None
                        self._cancel_rhythm_scoring_pending()
                        self._clear_active_output_notes()
                    changed = True
                elif kind == "sound_state":
                    status = str(message[2])
                    self.state.status = status
                    if status in {"sound ended", "sound stopped"} and self.state.sound_playing:
                        if status == "sound ended":
                            self.state.position = self.state.duration
                            completed_sound_mode = normalize_sound_playback_mode(
                                self.state.sound_playback_mode
                            )
                        self.state.current_mode = None
                        self._cancel_rhythm_scoring_pending()
                        self._clear_active_output_notes("sound")
                    changed = True
                elif kind == "midi_input_state":
                    status = str(message[1])
                    self.state.status = status
                    if status == "midi input failed":
                        self.stop_midi_input()
                    changed = True
                elif kind == "position":
                    if int(message[2]) != self.position_generation:
                        continue
                    self.state.position = max(
                        0.0,
                        min(self.state.duration, float(message[3])),
                    )
                    changed = True
                elif kind == "optimization":
                    progress = message[2]
                    if progress is None:
                        self.state.status = "playing" if self.state.keyboard_playing else "sound playing"
                    else:
                        percent = self._clamp_int(progress, 0, 100, 0)
                        self.state.status = self.text("optimization_progress").format(percent=percent)
                    changed = True
                elif kind in {
                    "key_output_note",
                    "sound_output_note",
                    "sound_output_remap",
                    "midi_output_note",
                }:
                    source_kind = {
                        "key_output_note": "key",
                        "sound_output_note": "sound",
                        "sound_output_remap": "sound",
                        "midi_output_note": "midi",
                    }[kind]
                    note = int(message[2])
                    pressed = bool(message[3])
                    event_at = (
                        float(message[4])
                        if len(message) >= 5
                        else time.monotonic()
                    )
                    rhythm_hit: RhythmHit | None = None
                    released = not pressed
                    if self._rhythm_scoring_is_enabled():
                        if (
                            kind == "key_output_note"
                            and self.state.keyboard_playing
                        ):
                            rhythm_hit = self._rhythm_scorer.record_automatic_perfect(
                                note,
                                released=released,
                                timestamp=event_at,
                            )
                        elif (
                            kind == "sound_output_note"
                            and self.state.sound_playing
                        ):
                            if self.state.midi_input_running:
                                rhythm_hit = self._rhythm_scorer.record_expected(
                                    note,
                                    event_at,
                                    released=released,
                                )
                            else:
                                rhythm_hit = (
                                    self._rhythm_scorer.record_automatic_perfect(
                                        note,
                                        released=released,
                                        timestamp=event_at,
                                    )
                                )
                        elif (
                            source_kind == "midi"
                            and self._rhythm_scoring_is_active()
                        ):
                            rhythm_hit = self._rhythm_scorer.record_input(
                                note,
                                event_at,
                                released=released,
                            )
                    if rhythm_hit is not None:
                        changed = (
                            self._record_rhythm_hit_event(rhythm_hit)
                            or changed
                        )
                    if (
                        rhythm_hit is not None
                        or self._rhythm_scoring_is_active()
                    ):
                        changed = (
                            self._sync_rhythm_score_state()
                            or changed
                        )
                    changed = self._set_output_note_state(
                        (source_kind, int(message[1])),
                        note,
                        pressed,
                        retrigger=pressed and note in released_output_notes,
                    ) or changed
                    if pressed:
                        released_output_notes.discard(note)
                    else:
                        released_output_notes.add(note)
            if completed_sound_mode is not None:
                changed = (
                    self._continue_sound_after_end(completed_sound_mode)
                    or changed
                )
            if self._rhythm_scoring_is_active():
                self._rhythm_scorer.expire(time.monotonic())
                changed = self._sync_rhythm_score_state() or changed
            if self._rhythm_scoring_is_enabled():
                changed = self._record_pending_rhythm_miss_events() or changed
            self._schedule_rhythm_score_update()
            changed = self._expire_output_note_releases() or changed
            if changed:
                self._notify()
        finally:
            self._complete_event_dispatch()

    def _continue_sound_after_end(self, mode: str) -> bool:
        previous_player = self.sound_player
        if previous_player:
            previous_player.wait_until_stopped(timeout=0.5)
        self.sound_player = None
        if mode == SOUND_PLAYBACK_MODE_OFF:
            return False
        if mode == SOUND_PLAYBACK_MODE_REPEAT_ONE:
            self.state.position = 0.0
            self.play_sound(start_time=0.0)
            return self.state.sound_playing
        if mode != SOUND_PLAYBACK_MODE_CONTINUOUS or not self.midi_files:
            return False
        current_index = self.state.selected_midi_index
        next_index = (
            current_index + 1
            if 0 <= current_index < len(self.midi_files) - 1
            else 0
        )
        self.select_midi(next_index)
        if self.state.selected_midi_index != next_index:
            return False
        self.play_sound(start_time=0.0)
        return self.state.sound_playing

    def request_save(self) -> None:
        self._settings_dirty = True

    def record_update_check(self, checked_at: int) -> bool:
        self.last_update_check_at = max(0, int(checked_at))
        return self.save_settings_now()

    def save_settings_now(self) -> bool:
        try:
            save_settings(self.current_settings())
        except Exception as exc:
            message = f"Settings could not be saved: {exc}"
            if message != self.settings_save_error:
                self._log(message)
            self.settings_save_error = message
            return False
        else:
            self.settings_save_error = ""
            self._settings_dirty = False
            return True

    def _save_settings_on_shutdown(self) -> None:
        if self._settings_dirty:
            self.save_settings_now()

    def current_settings(self) -> AppSettings:
        return AppSettings(
            countdown_seconds=self.state.countdown_seconds,
            midi_sound_volume=self.state.midi_sound_volume,
            sound_source=self.state.sound_source,
            dry_run=self.state.dry_run,
            countdown_sound=self.state.countdown_sound,
            game_countdown_sound=self.state.game_countdown_sound,
            auto_fit_note_range=self.state.auto_fit_note_range,
            transpose_semitones=self.state.transpose_semitones,
            octave_shift=self.state.octave_shift,
            humanize_timing=self.state.humanize_timing,
            chord_optimization=self.state.chord_optimization,
            chord_strum=self.state.chord_strum,
            auto_sustain=self.state.auto_sustain,
            repeat_prevention=self.state.repeat_prevention,
            playback_speed_percent=self.state.playback_speed_percent,
            sound_playback_mode=self.state.sound_playback_mode,
            language=self.state.language,
            color_theme=self.state.color_theme,
            always_on_top=self.state.always_on_top,
            tray_resident=self.state.tray_resident,
            hide_release_notes_on_startup=(
                self.state.hide_release_notes_on_startup
            ),
            window_opacity=self.state.window_opacity,
            ui_scale_percent=self.state.ui_scale_percent,
            window_width=self.state.window_width,
            window_height=self.state.window_height,
            last_midi_folder=self.last_midi_folder,
            keyboard_play_shortcut=self.state.keyboard_play_shortcut,
            keyboard_pause_shortcut=self.state.keyboard_pause_shortcut,
            keyboard_stop_shortcut=self.state.keyboard_stop_shortcut,
            shortcut_locked=self.state.shortcut_locked,
            midi_input_device=self.state.midi_input_device,
            input_conversion_mode=self.state.input_conversion_mode,
            key_bindings=self.current_key_bindings(),
            sustain_key=self.state.sustain_key,
            octave_down_key=self.state.octave_down_key,
            octave_up_key=self.state.octave_up_key,
            panel_order=normalize_panel_order(self.state.panel_order),
            section_visibility=normalize_section_visibility(
                self.state.section_visibility
            ),
            last_update_check_at=self.last_update_check_at,
            automatic_audio_buffer_frames=self.state.audio_buffer_frames,
            minimum_stable_qt_frames=self.minimum_stable_qt_frames,
            qt_audio_environment=self.qt_audio_environment,
        )

    def shutdown(self) -> None:
        if self.exiting:
            return
        self.exiting = True
        self.set_event_notifier(None)
        self.metadata_cancel.set()
        self._unbind_global_hotkeys()
        self.stop_midi_input()
        self.stop_playback()
        self._save_settings_on_shutdown()

    def _apply_live_option(self, name: str) -> None:
        if name == "dry_run":
            if self.player:
                self.player.set_dry_run(self.state.dry_run)
            if self.midi_input_bridge:
                self.midi_input_bridge.set_dry_run(self.state.dry_run)
            if self.realtime_sound_output:
                self.realtime_sound_output.set_enabled(self.state.dry_run)
        elif name == "midi_sound_volume":
            if self.sound_player:
                self.sound_player.set_volume(self.state.midi_sound_volume)
            if self.realtime_sound_output:
                self.realtime_sound_output.set_volume(self.state.midi_sound_volume)
        elif name == "sound_source":
            for target in (self.sound_player, self.realtime_sound_output):
                if target:
                    target.set_sound_source(self.state.sound_source)
        elif name == "playback_speed_percent":
            if self.player:
                self.player.set_playback_speed(self.state.playback_speed_percent)
            if self.sound_player:
                self.sound_player.set_playback_speed(self.state.playback_speed_percent)
        elif name == "humanize_timing":
            if self.player:
                self.player.set_humanize_timing(self.state.humanize_timing)
            if self.sound_player:
                self.sound_player.set_humanize_timing(self.state.humanize_timing)
        elif name == "chord_optimization":
            if self.player:
                self.player.set_chord_optimization(self.state.chord_optimization)
            if self.sound_player:
                self.sound_player.set_chord_optimization(self.state.chord_optimization)
        elif name == "chord_strum":
            if self.player:
                self.player.set_chord_strum(self.state.chord_strum)
            if self.sound_player:
                self.sound_player.set_chord_strum(self.state.chord_strum)
        elif name == "auto_sustain":
            for target in (
                self.player,
                self.sound_player,
                self.midi_input_bridge,
                self.realtime_sound_output,
            ):
                if target:
                    target.set_auto_sustain(self.state.auto_sustain)
        elif name == "special_key_bindings":
            for target in (self.player, self.midi_input_bridge):
                if target:
                    target.set_special_key_bindings(
                        self.state.sustain_key,
                        self.state.octave_down_key,
                        self.state.octave_up_key,
                    )
        elif name == "repeat_prevention":
            for target in (self.player, self.sound_player, self.midi_input_bridge, self.realtime_sound_output):
                if target:
                    target.set_repeat_prevention(self.state.repeat_prevention)
        elif name == "auto_fit_note_range":
            for target in (self.player, self.sound_player, self.midi_input_bridge):
                if target:
                    target.set_auto_fit_note_range(self.state.auto_fit_note_range)
        elif name in {"transpose_semitones", "octave_shift"}:
            for target in (self.player, self.sound_player, self.midi_input_bridge, self.realtime_sound_output):
                if target:
                    target.set_note_shift(self.state.transpose_semitones, self.state.octave_shift)

    def _apply_key_bindings(self, bindings: dict[int, str]) -> None:
        self.key_bindings = normalized_key_bindings(bindings)
        if self.player:
            self.player.set_key_bindings(self.key_bindings)
        if self.midi_input_bridge:
            self.midi_input_bridge.set_key_bindings(self.key_bindings)
        self.request_save()
        self._notify()

    def _set_track_channels(self, summary: MidiSummary) -> None:
        sources = [
            (track.index, channel)
            for track in summary.tracks
            for channel in track.channels
        ]
        if not sources:
            sources = [(0, channel) for channel in summary.channels]
        self._set_enabled_sources(sources)
        self.state.track_channels = [
            TrackChannelItem(track=track, channel=channel, enabled=True)
            for track, channel in sources
        ]

    def _set_enabled_sources(self, sources: object) -> None:
        enabled = frozenset((int(track), int(channel)) for track, channel in sources)
        with self._source_lock:
            self.enabled_sources_snapshot = enabled
            self.enabled_channels_snapshot = frozenset(channel for _track, channel in enabled)

    def _has_enabled_events(self) -> bool:
        sources = self.enabled_sources()
        channels = self.enabled_channels()
        return any(
            event.channel is None
            or (event.track is not None and (event.track, event.channel) in sources)
            or (event.track is None and event.channel in channels)
            for event in self.events
        )

    def _play_start_position(self) -> float:
        if self.state.duration > 0 and self.state.position >= self.state.duration - 1.0:
            self.state.position = 0.0
        return self.state.position

    def _sound_playback_is_active(self) -> bool:
        return bool(self.state.sound_playing and self.sound_player and self.sound_player.is_playing)

    def _playback_mode_is_active(self) -> bool:
        return self.state.current_mode in {
            "keys",
            "keys_paused",
            "sound",
            "sound_paused",
        }

    def _midi_sound_can_start(self) -> bool:
        return self.state.current_mode in (None, "midi_input")

    def _selected_midi_input_device_id(self) -> int | None:
        for device_id, name in getattr(self, "midi_input_devices", []):
            if name == self.state.midi_input_device:
                return device_id
        return None

    def _close_realtime_sound_output(self) -> None:
        output = self.realtime_sound_output
        self.realtime_sound_output = None
        if output:
            output.close()

    def _countdown_tick_enabled(self) -> bool:
        return self.state.countdown_sound or self.state.game_countdown_sound

    def _play_countdown_tick(self, remaining: int) -> None:
        self._queue_worker_message(("log", f"Countdown: {remaining}"))
        if self.state.countdown_sound:
            try:
                winsound.Beep(1200 if remaining == 1 else 880, 90)
            except RuntimeError as exc:
                self._queue_worker_message(("log", f"Countdown sound failed: {exc}"))
        if self.state.game_countdown_sound:
            key = self.current_key_bindings()[48]
            output = KeyboardOutput(dry_run=self.state.dry_run)
            threading.Thread(
                target=self._tap_countdown_game_key,
                args=(output, key, self.playback_id),
                daemon=True,
            ).start()
            self._queue_worker_message(("log", f"Countdown game key: {key}"))

    def _tap_countdown_game_key(self, output: KeyboardOutput, key: str, playback_id: int) -> None:
        output.press(key)
        self._queue_worker_message(("key_output_note", playback_id, 48, True))
        try:
            time.sleep(GAME_COUNTDOWN_KEY_HOLD_SECONDS)
        finally:
            output.release(key)
            self._queue_worker_message(("key_output_note", playback_id, 48, False))

    def _start_metadata_scan(self, paths: list[Path]) -> None:
        self.metadata_cancel.set()
        self.metadata_scan_id += 1
        scan_id = self.metadata_scan_id
        cancel = threading.Event()
        self.metadata_cancel = cancel

        def scan() -> None:
            for path in paths:
                if cancel.is_set():
                    return
                try:
                    _events, summary = parse_midi(path)
                    note_range = self.format_note_range(summary.note_range)
                    duration = self.format_time(summary.duration)
                except Exception:
                    note_range, duration = "--", "--:--"
                self._queue_metadata_result((scan_id, path, note_range, duration))

        threading.Thread(target=scan, daemon=True).start()

    def _drain_metadata_queue(self) -> bool:
        changed = False
        while True:
            try:
                scan_id, path, note_range, duration = self.metadata_queue.get_nowait()
            except queue.Empty:
                break
            if scan_id != self.metadata_scan_id:
                continue
            for index, row in enumerate(self.state.midi_rows):
                if row.path == path:
                    rows = list(self.state.midi_rows)
                    rows[index] = replace(
                        row,
                        note_range=note_range,
                        duration=duration,
                    )
                    self.state.midi_rows = rows
                    changed = True
                    break
        return changed

    def _update_row_metadata(self, path: Path, summary: MidiSummary | None) -> None:
        if summary is None:
            return
        for index, row in enumerate(self.state.midi_rows):
            if row.path == path:
                note_range = self.format_note_range(summary.note_range)
                duration = self.format_time(summary.duration)
                if row.note_range == note_range and row.duration == duration:
                    return
                rows = list(self.state.midi_rows)
                rows[index] = replace(
                    row,
                    note_range=note_range,
                    duration=duration,
                )
                self.state.midi_rows = rows
                return

    def _find_midi_index(self, path: Path) -> int:
        for index, candidate in enumerate(self.midi_files):
            if candidate == path or candidate.name == path.name:
                return index
        return -1

    def _bind_global_hotkeys(self) -> None:
        self._unbind_global_hotkeys()
        specs = []
        errors: list[str] = []
        play_spec = shortcut_to_hotkey_spec(self.state.keyboard_play_shortcut, "play")
        pause_spec = shortcut_to_hotkey_spec(
            self.state.keyboard_pause_shortcut,
            "pause_resume",
        )
        stop_spec = shortcut_to_hotkey_spec(self.state.keyboard_stop_shortcut, "stop")
        used_shortcuts: dict[tuple[int, int], str] = {}
        if play_spec:
            specs.append(play_spec)
            used_shortcuts[(play_spec.modifiers, play_spec.vk)] = "start"
        else:
            errors.append(f"Unsupported start shortcut: {self.state.keyboard_play_shortcut}")
        if pause_spec is None:
            errors.append(f"Unsupported pause/resume shortcut: {self.state.keyboard_pause_shortcut}")
        elif (pause_spec.modifiers, pause_spec.vk) in used_shortcuts:
            errors.append("Start and pause/resume shortcuts must be different")
        else:
            specs.append(pause_spec)
            used_shortcuts[(pause_spec.modifiers, pause_spec.vk)] = "pause/resume"
        if stop_spec is None:
            errors.append(f"Unsupported end shortcut: {self.state.keyboard_stop_shortcut}")
        elif (stop_spec.modifiers, stop_spec.vk) in used_shortcuts:
            errors.append("Start, pause/resume, and end shortcuts must be different")
        else:
            specs.append(stop_spec)
        manager = GlobalHotkeyManager(
            specs,
            lambda action: self._queue_worker_message(("hotkey", action)),
        )
        manager.start()
        self.global_hotkeys = manager
        failures = errors + [
            f"Global shortcut registration failed: {action}"
            for action in manager.failed_actions
        ]
        signature = tuple(failures)
        if signature != self.hotkey_failure_signature:
            for message in failures:
                self._log(message)
            self.hotkey_failure_signature = signature

    def _unbind_global_hotkeys(self) -> None:
        if self.global_hotkeys:
            self.global_hotkeys.stop()
            self.global_hotkeys = None

    def ensure_hotkeys(self) -> None:
        if self.global_hotkeys is None or not self.global_hotkeys.is_healthy:
            self._bind_global_hotkeys()

    def _next_playback_id(self) -> int:
        self.playback_id += 1
        return self.playback_id

    def _next_position_generation(self) -> int:
        self.position_generation += 1
        return self.position_generation

    def _queue_position_message(self, playback_id: int, position: float) -> None:
        self._queue_worker_message(
            (
                "position",
                playback_id,
                self.position_generation,
                position,
            )
        )

    def _next_midi_input_id(self) -> int:
        self.midi_input_id += 1
        return self.midi_input_id

    def _rhythm_scoring_is_enabled(self) -> bool:
        return bool(self.state.section_visibility.get("piano_roll", True))

    def _rhythm_scoring_is_active(self) -> bool:
        return (
            self._rhythm_scoring_is_enabled()
            and self.state.sound_playing
            and self.state.midi_input_running
        )

    def _reset_rhythm_score(self) -> bool:
        changed = self._rhythm_scorer.reset()
        self.view.schedule_rhythm_score_update(None)
        if self.state.rhythm_hit_events:
            self.state.rhythm_hit_events = ()
            changed = True
        return self._sync_rhythm_score_state() or changed

    def _cancel_rhythm_scoring_pending(self) -> None:
        self._rhythm_scorer.cancel_pending()
        self.view.schedule_rhythm_score_update(None)

    def _record_rhythm_hit_event(self, hit: RhythmHit) -> bool:
        return self._record_rhythm_judgment_event(
            hit.note,
            hit.judgment,
            released=hit.released,
        )

    def _record_rhythm_judgment_event(
        self,
        note: int,
        judgment: str,
        *,
        released: bool = False,
    ) -> bool:
        self._rhythm_hit_serial += 1
        event = (
            self._rhythm_hit_serial,
            int(note),
            str(judgment).upper(),
            bool(released),
        )
        self.state.rhythm_hit_events = (
            *self.state.rhythm_hit_events,
            event,
        )[-RHYTHM_HIT_EVENT_HISTORY_LIMIT:]
        return True

    def _record_pending_rhythm_miss_events(self) -> bool:
        missed_events = self._rhythm_scorer.take_missed_events()
        for note, released in missed_events:
            self._record_rhythm_judgment_event(
                note,
                "MISS",
                released=released,
            )
        return bool(missed_events)

    def _sync_rhythm_score_state(self) -> bool:
        next_score = self._rhythm_scorer.score
        next_combo = self._rhythm_scorer.combo
        next_judgment = self._rhythm_scorer.judgment
        next_multiplier_tenths = self._rhythm_scorer.multiplier_tenths
        if (
            self.state.rhythm_score == next_score
            and self.state.rhythm_combo == next_combo
            and self.state.rhythm_judgment == next_judgment
            and self.state.rhythm_multiplier_tenths == next_multiplier_tenths
        ):
            return False
        self.state.rhythm_score = next_score
        self.state.rhythm_combo = next_combo
        self.state.rhythm_judgment = next_judgment
        self.state.rhythm_multiplier_tenths = next_multiplier_tenths
        return True

    def _set_output_note_state(
        self,
        source: tuple[str, int],
        note: int,
        pressed: bool,
        *,
        retrigger: bool = False,
    ) -> bool:
        if not PIANO_NOTE_MIN <= note <= PIANO_NOTE_MAX:
            return False
        now = time.monotonic()
        active = set(self.state.active_output_notes)
        source_notes = self._active_output_notes_by_source.setdefault(source, set())
        realtime_changed = False
        realtime_was_active = note in self.state.realtime_output_notes
        if source[0] == "midi" and pressed:
            self.state.realtime_note_trigger_serial += 1
            trigger_events = dict(self.state.realtime_note_trigger_events)
            trigger_events[note] = self.state.realtime_note_trigger_serial
            self.state.realtime_note_trigger_events = tuple(
                sorted(trigger_events.items())
            )
            realtime_changed = True
        if pressed:
            source_notes.add(note)
            realtime_changed = self._sync_realtime_output_notes() or realtime_changed
            if source[0] == "midi":
                realtime_changed = self._set_realtime_visible_note_state(
                    note,
                    True,
                    now,
                    retrigger=realtime_was_active or retrigger,
                ) or realtime_changed
            self._output_note_release_due.pop(note, None)
            self._output_note_visible_until[note] = now + OUTPUT_NOTE_MIN_VISIBLE_SECONDS
            was_active = note in active
            active.add(note)
            if was_active or retrigger:
                self.state.output_note_retrigger_serial += 1
                retrigger_events = dict(self.state.output_note_retrigger_events)
                retrigger_events[note] = self.state.output_note_retrigger_serial
                self.state.output_note_retrigger_events = tuple(
                    sorted(retrigger_events.items())
                )
        else:
            source_notes.discard(note)
            if not source_notes:
                self._active_output_notes_by_source.pop(source, None)
            realtime_changed = self._sync_realtime_output_notes() or realtime_changed
            if source[0] == "midi":
                realtime_changed = self._set_realtime_visible_note_state(
                    note,
                    False,
                    now,
                ) or realtime_changed
            if any(note in notes for notes in self._active_output_notes_by_source.values()):
                return realtime_changed
            if note not in active:
                self._output_note_visible_until.pop(note, None)
                self._output_note_release_due.pop(note, None)
                return realtime_changed
            visible_until = self._output_note_visible_until.get(note, now)
            if now < visible_until:
                self._output_note_release_due[note] = visible_until
                self._schedule_output_note_release()
                return realtime_changed
            active.discard(note)
            self._output_note_visible_until.pop(note, None)
            self._output_note_release_due.pop(note, None)
        self.state.active_output_notes = frozenset(active)
        return True

    def _set_realtime_visible_note_state(
        self,
        note: int,
        pressed: bool,
        now: float,
        *,
        retrigger: bool = False,
    ) -> bool:
        visible = set(self.state.realtime_visible_output_notes)
        changed = False
        if pressed:
            was_visible = note in visible
            visible.add(note)
            self._realtime_note_release_due.pop(note, None)
            self._realtime_note_visible_until[note] = (
                now + OUTPUT_NOTE_MIN_VISIBLE_SECONDS
            )
            if was_visible or retrigger:
                self.state.realtime_output_retrigger_serial += 1
                events = dict(self.state.realtime_output_retrigger_events)
                events[note] = self.state.realtime_output_retrigger_serial
                self.state.realtime_output_retrigger_events = tuple(
                    sorted(events.items())
                )
                changed = True
        elif note in self.state.realtime_output_notes:
            return False
        elif note not in visible:
            self._realtime_note_visible_until.pop(note, None)
            self._realtime_note_release_due.pop(note, None)
            return False
        else:
            visible_until = self._realtime_note_visible_until.get(note, now)
            if now < visible_until:
                self._realtime_note_release_due[note] = visible_until
                self._schedule_output_note_release()
                return False
            visible.discard(note)
            self._realtime_note_visible_until.pop(note, None)
            self._realtime_note_release_due.pop(note, None)
        next_notes = frozenset(visible)
        if self.state.realtime_visible_output_notes != next_notes:
            self.state.realtime_visible_output_notes = next_notes
            changed = True
        return changed

    def _sync_realtime_output_notes(self) -> bool:
        realtime_sources = [
            notes
            for source, notes in self._active_output_notes_by_source.items()
            if source[0] == "midi"
        ]
        next_notes = frozenset().union(*realtime_sources) if realtime_sources else frozenset()
        if self.state.realtime_output_notes == next_notes:
            return False
        self.state.realtime_output_notes = next_notes
        return True

    def _expire_output_note_releases(self) -> bool:
        if not self._output_note_release_due and not self._realtime_note_release_due:
            return False
        now = time.monotonic()
        expired_output = [
            note
            for note, release_at in self._output_note_release_due.items()
            if now >= release_at
        ]
        expired_realtime = [
            note
            for note, release_at in self._realtime_note_release_due.items()
            if now >= release_at
        ]
        if not expired_output and not expired_realtime:
            self._schedule_output_note_release()
            return False
        changed = False
        active = set(self.state.active_output_notes)
        for note in expired_output:
            active.discard(note)
            self._output_note_release_due.pop(note, None)
            self._output_note_visible_until.pop(note, None)
        next_active = frozenset(active)
        if self.state.active_output_notes != next_active:
            self.state.active_output_notes = next_active
            changed = True
        realtime_visible = set(self.state.realtime_visible_output_notes)
        for note in expired_realtime:
            realtime_visible.discard(note)
            self._realtime_note_release_due.pop(note, None)
            self._realtime_note_visible_until.pop(note, None)
        next_realtime_visible = frozenset(realtime_visible)
        if self.state.realtime_visible_output_notes != next_realtime_visible:
            self.state.realtime_visible_output_notes = next_realtime_visible
            changed = True
        self._schedule_output_note_release()
        return changed

    def process_output_note_releases(self) -> None:
        if self._expire_output_note_releases():
            self._notify()

    def process_rhythm_score_update(self) -> None:
        if not self._rhythm_scoring_is_enabled():
            self.view.schedule_rhythm_score_update(None)
            return
        changed = self._rhythm_scorer.expire(time.monotonic())
        changed = self._sync_rhythm_score_state() or changed
        changed = self._record_pending_rhythm_miss_events() or changed
        self._schedule_rhythm_score_update()
        if changed:
            self._notify()

    def _schedule_rhythm_score_update(self) -> None:
        if not self._rhythm_scoring_is_enabled():
            self.view.schedule_rhythm_score_update(None)
            return
        delay_ms = self._rhythm_scorer.next_update_delay_ms(time.monotonic())
        self.view.schedule_rhythm_score_update(delay_ms)

    def _schedule_output_note_release(self) -> None:
        release_times = (
            *self._output_note_release_due.values(),
            *self._realtime_note_release_due.values(),
        )
        if not release_times:
            return
        remaining = min(release_times) - time.monotonic()
        delay_ms = max(1, int(remaining * 1000 + 0.999))
        self.view.schedule_output_note_release(delay_ms)

    def _clear_active_output_notes(self, source_kind: str | None = None) -> bool:
        had_retrigger = bool(self.state.output_note_retrigger_events)
        self.state.output_note_retrigger_events = ()
        had_realtime_events = bool(self.state.realtime_note_trigger_events)
        had_realtime_retrigger = (
            bool(self.state.realtime_output_retrigger_events)
            if source_kind is None or source_kind == "midi"
            else False
        )
        if source_kind is None or source_kind == "midi":
            self.state.realtime_note_trigger_events = ()
            self.state.realtime_output_retrigger_events = ()
        if source_kind is None:
            self._active_output_notes_by_source.clear()
            remaining: set[int] = set()
        else:
            for source in [
                item for item in self._active_output_notes_by_source if item[0] == source_kind
            ]:
                self._active_output_notes_by_source.pop(source, None)
            remaining = (
                set().union(*self._active_output_notes_by_source.values())
                if self._active_output_notes_by_source
                else set()
            )
        realtime_changed = self._sync_realtime_output_notes()
        if source_kind is None or source_kind == "midi":
            realtime_changed = (
                bool(self.state.realtime_visible_output_notes)
                or realtime_changed
            )
            self.state.realtime_visible_output_notes = frozenset()
            self._realtime_note_visible_until.clear()
            self._realtime_note_release_due.clear()
        self._output_note_visible_until = {
            note: visible_until
            for note, visible_until in self._output_note_visible_until.items()
            if note in remaining
        }
        self._output_note_release_due = {
            note: release_at
            for note, release_at in self._output_note_release_due.items()
            if note in remaining
        }
        next_notes = frozenset(remaining)
        if self.state.active_output_notes == next_notes:
            return (
                had_retrigger
                or had_realtime_events
                or had_realtime_retrigger
                or realtime_changed
            )
        self.state.active_output_notes = next_notes
        return True

    def _notify(self) -> None:
        self.view.render(self.state)

    def _log(self, message: str) -> None:
        self.view.append_log(message)

    def _message(self, level: str, title_key: str, message: str) -> None:
        self.view.show_message(level, self.text(title_key), message)

    @staticmethod
    def format_time(seconds: float) -> str:
        total = max(0, int(round(seconds)))
        return f"{total // 60:02d}:{total % 60:02d}"

    @classmethod
    def format_note_range(cls, note_range: tuple[int, int] | None) -> str:
        if note_range is None:
            return "--"
        return f"{cls.format_midi_note(note_range[0])}-{cls.format_midi_note(note_range[1])}"

    @staticmethod
    def format_midi_note(note: int) -> str:
        names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
        return f"{names[note % 12]}{note // 12 - 1}"

    @staticmethod
    def _clamp_int(value: object, minimum: int, maximum: int, default: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return default
        return max(minimum, min(maximum, number))

    @staticmethod
    def _normalize_ui_scale(value: object) -> int:
        try:
            percent = int(value)
        except (TypeError, ValueError):
            percent = 100
        return min(UI_SCALE_PERCENT_OPTIONS, key=lambda option: abs(option - percent))
