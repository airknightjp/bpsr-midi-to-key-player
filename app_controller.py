from __future__ import annotations

import queue
import threading
import time
import winsound
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from app_state import AppState, MidiListRow, TrackChannelItem
from config import (
    DEFAULT_KEY_BINDINGS,
    DEFAULT_KEYBOARD_PAUSE_SHORTCUT,
    DEFAULT_KEYBOARD_PLAY_SHORTCUT,
    DEFAULT_KEYBOARD_STOP_SHORTCUT,
    MAX_OCTAVE_SHIFT,
    MAX_TRANSPOSE_SEMITONES,
    MIN_OCTAVE_SHIFT,
    MIN_TRANSPOSE_SEMITONES,
    normalized_key_bindings,
)
from global_hotkeys import GlobalHotkeyManager, shortcut_to_hotkey_spec
from i18n import TEXT, normalize_color_theme, normalize_language
from keyboard_output import KeyboardOutput
from live_midi_input import MidiInputKeyboardBridge, list_midi_input_devices
from midi_parser import MidiEvent, MidiSummary, parse_midi
from playback_timing import MAX_PLAYBACK_SPEED_PERCENT, MIN_PLAYBACK_SPEED_PERCENT
from player import MidiKeyboardPlayer
from settings import AppSettings, consume_settings_error, load_settings, save_settings
from sound_player import MidiSoundPlayer, RealtimeMidiSoundOutput


GAME_COUNTDOWN_KEY_HOLD_SECONDS = 0.12
UI_SCALE_PERCENT_OPTIONS = (100, 110, 125, 150, 175, 200)


class ControllerView(Protocol):
    def render(self, state: AppState) -> None: ...

    def append_log(self, message: str) -> None: ...

    def clear_log(self) -> None: ...

    def show_message(self, level: str, title: str, message: str) -> None: ...


class NullView:
    def render(self, _state: AppState) -> None:
        pass

    def append_log(self, _message: str) -> None:
        pass

    def clear_log(self) -> None:
        pass

    def show_message(self, _level: str, _title: str, _message: str) -> None:
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
            playback_speed_percent=self.settings.playback_speed_percent,
            dry_run=self.settings.dry_run,
            countdown_sound=self.settings.countdown_sound,
            game_countdown_sound=self.settings.game_countdown_sound,
            auto_fit_note_range=self.settings.auto_fit_note_range,
            transpose_semitones=self.settings.transpose_semitones,
            octave_shift=self.settings.octave_shift,
            humanize_timing=self.settings.humanize_timing,
            chord_optimization=self.settings.chord_optimization,
            chord_strum=self.settings.chord_strum,
            repeat_prevention=self.settings.repeat_prevention,
            keyboard_play_shortcut=self.settings.keyboard_play_shortcut,
            keyboard_pause_shortcut=self.settings.keyboard_pause_shortcut,
            keyboard_stop_shortcut=self.settings.keyboard_stop_shortcut,
            shortcut_locked=self.settings.shortcut_locked,
            always_on_top=self.settings.always_on_top,
            tray_resident=self.settings.tray_resident,
            window_opacity=self.settings.window_opacity,
            ui_scale_percent=self._normalize_ui_scale(self.settings.ui_scale_percent),
            window_width=max(1, self.settings.window_width),
            window_height=max(1, self.settings.window_height),
            midi_input_device=self.settings.midi_input_device,
        )
        self.view: ControllerView = NullView()
        self.events: list[MidiEvent] = []
        self.summary: MidiSummary | None = None
        self.midi_files: list[Path] = []
        self.last_midi_folder = self.settings.last_midi_folder
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
        self.metadata_cancel = threading.Event()
        self.metadata_scan_id = 0
        self.playback_id = 0
        self.ignore_player_position_until = 0.0
        self.seeking_keys = False
        self.global_hotkeys: GlobalHotkeyManager | None = None
        self.hotkey_failure_signature: tuple[str, ...] = ()
        self.save_due_at: float | None = None
        self.settings_save_error = ""
        self.exiting = False

    def attach_view(self, view: ControllerView) -> None:
        self.view = view
        if self.settings_load_error:
            self._log(self.settings_load_error)
        self.refresh_midi_input_devices(notify=False)
        self._notify()

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
        if switch_sound and self.summary is not None and selected == self.summary.path:
            self.state.selected_midi_index = index
            self._notify()
            return
        if not self._load_midi_file(selected, stop_playback=not switch_sound):
            return
        self.state.selected_midi_index = index
        self._update_row_metadata(selected, self.summary)
        if switch_sound and self.sound_player:
            self.sound_player.switch(self.events, start_time=0.0)
        self._notify()

    def _load_midi_file(self, path: Path, *, stop_playback: bool) -> bool:
        if stop_playback and self.state.current_mode is not None:
            self.stop_playback()
        try:
            events, summary = parse_midi(path)
        except Exception as exc:
            self._message("error", "load_failed_title", str(exc))
            return False
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

    def toggle_keyboard_playback(self) -> None:
        if self.state.keyboard_playing or self.state.keyboard_paused:
            self.stop_playback()
        elif self.state.current_mode is None and not self.state.midi_input_running:
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
                self.ignore_player_position_until = time.perf_counter() + 0.8
                player.stop()
                player.wait_until_stopped(timeout=2.0)
            self.player = None
            self.state.current_mode = "keys_paused"
            self.state.position = max(0.0, min(self.state.duration, position))
            self.state.status = "paused"
            self._notify()
        elif self.state.keyboard_paused:
            position = self.state.position
            self.state.current_mode = None
            self.play_keyboard(start_time=position, countdown=False)

    def toggle_sound_playback(self) -> None:
        if self.state.sound_playing:
            self.stop_playback()
        elif self.state.current_mode is None:
            self.play_sound()

    def play_keyboard(self, *, start_time: float | None = None, countdown: bool = True) -> None:
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
            log=lambda message: self.worker_queue.put(("log", message)),
            on_state=lambda status, pid=playback_id: self.worker_queue.put(("key_state", pid, status)),
            on_position=lambda value, pid=playback_id: self.worker_queue.put(("position", pid, value)),
            on_optimization_progress=lambda progress, pid=playback_id: self.worker_queue.put(
                ("optimization", pid, progress)
            ),
            enabled_channels=self.enabled_channels,
            enabled_sources=self.enabled_sources,
            auto_fit_note_range=self.state.auto_fit_note_range,
            transpose_semitones=self.state.transpose_semitones,
            octave_shift=self.state.octave_shift,
            humanize_timing=self.state.humanize_timing,
            chord_optimization=self.state.chord_optimization,
            chord_strum=self.state.chord_strum,
            repeat_prevention=self.state.repeat_prevention,
            playback_speed_percent=self.state.playback_speed_percent,
            key_bindings=self.current_key_bindings(),
        )
        try:
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

    def play_sound(self) -> None:
        if self.state.current_mode is not None:
            return
        if self.summary is None:
            self._message("info", "no_midi_title", self.text("load_midi_first"))
            return
        if not self._has_enabled_events():
            self._message("info", "no_events_title", self.text("no_events_enabled"))
            return
        playback_id = self._next_playback_id()
        self.sound_player = MidiSoundPlayer(
            log=lambda message: self.worker_queue.put(("log", message)),
            on_state=lambda status, pid=playback_id: self.worker_queue.put(("sound_state", pid, status)),
            on_position=lambda value, pid=playback_id: self.worker_queue.put(("position", pid, value)),
            on_optimization_progress=lambda progress, pid=playback_id: self.worker_queue.put(
                ("optimization", pid, progress)
            ),
            enabled_channels=self.enabled_channels,
            enabled_sources=self.enabled_sources,
            volume=self.state.midi_sound_volume,
            auto_fit_note_range=self.state.auto_fit_note_range,
            transpose_semitones=self.state.transpose_semitones,
            octave_shift=self.state.octave_shift,
            humanize_timing=self.state.humanize_timing,
            chord_optimization=self.state.chord_optimization,
            chord_strum=self.state.chord_strum,
            repeat_prevention=self.state.repeat_prevention,
            playback_speed_percent=self.state.playback_speed_percent,
        )
        try:
            self.state.current_mode = "sound"
            self._notify()
            self.sound_player.play(self.events, start_time=self._play_start_position())
        except RuntimeError as exc:
            self.sound_player = None
            self.state.current_mode = None
            self._notify()
            self._message("warning", "already_playing_title", str(exc))

    def stop_playback(self) -> None:
        self._next_playback_id()
        self.ignore_player_position_until = time.perf_counter() + 1.0
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
        self.seeking_keys = False
        self.state.position = 0.0
        if stopped_mode == "sound":
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
        self._close_realtime_sound_output()
        output = KeyboardOutput(dry_run=self.state.dry_run)
        self.realtime_sound_output = RealtimeMidiSoundOutput(
            volume=self.state.midi_sound_volume,
            log=lambda message: self.worker_queue.put(("log", message)),
            transpose_semitones=self.state.transpose_semitones,
            octave_shift=self.state.octave_shift,
            repeat_prevention=self.state.repeat_prevention,
        )
        self.realtime_sound_output.set_enabled(self.state.dry_run)
        bridge = MidiInputKeyboardBridge(
            device_id=device_id,
            output=output,
            log=lambda message: self.worker_queue.put(("log", message)),
            on_state=lambda status: self.worker_queue.put(("midi_input_state", status)),
            on_midi_message=self.realtime_sound_output.process_message,
            auto_fit_note_range=self.state.auto_fit_note_range,
            transpose_semitones=self.state.transpose_semitones,
            octave_shift=self.state.octave_shift,
            repeat_prevention=self.state.repeat_prevention,
            key_bindings=self.current_key_bindings(),
        )
        try:
            bridge.start()
        except Exception as exc:
            bridge.stop()
            self._close_realtime_sound_output()
            self._message("warning", "load_failed_title", str(exc))
            return
        self.midi_input_bridge = bridge
        self.state.midi_input_running = True
        self.request_save()
        self._notify()

    def stop_midi_input(self) -> None:
        bridge = self.midi_input_bridge
        self.midi_input_bridge = None
        if bridge:
            bridge.stop()
        self._close_realtime_sound_output()
        self.state.midi_input_running = False
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
            "repeat_prevention",
            "shortcut_locked",
            "always_on_top",
            "tray_resident",
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
        elif name == "midi_input_device":
            self.state.midi_input_device = str(value)
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
        self.state.section_visibility[section] = bool(visible)
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

    def current_key_bindings(self) -> dict[int, str]:
        return normalized_key_bindings(self.key_bindings)

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

    def enable_all_track_channels(self) -> None:
        sources = [(item.track, item.channel) for item in self.state.track_channels]
        if not sources:
            return
        self._set_enabled_sources(sources)
        self.state.track_channels = [replace(item, enabled=True) for item in self.state.track_channels]
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
        self.state.position = value
        self.ignore_player_position_until = time.perf_counter() + 0.8
        if self.state.sound_playing and self.sound_player and self.sound_player.is_playing:
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

    def poll(self) -> None:
        self._drain_metadata_queue()
        changed = False
        while True:
            try:
                message = self.worker_queue.get_nowait()
            except queue.Empty:
                break
            kind = str(message[0])
            if kind == "log":
                self._log(str(message[1]))
                continue
            if kind == "hotkey":
                if message[1] == "play":
                    self.toggle_keyboard_playback()
                elif message[1] == "pause_resume":
                    self.toggle_keyboard_pause()
                elif message[1] == "stop" and (
                    self.state.keyboard_playing or self.state.keyboard_paused
                ):
                    self.stop_playback()
                continue
            if kind in {"key_state", "sound_state", "position", "optimization"}:
                if int(message[1]) != self.playback_id:
                    continue
            if kind == "key_state":
                status = str(message[2])
                self.state.status = status
                if status == "stopped" and not self.seeking_keys and self.state.keyboard_playing:
                    self.state.current_mode = None
                changed = True
            elif kind == "sound_state":
                status = str(message[2])
                self.state.status = status
                if status in {"sound ended", "sound stopped"} and self.state.sound_playing:
                    if status == "sound ended":
                        self.state.position = self.state.duration
                    self.state.current_mode = None
                changed = True
            elif kind == "midi_input_state":
                status = str(message[1])
                self.state.status = status
                if status == "midi input failed":
                    self.stop_midi_input()
                changed = True
            elif kind == "position":
                if time.perf_counter() >= self.ignore_player_position_until:
                    self.state.position = max(0.0, min(self.state.duration, float(message[2])))
                    changed = True
            elif kind == "optimization":
                progress = message[2]
                if progress is None:
                    self.state.status = "playing" if self.state.keyboard_playing else "sound playing"
                else:
                    percent = self._clamp_int(progress, 0, 100, 0)
                    self.state.status = self.text("optimization_progress").format(percent=percent)
                changed = True
        if changed:
            self._notify()
        if self.save_due_at is not None and time.monotonic() >= self.save_due_at:
            self.flush_settings()

    def request_save(self) -> None:
        self.save_due_at = time.monotonic() + 0.3

    def flush_settings(self) -> None:
        self.save_due_at = None
        try:
            save_settings(self.current_settings())
        except Exception as exc:
            message = f"Settings could not be saved: {exc}"
            if message != self.settings_save_error:
                self._log(message)
            self.settings_save_error = message
            if not self.exiting:
                self.save_due_at = time.monotonic() + 2.0
        else:
            self.settings_save_error = ""

    def current_settings(self) -> AppSettings:
        return AppSettings(
            countdown_seconds=self.state.countdown_seconds,
            midi_sound_volume=self.state.midi_sound_volume,
            dry_run=self.state.dry_run,
            countdown_sound=self.state.countdown_sound,
            game_countdown_sound=self.state.game_countdown_sound,
            auto_fit_note_range=self.state.auto_fit_note_range,
            transpose_semitones=self.state.transpose_semitones,
            octave_shift=self.state.octave_shift,
            humanize_timing=self.state.humanize_timing,
            chord_optimization=self.state.chord_optimization,
            chord_strum=self.state.chord_strum,
            repeat_prevention=self.state.repeat_prevention,
            playback_speed_percent=self.state.playback_speed_percent,
            language=self.state.language,
            color_theme=self.state.color_theme,
            always_on_top=self.state.always_on_top,
            tray_resident=self.state.tray_resident,
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
            key_bindings=self.current_key_bindings(),
        )

    def shutdown(self) -> None:
        if self.exiting:
            return
        self.exiting = True
        self.metadata_cancel.set()
        self._unbind_global_hotkeys()
        self.stop_midi_input()
        self.stop_playback()
        self.flush_settings()

    def _apply_live_option(self, name: str) -> None:
        if name == "midi_sound_volume":
            if self.sound_player:
                self.sound_player.set_volume(self.state.midi_sound_volume)
            if self.realtime_sound_output:
                self.realtime_sound_output.set_volume(self.state.midi_sound_volume)
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
        self.worker_queue.put(("log", f"Countdown: {remaining}"))
        if self.state.countdown_sound:
            try:
                winsound.Beep(1200 if remaining == 1 else 880, 90)
            except RuntimeError as exc:
                self.worker_queue.put(("log", f"Countdown sound failed: {exc}"))
        if self.state.game_countdown_sound:
            key = self.current_key_bindings()[48]
            output = KeyboardOutput(dry_run=self.state.dry_run)
            threading.Thread(
                target=self._tap_countdown_game_key,
                args=(output, key),
                daemon=True,
            ).start()
            self.worker_queue.put(("log", f"Countdown game key: {key}"))

    @staticmethod
    def _tap_countdown_game_key(output: KeyboardOutput, key: str) -> None:
        output.press(key)
        try:
            time.sleep(GAME_COUNTDOWN_KEY_HOLD_SECONDS)
        finally:
            output.release(key)

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
                self.metadata_queue.put((scan_id, path, note_range, duration))

        threading.Thread(target=scan, daemon=True).start()

    def _drain_metadata_queue(self) -> None:
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
                    self.state.midi_rows[index] = replace(row, note_range=note_range, duration=duration)
                    changed = True
                    break
        if changed:
            self._notify()

    def _update_row_metadata(self, path: Path, summary: MidiSummary | None) -> None:
        if summary is None:
            return
        for index, row in enumerate(self.state.midi_rows):
            if row.path == path:
                self.state.midi_rows[index] = replace(
                    row,
                    note_range=self.format_note_range(summary.note_range),
                    duration=self.format_time(summary.duration),
                )
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
        manager = GlobalHotkeyManager(specs, lambda action: self.worker_queue.put(("hotkey", action)))
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
