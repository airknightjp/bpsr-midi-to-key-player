from __future__ import annotations

import queue
import stat as stat_module
import threading
import time
import winsound
from dataclasses import replace
from pathlib import Path
from typing import Callable, Protocol

from audio_buffer import (
    normalize_audio_buffer_frames,
    normalize_audio_chunk_frames,
    normalize_audio_fallback_interval_ms,
    normalize_audio_response_frames,
    normalize_qt_audio_frames,
)
from app_state import AppState, MidiListRow, TrackChannelItem
from chord_optimization import ChordOptimizationPlan
from config import (
    INPUT_CONVERSION_MIDI_FILE,
    INPUT_CONVERSION_REALTIME,
    DEFAULT_KEY_BINDINGS,
    DEFAULT_COUNTDOWN_SECONDS,
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
    normalize_midi_column_widths,
    normalize_panel_order,
    normalize_section_visibility,
    normalize_sound_playback_mode,
)
from global_hotkeys import GlobalHotkeyManager, shortcut_to_hotkey_spec
from i18n import TEXT, normalize_color_theme, normalize_language
from keyboard_output import KeyboardOutput
from live_midi_input import MidiInputKeyboardBridge, list_midi_input_devices
from midi_parser import MidiEvent, MidiSummary
from midi_parser_process import MidiParserProcess
from piano_arrangement import cached_piano_arrangement
from piano_arrangement_models import (
    ArrangementPlan,
    PianoArrangementConfig,
    normalize_arrangement_quality,
)
from piano_arrangement_process import PianoArrangementProcess
from playback_timing import MAX_PLAYBACK_SPEED_PERCENT, MIN_PLAYBACK_SPEED_PERCENT
from player import MidiKeyboardPlayer
from rhythm_judgment import RhythmJudge, RhythmJudgment
from settings import AppSettings, load_settings, save_settings
from sound_sources import normalize_sound_source
from sound_player import MidiSoundPlayer, RealtimeMidiSoundOutput
from source_colors import track_channel_color


GAME_COUNTDOWN_KEY_HOLD_SECONDS = 0.12
OUTPUT_NOTE_MIN_VISIBLE_SECONDS = 0.075
RHYTHM_HIT_EVENT_HISTORY_LIMIT = 128
UI_SCALE_PERCENT_OPTIONS = (100, 110, 125, 150, 175, 200)


class ControllerView(Protocol):
    def render(self, state: AppState) -> None: ...

    def render_position(self, position: float, duration: float) -> None: ...

    def show_message(self, level: str, title: str, message: str) -> None: ...

    def schedule_output_note_release(self, delay_ms: int) -> None: ...


class NullView:
    def render(self, _state: AppState) -> None:
        pass

    def render_position(self, _position: float, _duration: float) -> None:
        pass

    def show_message(self, _level: str, _title: str, _message: str) -> None:
        pass

    def schedule_output_note_release(self, _delay_ms: int) -> None:
        pass


class AppController:
    """UI-independent application state and orchestration layer."""

    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or load_settings()
        self.state = AppState(
            language=self.settings.language,
            color_theme=self.settings.color_theme,
            status=TEXT[self.settings.language]["waiting"],
            countdown_seconds=self.settings.countdown_seconds,
            midi_sound_volume=self.settings.midi_sound_volume,
            sound_source=self.settings.sound_source,
            arrangement_quality=normalize_arrangement_quality(
                self.settings.arrangement_quality
            ).value,
            use_piano_arrangement=self.settings.use_piano_arrangement,
            playback_speed_percent=self.settings.playback_speed_percent,
            sound_playback_mode=normalize_sound_playback_mode(
                self.settings.sound_playback_mode
            ),
            play_sound=self.settings.play_sound,
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
            midi_column_widths=normalize_midi_column_widths(
                self.settings.midi_column_widths
            ),
            midi_input_device=self.settings.midi_input_device,
            input_conversion_mode=normalize_input_conversion_mode(
                self.settings.input_conversion_mode
            ),
            section_visibility=normalize_section_visibility(
                self.settings.section_visibility
            ),
            panel_order=normalize_panel_order(self.settings.panel_order),
            audio_qt_frames=normalize_qt_audio_frames(
                self.settings.audio_qt_frames
            ),
            audio_buffer_frames=normalize_audio_buffer_frames(
                self.settings.audio_buffer_frames
            ),
            audio_response_frames=normalize_audio_response_frames(
                self.settings.audio_response_frames
            ),
            audio_chunk_frames=normalize_audio_chunk_frames(
                self.settings.audio_chunk_frames
            ),
            audio_fallback_interval_ms=normalize_audio_fallback_interval_ms(
                self.settings.audio_fallback_interval_ms
            ),
        )
        self.view: ControllerView = NullView()
        self.midi_parser_process = MidiParserProcess()
        self.piano_arrangement_process = PianoArrangementProcess()
        self.source_events: list[MidiEvent] = []
        self.events: list[MidiEvent] = []
        self.summary: MidiSummary | None = None
        self.arrangement_plan: ArrangementPlan | None = None
        self.midi_files: list[Path] = []
        self._midi_cache_root: Path | None = None
        self._midi_file_stats: dict[Path, tuple[int, int]] = {}
        self._midi_sort_keys: dict[
            Path,
            tuple[tuple[str, ...], str, str],
        ] = {}
        self._midi_metadata_complete: set[Path] = set()
        self.last_midi_folder = self.settings.last_midi_folder
        self.last_update_check_at = self.settings.last_update_check_at
        self.key_bindings = normalized_key_bindings(self.settings.key_bindings)
        self.enabled_sources_snapshot: frozenset[tuple[int, int]] = frozenset()
        self.enabled_channels_snapshot: frozenset[int] = frozenset()
        self._source_lock = threading.RLock()
        self.player: MidiKeyboardPlayer | None = None
        self.sound_player: MidiSoundPlayer | None = None
        self.midi_input_bridge: MidiInputKeyboardBridge | None = None
        self.realtime_sound_output: RealtimeMidiSoundOutput | None = None
        self.worker_queue: queue.Queue[tuple[object, ...]] = queue.Queue()
        self.metadata_queue: queue.Queue[tuple[int, Path, str]] = queue.Queue()
        self._event_notifier: Callable[[], None] | None = None
        self._event_notification_lock = threading.Lock()
        self._event_notification_pending = False
        self.metadata_cancel = threading.Event()
        self.metadata_scan_id = 0
        self.playback_id = 0
        self.position_generation = 0
        self.midi_input_id = 0
        self._active_output_notes_by_source: dict[tuple[str, int], set[int]] = {}
        self._active_output_note_sources: dict[
            tuple[str, int],
            set[tuple[int, int, int]],
        ] = {}
        self._output_note_visible_until: dict[int, float] = {}
        self._output_note_release_due: dict[int, float] = {}
        self._realtime_note_visible_until: dict[int, float] = {}
        self._realtime_note_release_due: dict[int, float] = {}
        self._rhythm_judge = RhythmJudge()
        self._rhythm_hit_serial = 0
        self.seeking_keys = False
        self.global_hotkeys: GlobalHotkeyManager | None = None
        self.settings_save_error = ""
        self._settings_dirty = False
        self.exiting = False

    def attach_view(self, view: ControllerView) -> None:
        self.view = view
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

    def _queue_metadata_result(self, result: tuple[int, Path, str]) -> None:
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
        previous_selected_path = (
            self.summary.path
            if self.summary is not None
            else (
                self.midi_files[self.state.selected_midi_index]
                if 0 <= self.state.selected_midi_index < len(self.midi_files)
                else None
            )
        )
        cache_matches = self._midi_cache_root == folder
        previous_rows = (
            {row.path: row for row in self.state.midi_rows}
            if cache_matches
            else {}
        )
        previous_stats = self._midi_file_stats if cache_matches else {}
        previous_sort_keys = self._midi_sort_keys if cache_matches else {}
        if not preserve_sound_playback and self.state.current_mode is not None:
            self.stop_playback()
        try:
            discovered: list[Path] = []
            next_stats: dict[Path, tuple[int, int]] = {}
            next_sort_keys: dict[
                Path,
                tuple[tuple[str, ...], str, str],
            ] = {}
            changed_paths: set[Path] = set()
            for path in folder.rglob("*"):
                if path.suffix.lower() not in {".mid", ".midi"}:
                    continue
                file_stat = path.stat()
                if not stat_module.S_ISREG(file_stat.st_mode):
                    continue
                previous_stat = previous_stats.get(path)
                if (
                    previous_stat is not None
                    and previous_stat[0] == file_stat.st_size
                    and previous_stat[1] == file_stat.st_mtime_ns
                ):
                    next_stats[path] = previous_stat
                else:
                    next_stats[path] = (
                        file_stat.st_size,
                        file_stat.st_mtime_ns,
                    )
                    changed_paths.add(path)

                sort_key = previous_sort_keys.get(path)
                if sort_key is None:
                    relative = path.relative_to(folder)
                    sort_key = (
                        tuple(part.casefold() for part in relative.parent.parts),
                        path.name.casefold(),
                        relative.as_posix(),
                    )
                next_sort_keys[path] = sort_key
                discovered.append(path)
            files = sorted(discovered, key=next_sort_keys.__getitem__)
        except OSError as exc:
            self._message("error", "load_failed_title", str(exc))
            return

        removed_paths = set(previous_stats).difference(next_stats)
        if not cache_matches:
            self._midi_metadata_complete.clear()
        else:
            self._midi_metadata_complete.intersection_update(next_stats)
        self._midi_metadata_complete.difference_update(changed_paths)
        rows = [
            (
                previous_rows[path]
                if path in previous_rows and path not in changed_paths
                else MidiListRow(
                    path=path,
                    name=path.name,
                    folder=self._format_midi_folder(folder, path),
                )
            )
            for path in files
        ]
        rows_changed = (
            len(rows) != len(self.state.midi_rows)
            or any(
                current is not previous
                for current, previous in zip(rows, self.state.midi_rows)
            )
        )
        preserve_sound = preserve_sound_playback and self._sound_playback_is_active()
        self.midi_files = files
        self._midi_cache_root = folder
        self._midi_file_stats = next_stats
        self._midi_sort_keys = next_sort_keys
        if rows_changed:
            self.state.midi_rows = rows
        if save_folder:
            self.last_midi_folder = str(folder)
            self.request_save()

        restart_metadata_scan = (
            not cache_matches
            or bool(changed_paths)
            or bool(removed_paths)
        )
        if not files:
            if restart_metadata_scan:
                self._start_metadata_scan([])
            if not preserve_sound:
                self.cancel_piano_arrangement(notify=False)
                self.source_events = []
                self.events = []
                self.summary = None
                self.arrangement_plan = None
                self.state.arrangement_status = "idle"
                self.state.arrangement_progress = 0
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
            if restart_metadata_scan:
                self._start_metadata_scan(
                    [
                        path
                        for path in files
                        if path not in self._midi_metadata_complete
                    ]
                )
            self._notify()
            return
        selected_index = (
            self._find_midi_index(previous_selected_path)
            if previous_selected_path is not None
            else -1
        )
        if (
            selected_index >= 0
            and previous_selected_path not in changed_paths
            and self.summary is not None
        ):
            self.state.selected_midi_index = selected_index
            if restart_metadata_scan:
                self._start_metadata_scan(
                    [
                        path
                        for path in files
                        if path not in self._midi_metadata_complete
                    ]
                )
            self._notify()
            return
        self.select_midi(selected_index if selected_index >= 0 else 0)
        if restart_metadata_scan:
            self._start_metadata_scan(
                [
                    path
                    for path in files
                    if path not in self._midi_metadata_complete
                ]
            )

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
        self.cancel_piano_arrangement(notify=False)
        if stop_playback and self._playback_mode_is_active():
            self.stop_playback()
        try:
            events, summary = self.midi_parser_process.parse(path)
        except Exception as exc:
            self._message("error", "load_failed_title", str(exc))
            return False
        self._reset_rhythm_judgments()
        self.source_events = events
        self.events = events
        self.summary = summary
        self.arrangement_plan = None
        self.state.duration = summary.duration
        self.state.position = 0.0
        self._set_track_channels(summary)
        self._load_cached_piano_arrangement()
        return True

    def current_piano_arrangement_config(self) -> PianoArrangementConfig:
        return PianoArrangementConfig(
            quality=normalize_arrangement_quality(
                self.state.arrangement_quality
            )
        ).normalized()

    def analyze_selected_midi(self) -> None:
        if self.state.arrangement_status == "analyzing":
            self.cancel_piano_arrangement()
            return
        if self.summary is None:
            self._message("info", "no_midi_title", self.text("load_midi_first"))
            return
        config = self.current_piano_arrangement_config()
        source_path = self.summary.path
        self.state.arrangement_status = "analyzing"
        self.state.arrangement_progress = 0
        self._notify()
        try:
            self.piano_arrangement_process.start(
                source_path,
                config,
                on_progress=lambda value: self._queue_worker_message(
                    ("arrangement_progress", int(value))
                ),
                on_complete=lambda source_hash, config_key: self._queue_worker_message(
                    ("arrangement_complete", source_hash, config_key)
                ),
                on_error=lambda message: self._queue_worker_message(
                    ("arrangement_error", message)
                ),
                on_cancelled=lambda: self._queue_worker_message(
                    ("arrangement_cancelled",)
                ),
            )
        except Exception as exc:
            self.state.arrangement_status = "error"
            self.state.arrangement_progress = 0
            self._notify()
            self._message("error", "arrangement_title", str(exc))

    def cancel_piano_arrangement(self, *, notify: bool = True) -> None:
        self.piano_arrangement_process.cancel()
        if self.state.arrangement_status == "analyzing":
            self.state.arrangement_status = (
                "ready" if self.arrangement_plan is not None else "idle"
            )
            self.state.arrangement_progress = 0
            if notify:
                self._notify()

    def _load_cached_piano_arrangement(self) -> bool:
        summary = self.summary
        if summary is None or not summary.file_hash:
            self.arrangement_plan = None
            self.events = self.source_events
            self.state.arrangement_status = "idle"
            self.state.arrangement_progress = 0
            return False
        plan = cached_piano_arrangement(
            summary.file_hash,
            self.current_piano_arrangement_config(),
        )
        if plan is None:
            self.arrangement_plan = None
            self.events = self.source_events
            self.state.duration = summary.duration
            self.state.arrangement_status = "idle"
            self.state.arrangement_progress = 0
            return False
        self.arrangement_plan = plan
        if self.state.use_piano_arrangement:
            self.events = plan.to_midi_events()
            self.state.duration = plan.duration
        else:
            self.events = self.source_events
            self.state.duration = summary.duration
        self.state.arrangement_status = "ready"
        self.state.arrangement_progress = 100
        return True

    def _reload_piano_arrangement(self, *, apply_live: bool) -> bool:
        previous_events = self.events
        loaded = self._load_cached_piano_arrangement()
        if apply_live and self.events is not previous_events:
            self._apply_current_events_to_active_playback()
        return loaded

    def _apply_current_events_to_active_playback(self) -> None:
        position = self.state.position
        if self.state.keyboard_playing and self.player and self.player.is_playing:
            current_position = self.player.current_position()
            if current_position is not None:
                position = current_position
            self.seek(position)
            return
        if (
            self.state.sound_playing
            and self.sound_player
            and self.sound_player.is_playing
        ):
            current_position = self.sound_player.current_position()
            if current_position is not None:
                position = current_position
            position = max(0.0, min(self.state.duration, position))
            self._next_position_generation()
            self._reset_rhythm_judgments()
            self._clear_active_output_notes("sound")
            self.state.position = position
            self.sound_player.switch(self.events, start_time=position)
            return
        self.state.position = max(
            0.0,
            min(self.state.duration, self.state.position),
        )

    def start_keyboard_conversion_from_shortcut(self) -> None:
        if (
            self.state.input_conversion_mode != INPUT_CONVERSION_MIDI_FILE
            or self.state.midi_input_running
            or self.state.keyboard_playing
        ):
            return
        if (
            self.state.keyboard_paused
            or self.state.sound_playing
            or self.state.sound_paused
        ):
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
            if self.state.sound_playing or self.state.sound_paused:
                self.stop_playback()
                self.play_keyboard(start_time=0.0)
            else:
                self.play_keyboard()

    def toggle_keyboard_pause(self) -> None:
        if self.state.keyboard_playing:
            player = self.player
            sound_player = self.sound_player
            position = self.state.position
            if player:
                current_position = player.current_position()
                if current_position is not None:
                    position = current_position
                self._next_playback_id()
                player.stop()
            if sound_player:
                sound_player.stop()
            if player:
                player.wait_until_stopped(timeout=2.0)
            if sound_player:
                sound_player.wait_until_stopped(timeout=2.0)
            self.player = None
            self.sound_player = None
            self._cancel_rhythm_judgments()
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
        self._cancel_rhythm_judgments()
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
        self.play_sound(start_time=position)

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
        events = self.events
        output = KeyboardOutput()
        self.sound_player = (
            self._create_midi_sound_player(playback_id, report_playback=False)
            if self.state.play_sound
            else None
        )
        self.player = MidiKeyboardPlayer(
            output=output,
            on_state=lambda status, pid=playback_id, source_events=events, source_position=position: (
                self._handle_keyboard_player_state(
                    status,
                    pid,
                    source_events,
                    source_position,
                )
            ),
            on_error=lambda message, pid=playback_id: self._queue_worker_message(
                ("playback_error", pid, message)
            ),
            on_position=lambda value, pid=playback_id: self._queue_position_message(pid, value),
            on_optimization_progress=lambda progress, pid=playback_id: (
                self._queue_worker_message(("optimization", pid, progress))
            ),
            on_output_note=lambda note, pressed, pid=playback_id: self._queue_worker_message(
                ("key_output_note", pid, note, pressed)
            ),
            on_output_source_note=lambda note, track, channel, pressed, pid=playback_id: (
                self._queue_worker_message(
                    (
                        "key_output_source",
                        pid,
                        note,
                        track,
                        channel,
                        pressed,
                    )
                )
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
            self._reset_rhythm_judgments()
            self._clear_active_output_notes()
            self.state.input_conversion_mode = INPUT_CONVERSION_MIDI_FILE
            self.state.current_mode = "keys"
            self._notify()
            self.player.play_with_countdown_sound(
                events,
                countdown_seconds=self.state.countdown_seconds if countdown else 0,
                start_time=position,
                on_countdown_tick=self._play_countdown_tick if self._countdown_tick_enabled() else None,
            )
        except RuntimeError as exc:
            self.player = None
            self.sound_player = None
            self.state.current_mode = None
            self._notify()
            self._message("warning", "already_playing_title", str(exc))

    def play_sound(
        self,
        *,
        start_time: float | None = None,
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
        self.sound_player = self._create_midi_sound_player(
            playback_id,
            report_playback=True,
        )

        try:
            self._reset_rhythm_judgments()
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

    def _create_midi_sound_player(
        self,
        playback_id: int,
        *,
        report_playback: bool,
    ) -> MidiSoundPlayer:
        return MidiSoundPlayer(
            on_state=(
                lambda status, pid=playback_id: self._queue_worker_message(
                    ("sound_state", pid, status)
                )
                if report_playback
                else None
            ),
            on_error=lambda message, pid=playback_id: self._queue_worker_message(
                ("playback_error", pid, message)
            ),
            on_position=(
                lambda value, pid=playback_id: self._queue_position_message(
                    pid,
                    value,
                )
                if report_playback
                else None
            ),
            on_optimization_progress=(
                lambda progress, pid=playback_id: self._queue_worker_message(
                    ("optimization", pid, progress)
                )
                if report_playback
                else None
            ),
            on_output_note=(
                lambda note, pressed, pid=playback_id: self._queue_worker_message(
                    ("sound_output_note", pid, note, pressed, time.monotonic())
                )
                if report_playback
                else None
            ),
            on_output_remap=(
                lambda note, pressed, pid=playback_id: self._queue_worker_message(
                    ("sound_output_remap", pid, note, pressed)
                )
                if report_playback
                else None
            ),
            on_output_source_note=(
                lambda note, track, channel, pressed, pid=playback_id: self._queue_worker_message(
                    (
                        "sound_output_source",
                        pid,
                        note,
                        track,
                        channel,
                        pressed,
                    )
                )
                if report_playback
                else None
            ),
            enabled_channels=self.enabled_channels,
            enabled_sources=self.enabled_sources,
            volume=self.state.midi_sound_volume,
            sound_source=self.state.sound_source,
            on_audio_runtime_changed=lambda qt_frames, buffer_frames, response_frames, chunk_frames, fallback_interval_ms, _reason: self._queue_worker_message(
                (
                    "audio_runtime",
                    qt_frames,
                    buffer_frames,
                    response_frames,
                    chunk_frames,
                    fallback_interval_ms,
                )
            ),
            audio_qt_frames=self.state.audio_qt_frames,
            audio_buffer_frames=self.state.audio_buffer_frames,
            audio_response_frames=self.state.audio_response_frames,
            audio_chunk_frames=self.state.audio_chunk_frames,
            audio_fallback_interval_ms=(
                self.state.audio_fallback_interval_ms
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

    def _handle_keyboard_player_state(
        self,
        status: str,
        playback_id: int,
        events: list[MidiEvent],
        start_time: float,
    ) -> None:
        self._queue_worker_message(("key_state", playback_id, status))
        if status == "playing":
            self._start_keyboard_sound(
                playback_id,
                events,
                start_time,
            )

    def _start_keyboard_sound(
        self,
        playback_id: int,
        events: list[MidiEvent],
        start_time: float,
    ) -> None:
        if (
            playback_id != self.playback_id
            or not self.state.keyboard_playing
            or not self.state.play_sound
        ):
            return
        sound_player = self.sound_player
        if sound_player is None:
            sound_player = self._create_midi_sound_player(
                playback_id,
                report_playback=False,
            )
            self.sound_player = sound_player
        if sound_player.is_playing:
            return
        try:
            sound_player.play(events, start_time=start_time)
            if (
                playback_id != self.playback_id
                or self.sound_player is not sound_player
                or not self.state.keyboard_playing
                or not self.state.play_sound
            ):
                sound_player.stop()
                sound_player.wait_until_stopped(timeout=2.0)
        except RuntimeError as exc:
            if self.sound_player is sound_player:
                self.sound_player = None
            self._queue_worker_message(
                ("keyboard_sound_error", playback_id, str(exc))
            )

    def _set_keyboard_sound_enabled(self, enabled: bool) -> None:
        if not self.state.keyboard_playing or self.player is None:
            return
        if not enabled:
            sound_player = self.sound_player
            self.sound_player = None
            if sound_player:
                sound_player.stop()
                sound_player.wait_until_stopped(timeout=2.0)
            return
        position = self.player.current_position()
        if position is not None:
            self._start_keyboard_sound(
                self.playback_id,
                self.events,
                position,
            )

    def stop_playback(self) -> None:
        self._next_playback_id()
        self._next_position_generation()
        player = self.player
        sound_player = self.sound_player
        stopped_mode = self.state.current_mode
        if player:
            player.stop()
        if sound_player:
            sound_player.stop()
        if player:
            player.wait_until_stopped(timeout=2.0)
        if sound_player:
            sound_player.wait_until_stopped(timeout=2.0)
        self.player = None
        self.sound_player = None
        self.state.current_mode = None
        self._cancel_rhythm_judgments()
        if stopped_mode in {"keys", "keys_paused"}:
            self._clear_active_output_notes()
        elif stopped_mode in {"sound", "sound_paused"}:
            self._clear_active_output_notes("sound")
        self.seeking_keys = False
        self.state.position = 0.0
        if stopped_mode in {"sound", "sound_paused"}:
            self.state.status = "sound stopped"
        elif stopped_mode in {"keys", "keys_paused"}:
            self.state.status = "stopped"
        self._notify()

    def start_midi_input(self) -> None:
        if self.state.keyboard_playing or self.state.keyboard_paused or self.state.midi_input_running:
            return
        device_id = self._selected_midi_input_device_id()
        if device_id is None:
            self._message("info", "no_midi_title", self.text("no_midi_input_devices"))
            return
        input_id = self._next_midi_input_id()
        self._close_realtime_sound_output()
        output = KeyboardOutput()
        self.realtime_sound_output = RealtimeMidiSoundOutput(
            volume=self.state.midi_sound_volume,
            sound_source=self.state.sound_source,
            on_audio_runtime_changed=lambda qt_frames, buffer_frames, response_frames, chunk_frames, fallback_interval_ms, _reason: self._queue_worker_message(
                (
                    "audio_runtime",
                    qt_frames,
                    buffer_frames,
                    response_frames,
                    chunk_frames,
                    fallback_interval_ms,
                )
            ),
            audio_qt_frames=self.state.audio_qt_frames,
            audio_buffer_frames=self.state.audio_buffer_frames,
            audio_response_frames=self.state.audio_response_frames,
            audio_chunk_frames=self.state.audio_chunk_frames,
            audio_fallback_interval_ms=(
                self.state.audio_fallback_interval_ms
            ),
            transpose_semitones=self.state.transpose_semitones,
            octave_shift=self.state.octave_shift,
            auto_sustain=self.state.auto_sustain,
            repeat_prevention=self.state.repeat_prevention,
        )
        self.realtime_sound_output.set_enabled(self.state.play_sound)
        bridge = MidiInputKeyboardBridge(
            device_id=device_id,
            output=output,
            on_state=lambda status: self._queue_worker_message(("midi_input_state", status)),
            on_midi_message=self.realtime_sound_output.process_message,
            on_output_note=lambda note, pressed, iid=input_id: self._queue_worker_message(
                ("midi_output_note", iid, note, pressed, time.monotonic())
            ),
            on_output_source_note=lambda note, track, channel, pressed, iid=input_id: (
                self._queue_worker_message(
                    (
                        "midi_output_source",
                        iid,
                        note,
                        track,
                        channel,
                        pressed,
                    )
                )
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
            self._reset_rhythm_judgments()
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
        self._cancel_rhythm_judgments()
        self._clear_active_output_notes("midi")
        self._notify()

    def refresh_midi_input_devices(self, *, notify: bool = True) -> None:
        previous = self.state.midi_input_device
        try:
            devices = list_midi_input_devices()
        except Exception:
            devices = []
        self.midi_input_devices = devices
        names = [name for _device_id, name in devices]
        self.state.midi_input_devices = names
        self.state.midi_input_device = previous if previous in names else (names[0] if names else "")
        self.request_save()
        if notify:
            self._notify()

    def set_option(self, name: str, value: object) -> None:
        if name in {
            "play_sound",
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
            self.state.countdown_seconds = self._clamp_int(
                value,
                0,
                10,
                DEFAULT_COUNTDOWN_SECONDS,
            )
        elif name == "midi_sound_volume":
            self.state.midi_sound_volume = self._clamp_int(value, 0, 100, 80)
        elif name == "audio_qt_frames":
            self.state.audio_qt_frames = normalize_qt_audio_frames(value)
        elif name == "audio_buffer_frames":
            self.state.audio_buffer_frames = normalize_audio_buffer_frames(
                value
            )
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
        elif name == "arrangement_quality":
            self.cancel_piano_arrangement(notify=False)
            self.state.arrangement_quality = normalize_arrangement_quality(
                value
            ).value
            self._reload_piano_arrangement(apply_live=True)
        elif name == "use_piano_arrangement":
            self.state.use_piano_arrangement = bool(value)
            self._reload_piano_arrangement(apply_live=True)
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
            self._cancel_rhythm_judgments()
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
        if (
            self.state.keyboard_playing or self.state.keyboard_paused
        ) and self.player:
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

    def _apply_track_channel_change(self) -> None:
        if self.state.keyboard_playing and self.player and self.player.is_playing:
            self.player.request_chord_optimization_refresh()
            self.player.request_release_all()
            if self.sound_player and self.sound_player.is_playing:
                self.sound_player.request_chord_optimization_refresh()
                self.sound_player.release_all()
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
        self._reset_rhythm_judgments()
        self.state.position = value
        if self.state.sound_playing and self.sound_player and self.sound_player.is_playing:
            self.sound_player.seek(value)
        elif self.state.keyboard_playing and self.player and self.player.is_playing:
            old_player = self.player
            old_sound_player = self.sound_player
            self.seeking_keys = True
            old_player.stop()
            if old_sound_player:
                old_sound_player.stop()
            old_player.wait_until_stopped(timeout=2.0)
            if old_sound_player:
                old_sound_player.wait_until_stopped(timeout=2.0)
            self.sound_player = None
            if old_player.is_playing:
                self.seeking_keys = False
            else:
                self.player = None
                self.state.current_mode = None
                self.play_keyboard(start_time=value, countdown=False)
                self.seeking_keys = False
        self._notify()

    def process_pending_events(self) -> None:
        try:
            changed = self._drain_metadata_queue()
            position_changed = False
            released_output_notes: set[int] = set()
            completed_sound_mode: str | None = None
            while True:
                try:
                    message = self.worker_queue.get_nowait()
                except queue.Empty:
                    break
                kind = str(message[0])
                if kind == "arrangement_progress":
                    if self.state.arrangement_status == "analyzing":
                        self.state.arrangement_progress = self._clamp_int(
                            message[1], 0, 100, 0
                        )
                        changed = True
                    continue
                if kind == "arrangement_complete":
                    source_hash = str(message[1])
                    config_key = str(message[2])
                    if (
                        self.summary is not None
                        and self.summary.file_hash == source_hash
                        and self.current_piano_arrangement_config().cache_key()
                        == config_key
                    ):
                        self._reload_piano_arrangement(apply_live=True)
                    else:
                        self.state.arrangement_status = "idle"
                        self.state.arrangement_progress = 0
                    changed = True
                    continue
                if kind == "arrangement_cancelled":
                    if self.state.arrangement_status == "analyzing":
                        self.state.arrangement_status = (
                            "ready"
                            if self.arrangement_plan is not None
                            else "idle"
                        )
                        self.state.arrangement_progress = 0
                        changed = True
                    continue
                if kind == "arrangement_error":
                    self.state.arrangement_status = "error"
                    self.state.arrangement_progress = 0
                    self._message(
                        "error",
                        "arrangement_title",
                        str(message[1]),
                    )
                    changed = True
                    continue
                if kind == "audio_runtime":
                    try:
                        qt_frames = max(1, int(message[1]))
                    except (TypeError, ValueError):
                        qt_frames = self.state.audio_qt_frames
                    buffer_frames = normalize_audio_buffer_frames(message[2])
                    response_frames = normalize_audio_response_frames(
                        message[3]
                    )
                    chunk_frames = normalize_audio_chunk_frames(message[4])
                    fallback_interval_ms = (
                        normalize_audio_fallback_interval_ms(message[5])
                    )
                    if (
                        qt_frames != self.state.audio_qt_frames
                        or buffer_frames != self.state.audio_buffer_frames
                        or response_frames
                        != self.state.audio_response_frames
                        or chunk_frames != self.state.audio_chunk_frames
                        or fallback_interval_ms
                        != self.state.audio_fallback_interval_ms
                    ):
                        self.state.audio_qt_frames = qt_frames
                        self.state.audio_buffer_frames = buffer_frames
                        self.state.audio_response_frames = response_frames
                        self.state.audio_chunk_frames = chunk_frames
                        self.state.audio_fallback_interval_ms = (
                            fallback_interval_ms
                        )
                        changed = True
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
                    "keyboard_sound_error",
                    "playback_error",
                    "position",
                    "optimization",
                    "key_output_note",
                    "sound_output_note",
                    "sound_output_remap",
                    "key_output_source",
                    "sound_output_source",
                }:
                    if int(message[1]) != self.playback_id:
                        continue
                if kind == "midi_output_note" and int(message[1]) != self.midi_input_id:
                    continue
                if (
                    kind == "midi_output_source"
                    and int(message[1]) != self.midi_input_id
                ):
                    continue
                if kind == "key_state":
                    status = str(message[2])
                    self.state.status = status
                    if status == "stopped" and not self.seeking_keys and self.state.keyboard_playing:
                        sound_player = self.sound_player
                        self.sound_player = None
                        if sound_player:
                            sound_player.stop()
                            sound_player.wait_until_stopped(timeout=2.0)
                        self.state.current_mode = None
                        self._cancel_rhythm_judgments()
                        self._clear_active_output_notes()
                    changed = True
                elif kind == "keyboard_sound_error":
                    self._message(
                        "warning",
                        "already_playing_title",
                        str(message[2]),
                    )
                elif kind == "playback_error":
                    self._message(
                        "error",
                        "playback_failed_title",
                        str(message[2]),
                    )
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
                        self._cancel_rhythm_judgments()
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
                    next_position = max(
                        0.0,
                        min(self.state.duration, float(message[3])),
                    )
                    if next_position != self.state.position:
                        self.state.position = next_position
                        position_changed = True
                elif kind == "optimization":
                    progress = message[2]
                    if progress is None:
                        self.state.status = (
                            "playing"
                            if self.state.keyboard_playing
                            else "sound playing"
                        )
                    else:
                        percent = self._clamp_int(progress, 0, 100, 0)
                        self.state.status = self.text(
                            "optimization_progress"
                        ).format(percent=percent)
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
                    rhythm_judgment: RhythmJudgment | None = None
                    released = not pressed
                    if self._rhythm_judging_is_enabled():
                        if (
                            kind == "key_output_note"
                            and self.state.keyboard_playing
                        ):
                            rhythm_judgment = (
                                self._rhythm_judge.record_automatic_perfect(
                                    note,
                                    released=released,
                                )
                            )
                        elif (
                            kind == "sound_output_note"
                            and self.state.sound_playing
                        ):
                            if self.state.midi_input_running:
                                rhythm_judgment = (
                                    self._rhythm_judge.record_expected(
                                        note,
                                        event_at,
                                        released=released,
                                    )
                                )
                            else:
                                rhythm_judgment = (
                                    self._rhythm_judge.record_automatic_perfect(
                                        note,
                                        released=released,
                                    )
                                )
                        elif (
                            kind == "midi_output_note"
                            and self._rhythm_judging_is_active()
                        ):
                            rhythm_judgment = self._rhythm_judge.record_input(
                                note,
                                event_at,
                                released=released,
                            )
                    if rhythm_judgment is not None:
                        changed = (
                            self._record_rhythm_judgment_event(
                                rhythm_judgment
                            )
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
                elif kind in {
                    "key_output_source",
                    "sound_output_source",
                    "midi_output_source",
                }:
                    source_kind = {
                        "key_output_source": "key",
                        "sound_output_source": "sound",
                        "midi_output_source": "midi",
                    }[kind]
                    changed = self._set_output_note_source_state(
                        (source_kind, int(message[1])),
                        int(message[2]),
                        int(message[3]),
                        int(message[4]),
                        bool(message[5]),
                    ) or changed
            if completed_sound_mode is not None:
                changed = (
                    self._continue_sound_after_end(completed_sound_mode)
                    or changed
                )
            changed = self._expire_output_note_releases() or changed
            if changed:
                self._notify()
            elif position_changed:
                self._notify_position()
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

    def set_midi_column_widths(self, widths: object) -> None:
        normalized = normalize_midi_column_widths(widths)
        if normalized == self.state.midi_column_widths:
            return
        self.state.midi_column_widths = normalized
        self.request_save()

    def record_update_check(self, checked_at: int) -> bool:
        self.last_update_check_at = max(0, int(checked_at))
        return self.save_settings_now()

    def save_settings_now(self) -> bool:
        try:
            save_settings(self.current_settings())
        except Exception as exc:
            message = f"Settings could not be saved: {exc}"
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
            arrangement_quality=self.state.arrangement_quality,
            use_piano_arrangement=self.state.use_piano_arrangement,
            play_sound=self.state.play_sound,
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
            midi_column_widths=normalize_midi_column_widths(
                self.state.midi_column_widths
            ),
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
            audio_qt_frames=self.state.audio_qt_frames,
            audio_buffer_frames=self.state.audio_buffer_frames,
            audio_response_frames=self.state.audio_response_frames,
            audio_chunk_frames=self.state.audio_chunk_frames,
            audio_fallback_interval_ms=(
                self.state.audio_fallback_interval_ms
            ),
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
        self.piano_arrangement_process.shutdown()
        self.midi_parser_process.shutdown()
        self._save_settings_on_shutdown()

    def _apply_live_option(self, name: str) -> None:
        if name == "play_sound":
            self._set_keyboard_sound_enabled(self.state.play_sound)
            if self.realtime_sound_output:
                self.realtime_sound_output.set_enabled(self.state.play_sound)
        elif name == "midi_sound_volume":
            if self.sound_player:
                self.sound_player.set_volume(self.state.midi_sound_volume)
            if self.realtime_sound_output:
                self.realtime_sound_output.set_volume(self.state.midi_sound_volume)
        elif name == "sound_source":
            for target in (self.sound_player, self.realtime_sound_output):
                if target:
                    target.set_sound_source(self.state.sound_source)
        elif name in {"audio_qt_frames", "audio_buffer_frames"}:
            for target in (self.sound_player, self.realtime_sound_output):
                if target:
                    target.set_audio_settings(
                        self.state.audio_qt_frames,
                        self.state.audio_buffer_frames,
                        self.state.audio_response_frames,
                        self.state.audio_chunk_frames,
                        self.state.audio_fallback_interval_ms,
                    )
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
                self.player.set_chord_optimization(
                    self.state.chord_optimization
                )
            if self.sound_player:
                self.sound_player.set_chord_optimization(
                    self.state.chord_optimization
                )
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
            TrackChannelItem(
                track=track,
                channel=channel,
                enabled=True,
                color=track_channel_color(track, channel),
            )
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
        if self.state.countdown_sound:
            try:
                winsound.Beep(1200 if remaining == 1 else 880, 90)
            except RuntimeError:
                pass
        if self.state.game_countdown_sound:
            key = self.current_key_bindings()[48]
            output = KeyboardOutput()
            threading.Thread(
                target=self._tap_countdown_game_key,
                args=(output, key, self.playback_id),
                daemon=True,
            ).start()

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
                    _events, summary = self.midi_parser_process.parse(path)
                    duration = self.format_time(summary.duration)
                except Exception:
                    duration = "--:--"
                self._queue_metadata_result((scan_id, path, duration))

        threading.Thread(target=scan, daemon=True).start()

    def _drain_metadata_queue(self) -> bool:
        rows = self.state.midi_rows
        row_indexes = {row.path: index for index, row in enumerate(rows)}
        updated_rows: list[MidiListRow] | None = None
        while True:
            try:
                scan_id, path, duration = self.metadata_queue.get_nowait()
            except queue.Empty:
                break
            if scan_id != self.metadata_scan_id:
                continue
            self._midi_metadata_complete.add(path)
            index = row_indexes.get(path)
            if index is None:
                continue
            row = updated_rows[index] if updated_rows is not None else rows[index]
            if row.duration == duration:
                continue
            if updated_rows is None:
                updated_rows = list(rows)
            updated_rows[index] = replace(
                row,
                duration=duration,
            )
        if updated_rows is None:
            return False
        self.state.midi_rows = updated_rows
        return True

    def _update_row_metadata(self, path: Path, summary: MidiSummary | None) -> None:
        if summary is None:
            return
        self._midi_metadata_complete.add(path)
        for index, row in enumerate(self.state.midi_rows):
            if row.path == path:
                duration = self.format_time(summary.duration)
                if row.duration == duration:
                    return
                rows = list(self.state.midi_rows)
                rows[index] = replace(
                    row,
                    duration=duration,
                )
                self.state.midi_rows = rows
                return

    def _find_midi_index(self, path: Path) -> int:
        for index, candidate in enumerate(self.midi_files):
            if candidate == path:
                return index
        return -1

    @staticmethod
    def _format_midi_folder(root: Path, path: Path) -> str:
        root_name = root.name or root.anchor.rstrip("\\/") or str(root)
        relative_parent = path.relative_to(root).parent
        return " > ".join((root_name, *relative_parent.parts))

    def _bind_global_hotkeys(self) -> None:
        self._unbind_global_hotkeys()
        specs = []
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
        if (
            pause_spec is not None
            and (pause_spec.modifiers, pause_spec.vk) not in used_shortcuts
        ):
            specs.append(pause_spec)
            used_shortcuts[(pause_spec.modifiers, pause_spec.vk)] = "pause/resume"
        if (
            stop_spec is not None
            and (stop_spec.modifiers, stop_spec.vk) not in used_shortcuts
        ):
            specs.append(stop_spec)
        manager = GlobalHotkeyManager(
            specs,
            lambda action: self._queue_worker_message(("hotkey", action)),
        )
        manager.start()
        self.global_hotkeys = manager

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

    def _rhythm_judging_is_enabled(self) -> bool:
        return bool(self.state.section_visibility.get("piano_roll", True))

    def _rhythm_judging_is_active(self) -> bool:
        return (
            self._rhythm_judging_is_enabled()
            and self.state.sound_playing
            and self.state.midi_input_running
        )

    def _reset_rhythm_judgments(self) -> None:
        self._rhythm_judge.reset()
        self.state.rhythm_hit_events = ()

    def _cancel_rhythm_judgments(self) -> None:
        self._rhythm_judge.cancel_pending()

    def _record_rhythm_judgment_event(
        self,
        result: RhythmJudgment,
    ) -> bool:
        self._rhythm_hit_serial += 1
        event = (
            self._rhythm_hit_serial,
            int(result.note),
            str(result.judgment).upper(),
            bool(result.released),
        )
        self.state.rhythm_hit_events = (
            *self.state.rhythm_hit_events,
            event,
        )[-RHYTHM_HIT_EVENT_HISTORY_LIMIT:]
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

    def _set_output_note_source_state(
        self,
        playback_source: tuple[str, int],
        note: int,
        track: int,
        channel: int,
        pressed: bool,
    ) -> bool:
        if not PIANO_NOTE_MIN <= note <= PIANO_NOTE_MAX:
            return False
        source_notes = self._active_output_note_sources.setdefault(
            playback_source,
            set(),
        )
        source_entry = (note, track, channel)
        if pressed:
            source_notes.add(source_entry)
        else:
            source_notes.discard(source_entry)
            if not source_notes:
                self._active_output_note_sources.pop(playback_source, None)
        output_sources = tuple(
            sorted(
                set().union(*self._active_output_note_sources.values())
                if self._active_output_note_sources
                else set()
            )
        )
        realtime_sources = tuple(
            sorted(
                set().union(
                    *(
                        entries
                        for source, entries in self._active_output_note_sources.items()
                        if source[0] == "midi"
                    )
                )
                if any(
                    source[0] == "midi"
                    for source in self._active_output_note_sources
                )
                else set()
            )
        )
        if (
            output_sources == self.state.output_note_sources
            and realtime_sources == self.state.realtime_output_note_sources
        ):
            return False
        self.state.output_note_sources = output_sources
        self.state.realtime_output_note_sources = realtime_sources
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
            self._active_output_note_sources.clear()
            remaining: set[int] = set()
        else:
            for source in [
                item for item in self._active_output_notes_by_source if item[0] == source_kind
            ]:
                self._active_output_notes_by_source.pop(source, None)
            for source in [
                item
                for item in self._active_output_note_sources
                if item[0] == source_kind
            ]:
                self._active_output_note_sources.pop(source, None)
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
        next_output_sources = tuple(
            sorted(
                set().union(*self._active_output_note_sources.values())
                if self._active_output_note_sources
                else set()
            )
        )
        next_realtime_sources = tuple(
            sorted(
                {
                    entry
                    for source, entries in self._active_output_note_sources.items()
                    if source[0] == "midi"
                    for entry in entries
                }
            )
        )
        source_colors_changed = (
            self.state.output_note_sources != next_output_sources
            or self.state.realtime_output_note_sources != next_realtime_sources
        )
        self.state.output_note_sources = next_output_sources
        self.state.realtime_output_note_sources = next_realtime_sources
        if self.state.active_output_notes == next_notes:
            return (
                had_retrigger
                or had_realtime_events
                or had_realtime_retrigger
                or realtime_changed
                or source_colors_changed
            )
        self.state.active_output_notes = next_notes
        return True

    def _notify(self) -> None:
        self.view.render(self.state)

    def _notify_position(self) -> None:
        self.view.render_position(self.state.position, self.state.duration)

    def _message(self, level: str, title_key: str, message: str) -> None:
        self.view.show_message(level, self.text(title_key), message)

    @staticmethod
    def format_time(seconds: float) -> str:
        total = max(0, int(round(seconds)))
        return f"{total // 60:02d}:{total % 60:02d}"

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
