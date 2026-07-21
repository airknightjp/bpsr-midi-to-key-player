from __future__ import annotations

import queue
import ctypes
import sys
import tkinter as tk
import threading
import time
import webbrowser
import winsound
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from config import (
    DEFAULT_KEY_BINDINGS,
    MAX_OCTAVE_SHIFT,
    MAX_TRANSPOSE_SEMITONES,
    MIN_OCTAVE_SHIFT,
    MIN_TRANSPOSE_SEMITONES,
    SUPPORTED_BINDING_KEYS,
    normalized_key_bindings,
)
from i18n import (
    COLOR_THEME_NAMES,
    LANGUAGE_NAMES,
    TEXT,
    color_theme_code_from_name,
    language_code_from_name,
    normalize_color_theme,
    normalize_language,
)
from global_hotkeys import GlobalHotkeyManager, shortcut_to_hotkey_spec
from keyboard_output import KeyboardOutput
from live_midi_input import MidiInputKeyboardBridge, list_midi_input_devices
from midi_parser import MidiEvent, MidiSummary, MidiTrackSummary, parse_midi
from playback_timing import MAX_PLAYBACK_SPEED_PERCENT, MIN_PLAYBACK_SPEED_PERCENT
from player import MidiKeyboardPlayer
from settings import AppSettings, consume_settings_error, load_settings, save_settings
from single_instance import SingleInstance
from sound_player import MidiSoundPlayer, RealtimeMidiSoundOutput
from tray_icon import TrayIcon


CHANNEL_PANE_WIDTH = 38
DEFAULT_WINDOW_WIDTH = 900
DEFAULT_WINDOW_HEIGHT = 560
DEFAULT_WINDOW_SIZE = f"{DEFAULT_WINDOW_WIDTH}x{DEFAULT_WINDOW_HEIGHT}"
MIN_WINDOW_WIDTH = 760
MIN_WINDOW_HEIGHT = 480
ROOT_HORIZONTAL_PADDING = 24
ACTION_BUTTON_WIDTH = 16
MIDI_LIST_COLUMNS = ("duration", "note_range")
APP_ICON_RELATIVE_PATH = Path("assets") / "app_icon_starry_concept.ico"
APP_ICON_PNG_RELATIVE_PATH = Path("assets") / "app_icon_starry_concept.png"
APP_WINDOW_TITLE = "BPSR MIDI to KEY Player"
APP_VERSION = "1.1.1"
APP_COPYRIGHT = "\u00a9 2026 airknightjp"
APP_REPOSITORY_URL = "https://github.com/airknightjp/bpsr-midi-to-key-player"
GAME_COUNTDOWN_KEY_HOLD_SECONDS = 0.12


class App(tk.Tk):
    def __init__(self, single_instance: SingleInstance | None = None):
        super().__init__()
        self.single_instance = single_instance
        self.title(APP_WINDOW_TITLE)
        self.settings = load_settings()
        self.settings_load_error = consume_settings_error()
        self.saved_window_height = max(MIN_WINDOW_HEIGHT, self.settings.window_height)
        self.geometry(f"{DEFAULT_WINDOW_WIDTH}x{self.saved_window_height}")
        self.minsize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self.resizable(False, True)

        self.events: list[MidiEvent] = []
        self.summary: MidiSummary | None = None
        self.midi_files: list[Path] = []
        self.midi_note_range_labels: dict[Path, str] = {}
        self.midi_duration_labels: dict[Path, str] = {}
        self.midi_duration_queue: queue.Queue[
            tuple[int, Path, str, str]
        ] = queue.Queue()
        self.midi_duration_scan_id = 0
        self.midi_duration_scan_cancel = threading.Event()
        self.channel_vars: dict[int, tk.BooleanVar] = {}
        self.enabled_channels_snapshot: frozenset[int] = frozenset()
        self.track_channel_vars: dict[tuple[int, int], tk.BooleanVar] = {}
        self.enabled_sources_snapshot: frozenset[tuple[int, int]] = frozenset()
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.language = normalize_language(self.settings.language)
        self.color_theme = normalize_color_theme(self.settings.color_theme)
        self.state_var = tk.StringVar(value=self._text("waiting"))
        self.dry_run_var = tk.BooleanVar(value=self.settings.dry_run)
        self.countdown_var = tk.IntVar(value=self.settings.countdown_seconds)
        self.countdown_sound_var = tk.BooleanVar(value=self.settings.countdown_sound)
        self.game_countdown_sound_var = tk.BooleanVar(value=self.settings.game_countdown_sound)
        self.humanize_timing_var = tk.BooleanVar(value=self.settings.humanize_timing)
        self.chord_optimization_var = tk.BooleanVar(value=self.settings.chord_optimization)
        self.chord_strum_var = tk.BooleanVar(value=self.settings.chord_strum)
        self.repeat_prevention_var = tk.BooleanVar(value=self.settings.repeat_prevention)
        self.playback_speed_var = tk.IntVar(value=self.settings.playback_speed_percent)
        self.auto_fit_note_range_var = tk.BooleanVar(value=self.settings.auto_fit_note_range)
        self.transpose_semitones_var = tk.IntVar(value=self.settings.transpose_semitones)
        self.octave_shift_var = tk.IntVar(value=self.settings.octave_shift)
        self.sound_volume_var = tk.IntVar(value=self.settings.midi_sound_volume)
        self.color_theme_var = tk.StringVar(value=COLOR_THEME_NAMES[self.language][self.color_theme])
        self.color_theme_menu_var = tk.StringVar(value=self.color_theme)
        self.always_on_top_var = tk.BooleanVar(value=self.settings.always_on_top)
        self.tray_resident_var = tk.BooleanVar(value=self.settings.tray_resident)
        self.window_opacity_var = tk.IntVar(value=self.settings.window_opacity)
        self.keyboard_play_shortcut_var = tk.StringVar(value=self.settings.keyboard_play_shortcut)
        self.keyboard_stop_shortcut_var = tk.StringVar(value=self.settings.keyboard_stop_shortcut)
        self.shortcut_lock_var = tk.BooleanVar(value=self.settings.shortcut_locked)
        self.midi_input_device_var = tk.StringVar(value=self.settings.midi_input_device)
        self.language_var = tk.StringVar(value=LANGUAGE_NAMES[self.language])
        self.language_menu_var = tk.StringVar(value=self.language)
        self.key_bindings = normalized_key_bindings(self.settings.key_bindings)
        self.position_var = tk.DoubleVar(value=0.0)
        self.last_midi_folder = self.settings.last_midi_folder
        self.duration_seconds = 0.0
        self.current_play_mode: str | None = None
        self.playback_id = 0
        self.position_dragging = False
        self.last_drag_seek_at = 0.0
        self.ignore_player_position_until = 0.0
        self.updating_position_from_player = False
        self.updating_channels = False
        self.updating_midi_selection = False
        self.seeking_keys = False
        self.player: MidiKeyboardPlayer | None = None
        self.sound_player: MidiSoundPlayer | None = None
        self.midi_input_bridge: MidiInputKeyboardBridge | None = None
        self.realtime_sound_output: RealtimeMidiSoundOutput | None = None
        self.midi_input_devices: list[tuple[int, str]] = []
        self.style = ttk.Style(self)
        self.section_heading_font = tkfont.nametofont("TkDefaultFont").copy()
        self.section_heading_font.configure(weight="bold")
        self.active_shortcut_sequences: list[str] = []
        self.hotkey_queue: queue.Queue[str] = queue.Queue()
        self.global_hotkeys: GlobalHotkeyManager | None = None
        self.hotkey_failure_signature: tuple[str, ...] = ()
        self.tray_icon: TrayIcon | None = None
        self.exiting = False
        self.settings_save_after_id: str | None = None
        self.settings_save_error = ""

        self._build_ui()
        if self.settings_load_error:
            self._log(self.settings_load_error)
        self._fit_window_width_to_key_settings()
        self.update_idletasks()
        icon_path = self._resource_path(APP_ICON_RELATIVE_PATH)
        icon_png_path = self._resource_path(APP_ICON_PNG_RELATIVE_PATH)
        self._apply_window_icon(icon_path, icon_png_path)
        self.tray_icon = TrayIcon(self.winfo_id(), self._text("title"), icon_path)
        try:
            self.tray_icon.install()
        except Exception as exc:
            self.tray_icon = None
            self.tray_resident_var.set(False)
            self._log(f"Task tray could not be initialized: {exc}")
        self.countdown_var.trace_add("write", self._on_countdown_changed)
        self.countdown_sound_var.trace_add("write", self._on_countdown_sound_changed)
        self.game_countdown_sound_var.trace_add("write", self._on_game_countdown_sound_changed)
        self.humanize_timing_var.trace_add("write", self._on_humanize_timing_changed)
        self.chord_optimization_var.trace_add("write", self._on_chord_optimization_changed)
        self.chord_strum_var.trace_add("write", self._on_chord_strum_changed)
        self.repeat_prevention_var.trace_add("write", self._on_repeat_prevention_changed)
        self.auto_fit_note_range_var.trace_add("write", self._on_auto_fit_note_range_changed)
        self.transpose_semitones_var.trace_add("write", self._on_note_shift_changed)
        self.octave_shift_var.trace_add("write", self._on_note_shift_changed)
        self.dry_run_var.trace_add("write", self._on_dry_run_changed)
        self.always_on_top_var.trace_add("write", self._on_always_on_top_changed)
        self.tray_resident_var.trace_add("write", self._on_tray_resident_changed)
        self.window_opacity_var.trace_add("write", self._on_window_opacity_changed)
        self.shortcut_lock_var.trace_add("write", self._on_shortcut_lock_changed)
        self._apply_theme()
        self._apply_always_on_top()
        self._apply_window_opacity()
        self._bind_keyboard_shortcuts()
        self._refresh_option_states()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Button-1>", self._on_app_pointer_down, add="+")
        self.bind("<Configure>", self._on_window_configure)
        self.after(60, self._drain_log_queue)
        self.after(100, self._drain_midi_duration_queue)
        self.after(30, self._drain_hotkey_queue)
        self.after(3000, self._ensure_keyboard_shortcuts)
        self.after(100, self._poll_tray_icon)
        self.after(100, self._poll_single_instance)
        self.after(0, self._load_saved_midi_folder)

    def _build_ui(self) -> None:
        self.title(self._text("title"))
        self._build_menu_bar()
        root = tk.Frame(self, padx=12, pady=12)
        self.root_frame = root
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=0)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(7, weight=1)

        playback_status = ttk.Frame(root)
        playback_status.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        playback_status.columnconfigure(1, weight=1)
        self.status_label = ttk.Label(playback_status, textvariable=self.state_var, anchor="w")
        self.status_label.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        self.position_title = ttk.Label(playback_status, anchor="w")
        self.position_title.grid(row=1, column=0, sticky="w", padx=(0, 6))
        self.position_slider = ttk.Scale(
            playback_status,
            from_=0,
            to=0,
            orient="horizontal",
            variable=self.position_var,
            command=self._on_position_slider_changed,
        )
        self.position_slider.grid(row=1, column=1, sticky="ew", padx=(0, 6))
        self.position_slider.bind("<ButtonPress-1>", self._on_position_pointer_down)
        self.position_slider.bind("<B1-Motion>", self._on_position_pointer_move)
        self.position_slider.bind("<ButtonRelease-1>", self._on_position_drag_end)
        self.position_label = ttk.Label(playback_status, text="00:00 / 00:00", width=15, anchor="e")
        self.position_label.grid(row=1, column=2, sticky="e")

        self.key_settings = ttk.LabelFrame(
            root,
            padding=(8, 8),
            style="PrimarySection.TLabelframe",
        )
        self.key_settings.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.key_settings.columnconfigure(2, weight=1)
        self.play_button = ttk.Button(
            self.key_settings,
            command=self.toggle_keyboard_playback,
            width=ACTION_BUTTON_WIDTH,
        )
        self.play_button.grid(
            row=0,
            column=0,
            rowspan=2,
            sticky="ns",
            padx=(0, 14),
        )
        self.countdown_label = ttk.Label(self.key_settings, width=12, anchor="e")
        self.countdown_label.grid(row=0, column=1, sticky="e", padx=(0, 6))
        self.countdown_settings = tk.Frame(self.key_settings, borderwidth=1, relief=tk.GROOVE, padx=6, pady=4)
        self.countdown_settings.grid(row=0, column=2, sticky="w")
        self.countdown_spinbox = ttk.Spinbox(
            self.countdown_settings,
            from_=0,
            to=10,
            textvariable=self.countdown_var,
            width=4,
        )
        self.countdown_spinbox.grid(
            row=0,
            column=0,
            padx=(0, 2),
        )
        self.countdown_unit_label = ttk.Label(self.countdown_settings, anchor="w")
        self.countdown_unit_label.grid(row=0, column=1, sticky="w", padx=(0, 6))
        self.countdown_sound_check = tk.Checkbutton(
            self.countdown_settings,
            variable=self.countdown_sound_var,
            anchor="w",
        )
        self.countdown_sound_check.grid(row=0, column=2, sticky="w", padx=(0, 6))
        self.game_countdown_sound_check = tk.Checkbutton(
            self.countdown_settings,
            variable=self.game_countdown_sound_var,
            anchor="w",
        )
        self.game_countdown_sound_check.grid(row=0, column=3, sticky="w")
        self.shortcut_label = ttk.Label(self.key_settings, anchor="e")
        self.shortcut_label.grid(row=0, column=3, sticky="e", padx=(10, 4))
        self.shortcut_settings = tk.Frame(self.key_settings, borderwidth=1, relief=tk.GROOVE, padx=6, pady=4)
        self.shortcut_settings.grid(row=0, column=4, sticky="e")
        self.keyboard_play_shortcut_label = ttk.Label(self.shortcut_settings, width=4, anchor="e")
        self.keyboard_play_shortcut_label.grid(row=0, column=0, sticky="e", padx=(0, 2))
        self.keyboard_play_shortcut_entry = ttk.Entry(
            self.shortcut_settings,
            textvariable=self.keyboard_play_shortcut_var,
            width=6,
            state="readonly",
        )
        self.keyboard_play_shortcut_entry.grid(row=0, column=1, sticky="w", padx=(0, 6))
        self.keyboard_stop_shortcut_label = ttk.Label(self.shortcut_settings, width=4, anchor="e")
        self.keyboard_stop_shortcut_label.grid(row=0, column=2, sticky="e", padx=(0, 2))
        self.keyboard_stop_shortcut_entry = ttk.Entry(
            self.shortcut_settings,
            textvariable=self.keyboard_stop_shortcut_var,
            width=6,
            state="readonly",
        )
        self.keyboard_stop_shortcut_entry.grid(row=0, column=3, sticky="w")
        self.keyboard_play_shortcut_entry.bind("<KeyPress>", self._on_play_shortcut_key_pressed)
        self.keyboard_stop_shortcut_entry.bind("<KeyPress>", self._on_stop_shortcut_key_pressed)
        self.shortcut_lock_check = tk.Checkbutton(
            self.shortcut_settings,
            variable=self.shortcut_lock_var,
            anchor="w",
        )
        self.shortcut_lock_check.grid(row=0, column=4, sticky="w", padx=(6, 0))
        self._refresh_shortcut_lock_state()

        self.midi_input_settings = ttk.LabelFrame(
            root,
            padding=(8, 8),
            style="PrimarySection.TLabelframe",
        )
        self.midi_input_settings.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.midi_input_settings.columnconfigure(2, weight=1)
        self.midi_input_button = ttk.Button(
            self.midi_input_settings,
            command=self.toggle_midi_input,
            width=ACTION_BUTTON_WIDTH,
        )
        self.midi_input_button.grid(row=0, column=0, padx=(0, 14))
        self.midi_input_device_label = ttk.Label(self.midi_input_settings, width=12, anchor="e")
        self.midi_input_device_label.grid(row=0, column=1, sticky="e", padx=(0, 6))
        self.midi_input_select = ttk.Combobox(
            self.midi_input_settings,
            textvariable=self.midi_input_device_var,
            values=[],
            state="readonly",
            width=36,
        )
        self.midi_input_select.grid(row=0, column=2, sticky="ew", padx=(0, 8))
        self.midi_input_select.bind("<<ComboboxSelected>>", self._on_midi_input_device_changed)
        self.refresh_midi_inputs_button = ttk.Button(
            self.midi_input_settings,
            command=self._refresh_midi_input_devices,
            width=10,
        )
        self.refresh_midi_inputs_button.grid(row=0, column=3)

        self.sound_settings = ttk.LabelFrame(
            root,
            padding=10,
            style="PrimarySection.TLabelframe",
        )
        self.sound_settings.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.sound_settings.columnconfigure(3, weight=1)
        self.dry_run_check = tk.Checkbutton(self.sound_settings, variable=self.dry_run_var, anchor="w")
        self.dry_run_check.grid(row=0, column=0, sticky="w", padx=(0, 14))
        self.auto_fit_note_range_check = tk.Checkbutton(
            self.sound_settings,
            variable=self.auto_fit_note_range_var,
            anchor="w",
        )
        self.auto_fit_note_range_check.grid(row=0, column=1, sticky="w", padx=(0, 14))
        sound_controls = ttk.Frame(self.sound_settings)
        sound_controls.grid(row=0, column=3, sticky="ew")
        sound_controls.columnconfigure(1, weight=1)
        self.sound_volume_title = ttk.Label(
            sound_controls,
            width=self._sound_volume_label_width(),
            anchor=self._sound_volume_label_anchor(),
        )
        self.sound_volume_title.grid(row=0, column=0, sticky="w", padx=(0, self._sound_volume_label_padx()))
        self.sound_volume = ttk.Scale(
            sound_controls,
            from_=0,
            to=100,
            orient="horizontal",
            variable=self.sound_volume_var,
            command=self._on_sound_volume_changed,
        )
        self.sound_volume.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        self.sound_volume.bind("<ButtonPress-1>", self._on_sound_volume_pointer)
        self.sound_volume.bind("<B1-Motion>", self._on_sound_volume_pointer)
        self.sound_volume_label = ttk.Label(
            sound_controls,
            text=f"{self.sound_volume_var.get()}%",
            width=5,
            anchor="e",
        )
        self.sound_volume_label.grid(row=0, column=2, sticky="e")
        self.repeat_prevention_check = tk.Checkbutton(
            self.sound_settings,
            variable=self.repeat_prevention_var,
            anchor="w",
        )
        self.repeat_prevention_check.grid(
            row=0,
            column=2,
            sticky="w",
            padx=(0, 14),
        )
        self.performance_optimization_settings = tk.Frame(
            self.sound_settings,
            borderwidth=1,
            relief=tk.GROOVE,
            padx=6,
            pady=4,
        )
        self.performance_optimization_settings.grid(
            row=1,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(8, 0),
        )
        self.humanize_timing_check = tk.Checkbutton(
            self.performance_optimization_settings,
            variable=self.humanize_timing_var,
            anchor="w",
        )
        self.humanize_timing_check.grid(row=0, column=0, sticky="w", padx=(0, 14))
        self.chord_strum_check = tk.Checkbutton(
            self.performance_optimization_settings,
            variable=self.chord_strum_var,
            anchor="w",
        )
        self.chord_strum_check.grid(row=0, column=1, sticky="w", padx=(0, 14))
        self.chord_optimization_control = tk.Frame(
            self.performance_optimization_settings,
            borderwidth=0,
            relief=tk.FLAT,
        )
        self.chord_optimization_control.grid(row=0, column=2, sticky="w")
        self.chord_optimization_check = tk.Checkbutton(
            self.chord_optimization_control,
            variable=self.chord_optimization_var,
            text="",
            padx=0,
            pady=0,
        )
        self.chord_optimization_check.pack(side=tk.LEFT)
        self.chord_optimization_label = tk.Label(
            self.chord_optimization_control,
            anchor="w",
            padx=2,
            pady=1,
        )
        self.chord_optimization_label.pack(side=tk.LEFT, fill=tk.Y)
        self.chord_optimization_control.bind(
            "<Button-1>",
            self._toggle_chord_optimization,
        )
        self.chord_optimization_label.bind(
            "<Button-1>",
            self._toggle_chord_optimization,
        )
        note_shift_controls = ttk.Frame(self.sound_settings)
        note_shift_controls.grid(
            row=2,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(8, 0),
        )
        self.transpose_semitones_label = ttk.Label(note_shift_controls, anchor="e")
        self.transpose_semitones_label.grid(row=0, column=0, sticky="e", padx=(0, 6))
        self.transpose_semitones_spinbox = ttk.Spinbox(
            note_shift_controls,
            from_=MIN_TRANSPOSE_SEMITONES,
            to=MAX_TRANSPOSE_SEMITONES,
            textvariable=self.transpose_semitones_var,
            width=4,
        )
        self.transpose_semitones_spinbox.grid(row=0, column=1, sticky="w", padx=(0, 18))
        self.transpose_semitones_label.bind("<Double-Button-1>", self._reset_transpose_semitones)
        self.octave_shift_label = ttk.Label(note_shift_controls, anchor="e")
        self.octave_shift_label.grid(row=0, column=2, sticky="e", padx=(0, 6))
        self.octave_shift_spinbox = ttk.Spinbox(
            note_shift_controls,
            from_=MIN_OCTAVE_SHIFT,
            to=MAX_OCTAVE_SHIFT,
            textvariable=self.octave_shift_var,
            width=4,
        )
        self.octave_shift_spinbox.grid(row=0, column=3, sticky="w")
        self.octave_shift_label.bind("<Double-Button-1>", self._reset_octave_shift)
        speed_controls = ttk.Frame(self.sound_settings)
        speed_controls.grid(
            row=1,
            column=3,
            sticky="ew",
            pady=(8, 0),
        )
        speed_controls.columnconfigure(1, weight=1)
        self.playback_speed_title = ttk.Label(
            speed_controls,
            width=self._sound_volume_label_width(),
            anchor=self._sound_volume_label_anchor(),
        )
        self.playback_speed_title.grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, self._sound_volume_label_padx()),
        )
        self.playback_speed_title.bind("<Double-Button-1>", self._reset_playback_speed)
        self.playback_speed = ttk.Scale(
            speed_controls,
            from_=MIN_PLAYBACK_SPEED_PERCENT,
            to=MAX_PLAYBACK_SPEED_PERCENT,
            orient="horizontal",
            variable=self.playback_speed_var,
            command=self._on_playback_speed_changed,
        )
        self.playback_speed.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        self.playback_speed.bind("<ButtonPress-1>", self._on_playback_speed_pointer)
        self.playback_speed.bind("<B1-Motion>", self._on_playback_speed_pointer)
        self.playback_speed_label = ttk.Label(
            speed_controls,
            text=f"{self.playback_speed_var.get()}%",
            width=5,
            anchor="e",
        )
        self.playback_speed_label.grid(row=0, column=2, sticky="e")

        self.channel_box = tk.Frame(
            root,
            borderwidth=1,
            relief=tk.GROOVE,
            padx=0,
            pady=0,
        )
        self.channel_box.configure(width=CHANNEL_PANE_WIDTH)
        self.channel_box.grid(row=7, column=0, sticky="nsw", padx=(0, 4), pady=(12, 0))
        self.channel_box.grid_propagate(False)
        self.channel_canvas = tk.Canvas(
            self.channel_box,
            width=CHANNEL_PANE_WIDTH - 2,
            borderwidth=0,
            highlightthickness=0,
        )
        self.channel_frame = tk.Frame(self.channel_canvas)
        self.channel_canvas_window = self.channel_canvas.create_window(
            (0, 0),
            window=self.channel_frame,
            anchor="nw",
        )
        self.channel_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.channel_frame.bind("<Configure>", self._on_channel_frame_configure)
        self.channel_canvas.bind("<Configure>", self._on_channel_canvas_configure)
        self.channel_canvas.bind("<MouseWheel>", self._on_channel_mousewheel)
        self._set_channels(())

        self.detail_tabs = ttk.Notebook(root, style="Borderless.TNotebook")
        self.detail_tabs.grid(row=7, column=1, sticky="nsew", pady=(12, 0))

        self.midi_list_tab = ttk.Frame(self.detail_tabs, padding=0)
        self.midi_list_tab.rowconfigure(0, weight=1)
        self.midi_list_tab.columnconfigure(0, weight=1)
        self.midi_tree = ttk.Treeview(
            self.midi_list_tab,
            columns=MIDI_LIST_COLUMNS,
            show="tree headings",
            selectmode="browse",
        )
        self.midi_tree.heading("#0", text=self._text("name"), anchor="w")
        self.midi_tree.heading("duration", text=self._text("duration"), anchor="w")
        self.midi_tree.heading("note_range", text=self._text("note_range"), anchor="w")
        self.midi_tree.column("#0", width=200, minwidth=120, stretch=True, anchor="w")
        self.midi_tree.column("duration", width=80, minwidth=70, stretch=False, anchor="w")
        self.midi_tree.column("note_range", width=90, minwidth=75, stretch=False, anchor="w")
        self.midi_tree.grid(row=0, column=0, sticky="nsew")
        self.midi_scrollbar = ttk.Scrollbar(
            self.midi_list_tab,
            orient="vertical",
            command=self.midi_tree.yview,
            style="MidiList.Vertical.TScrollbar",
        )
        self.midi_tree.configure(yscrollcommand=self.midi_scrollbar.set)
        self.midi_tree.bind("<<TreeviewSelect>>", self._on_midi_selected)
        self.midi_tree.bind("<Double-1>", self._on_midi_double_click)
        self.after_idle(self._align_midi_scrollbar)

        self.log_tab = ttk.Frame(self.detail_tabs, padding=0)
        self.log_tab.rowconfigure(0, weight=1)
        self.log_tab.columnconfigure(0, weight=1)
        self.log_text = tk.Text(
            self.log_tab,
            wrap="none",
            height=18,
            state="disabled",
            borderwidth=0,
            highlightthickness=0,
            relief=tk.FLAT,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.reload_tab = ttk.Frame(self.detail_tabs)
        self.detail_tabs.add(self.reload_tab, text="\u21bb", padding=(5, 2))
        self.detail_tabs.add(
            self.midi_list_tab,
            text=self._text("midi_list"),
        )
        self.detail_tabs.add(self.log_tab, text=self._text("playback_log"))
        self.detail_tabs.select(self.midi_list_tab)
        self.detail_tabs.bind("<Button-1>", self._on_detail_tab_pointer, add="+")
        self._refresh_text()
        self._refresh_midi_input_devices()

    def _build_menu_bar(self) -> None:
        menu_bar = tk.Menu(self, tearoff=False)

        midi_menu = tk.Menu(menu_bar, tearoff=False)
        midi_menu.add_command(
            label=self._text("load_midi"),
            command=self.load_midi_folder,
        )
        midi_menu.add_separator()
        midi_menu.add_command(
            label=self._text("exit"),
            command=self._exit_app,
        )
        menu_bar.add_cascade(label=self._text("menu_midi"), menu=midi_menu)

        opacity_menu = tk.Menu(menu_bar, tearoff=False)
        for opacity in (100, 90, 80, 70, 60, 50, 40, 30):
            opacity_menu.add_radiobutton(
                label=f"{opacity}%",
                variable=self.window_opacity_var,
                value=opacity,
                command=lambda value=opacity: self._set_window_opacity(value),
            )

        view_menu = tk.Menu(menu_bar, tearoff=False)
        view_menu.add_cascade(label=self._text("window_opacity"), menu=opacity_menu)
        view_menu.add_separator()
        view_menu.add_checkbutton(
            label=self._text("always_on_top"),
            variable=self.always_on_top_var,
            command=self._on_always_on_top_changed,
        )
        menu_bar.add_cascade(label=self._text("menu_view"), menu=view_menu)

        theme_menu = tk.Menu(menu_bar, tearoff=False)
        for code, label in COLOR_THEME_NAMES[self.language].items():
            theme_menu.add_radiobutton(
                label=label,
                variable=self.color_theme_menu_var,
                value=code,
                command=lambda value=code: self._set_color_theme(value),
            )

        language_menu = tk.Menu(menu_bar, tearoff=False)
        for code, label in LANGUAGE_NAMES.items():
            language_menu.add_radiobutton(
                label=label,
                variable=self.language_menu_var,
                value=code,
                command=lambda value=code: self._set_language(value),
            )

        settings_menu = tk.Menu(menu_bar, tearoff=False)
        settings_menu.add_cascade(label=self._text("color_theme"), menu=theme_menu)
        settings_menu.add_cascade(label=self._text("language"), menu=language_menu)
        settings_menu.add_command(
            label=self._text("key_bindings"),
            command=self._show_key_bindings_window,
        )
        settings_menu.add_separator()
        settings_menu.add_checkbutton(
            label=self._text("tray_resident"),
            variable=self.tray_resident_var,
            command=self._on_tray_resident_changed,
        )
        menu_bar.add_cascade(label=self._text("menu_settings"), menu=settings_menu)

        other_menu = tk.Menu(menu_bar, tearoff=False)
        other_menu.add_command(
            label=self._text("about_app"),
            command=self._show_about_window,
        )
        menu_bar.add_cascade(label=self._text("menu_other"), menu=other_menu)

        self.menu_bar = menu_bar
        self.midi_menu = midi_menu
        self.opacity_menu = opacity_menu
        self.view_menu = view_menu
        self.theme_menu = theme_menu
        self.language_menu_widget = language_menu
        self.settings_menu = settings_menu
        self.other_menu = other_menu
        self.configure(menu=menu_bar)

    def _show_about_window(self) -> None:
        existing = self.__dict__.get("about_window")
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return

        about_window = tk.Toplevel(self)
        self.about_window = about_window
        about_window.title(self._text("about_title"))
        about_window.transient(self)
        about_window.resizable(False, False)

        content = ttk.Frame(about_window, padding=(18, 16))
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        about_window.columnconfigure(0, minsize=260)
        title_label = ttk.Label(
            content,
            text=APP_WINDOW_TITLE,
            anchor="center",
            font=("Segoe UI", 11, "bold"),
        )
        title_label.grid(row=0, column=0, sticky="ew")
        version_label = ttk.Label(
            content,
            text=f"{self._text('version')}: {APP_VERSION}",
            anchor="center",
        )
        version_label.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        copyright_label = ttk.Label(content, text=APP_COPYRIGHT, anchor="center")
        copyright_label.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        repository_button = ttk.Button(
            content,
            text="GitHub",
            width=14,
            command=lambda: webbrowser.open(APP_REPOSITORY_URL),
        )
        repository_button.grid(row=3, column=0, pady=(14, 0))
        close_button = ttk.Button(
            content,
            text=self._text("close"),
            width=14,
            command=about_window.destroy,
        )
        close_button.grid(row=4, column=0, pady=(8, 0))

        about_window.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - about_window.winfo_width()) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - about_window.winfo_height()) // 2)
        about_window.geometry(f"+{x}+{y}")

    def _show_key_bindings_window(self) -> None:
        existing = self.__dict__.get("key_bindings_window")
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return

        window = tk.Toplevel(self)
        self.key_bindings_window = window
        self.key_binding_vars: dict[int, tk.StringVar] = {}
        self.key_binding_entries: dict[int, ttk.Entry] = {}
        key_bindings = self._current_key_bindings()
        window.title(self._text("key_bindings"))
        window.transient(self)
        window.resizable(False, False)

        content = ttk.Frame(window, padding=(14, 12))
        content.grid(row=0, column=0, sticky="nsew")

        for octave_index, octave in enumerate((3, 4, 5)):
            group = ttk.LabelFrame(content, text=f"{self._text('octave')} {octave}", padding=(8, 6))
            group.grid(row=0, column=octave_index, sticky="n", padx=(0 if octave_index == 0 else 8, 0))
            for row, semitone in enumerate(range(12)):
                note = (octave + 1) * 12 + semitone
                note_label = ttk.Label(group, text=self._format_midi_note(note), width=4, anchor="e")
                note_label.grid(row=row, column=0, sticky="e", padx=(0, 4), pady=1)
                key_var = tk.StringVar(value=key_bindings[note])
                self.key_binding_vars[note] = key_var
                key_entry = ttk.Entry(
                    group,
                    textvariable=key_var,
                    state="readonly",
                    width=7,
                )
                self.key_binding_entries[note] = key_entry
                key_entry.grid(row=row, column=1, sticky="w", pady=1)
                key_entry.bind("<KeyPress>", self._on_key_binding_key_pressed)
                key_entry.bind("<FocusIn>", lambda event: event.widget.selection_range(0, tk.END))

        button_row = ttk.Frame(content)
        button_row.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        button_row.columnconfigure(0, weight=1)
        reset_button = ttk.Button(
            button_row,
            text=self._text("restore_default_key_bindings"),
            command=self._reset_key_bindings_to_default,
        )
        reset_button.grid(row=0, column=0, sticky="w")
        close_button = ttk.Button(
            button_row,
            text=self._text("close"),
            command=window.destroy,
            width=10,
        )
        close_button.grid(row=0, column=1, sticky="e")
        self._refresh_key_binding_duplicate_styles()

        window.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - window.winfo_width()) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - window.winfo_height()) // 2)
        window.geometry(f"+{x}+{y}")

    def _refresh_key_binding_window_values(self) -> None:
        variables = self.__dict__.get("key_binding_vars")
        if not variables:
            return
        for note, variable in variables.items():
            variable.set(self._current_key_bindings()[note])
        self._refresh_key_binding_duplicate_styles()

    def _on_key_binding_key_pressed(self, event: tk.Event) -> str:
        note = None
        for candidate_note, entry in self.__dict__.get("key_binding_entries", {}).items():
            if entry is event.widget:
                note = candidate_note
                break
        if note is None:
            return "break"

        key = self._key_binding_from_event(event)
        if key is not None:
            self._set_key_binding(note, key)
        return "break"

    @staticmethod
    def _key_binding_from_event(event: tk.Event) -> str | None:
        key_aliases = {
            "space": "space",
            "bracketleft": "[",
            "bracketright": "]",
        }
        keysym = str(getattr(event, "keysym", ""))
        key = key_aliases.get(keysym)
        if key is None:
            char = str(getattr(event, "char", ""))
            if len(char) == 1 and char.isprintable():
                key = char.lower()
            elif len(keysym) == 1:
                key = keysym.lower()
        if key in SUPPORTED_BINDING_KEYS:
            return key
        return None

    def _refresh_key_binding_duplicate_styles(self) -> None:
        entries = self.__dict__.get("key_binding_entries")
        if not entries:
            return
        key_counts: dict[str, int] = {}
        key_bindings = self._current_key_bindings()
        for key in key_bindings.values():
            key_counts[key] = key_counts.get(key, 0) + 1
        for note, entry in entries.items():
            style = (
                "DuplicateKeyBinding.TEntry"
                if key_counts.get(key_bindings[note], 0) > 1
                else "TEntry"
            )
            entry.configure(style=style)

    def _on_detail_tab_pointer(self, event: tk.Event) -> str | None:
        try:
            clicked_tab = self.detail_tabs.index(f"@{event.x},{event.y}")
            reload_tab = self.detail_tabs.index(self.reload_tab)
        except tk.TclError:
            return None
        if clicked_tab != reload_tab:
            return None
        self.reload_midi_folder()
        return "break"

    def _align_midi_scrollbar(self, _event: tk.Event | None = None) -> None:
        if not self.midi_tree.winfo_exists():
            return
        heading_seen = False
        heading_bottom = 0
        for y in range(min(self.midi_tree.winfo_height(), 80)):
            region = self.midi_tree.identify_region(1, y)
            if region == "heading":
                heading_seen = True
            elif heading_seen:
                heading_bottom = y
                break
        if heading_bottom <= 0:
            return
        if self.__dict__.get("_midi_scrollbar_heading_bottom") == heading_bottom:
            return
        self._midi_scrollbar_heading_bottom = heading_bottom
        self.midi_scrollbar.place(
            relx=1.0,
            x=0,
            y=heading_bottom,
            anchor="ne",
            relheight=1.0,
            height=-heading_bottom,
        )
        self.midi_scrollbar.lift()

    def _fit_window_width_to_key_settings(self) -> None:
        self.update_idletasks()
        screen_limit = max(MIN_WINDOW_WIDTH, self.winfo_screenwidth() - 80)
        window_width = max(MIN_WINDOW_WIDTH, min(DEFAULT_WINDOW_WIDTH, screen_limit))
        window_height = max(self.saved_window_height, self.winfo_height(), MIN_WINDOW_HEIGHT)
        self.minsize(window_width, MIN_WINDOW_HEIGHT)
        self.geometry(f"{window_width}x{window_height}")

    def load_midi_folder(self) -> None:
        folder = filedialog.askdirectory(
            title=self._text("select_midi_file"),
        )
        if not folder:
            return

        self._load_midi_folder(
            Path(folder),
            save_folder=True,
            show_empty_message=True,
            preserve_sound_playback=False,
        )

    def reload_midi_folder(self) -> None:
        if not self.last_midi_folder:
            messagebox.showinfo(self._text("no_midi_title"), self._text("load_midi_first"))
            return
        folder_path = Path(self.last_midi_folder)
        if not folder_path.is_dir():
            messagebox.showinfo(self._text("no_midi_title"), self._text("no_midi_files"))
            return
        self._load_midi_folder(
            folder_path,
            save_folder=False,
            show_empty_message=True,
            preserve_sound_playback=True,
        )

    def _load_saved_midi_folder(self) -> None:
        if not self.last_midi_folder:
            return
        folder_path = Path(self.last_midi_folder)
        if folder_path.is_dir():
            self._load_midi_folder(
                folder_path,
                save_folder=False,
                show_empty_message=False,
                preserve_sound_playback=False,
            )

    def _load_midi_folder(
        self,
        folder_path: Path,
        save_folder: bool,
        show_empty_message: bool,
        preserve_sound_playback: bool = False,
    ) -> None:
        if not preserve_sound_playback and self.current_play_mode is not None:
            self.stop(wait=True)

        try:
            self.midi_files = sorted(
                [
                    path
                    for path in folder_path.iterdir()
                    if path.is_file() and path.suffix.lower() in {".mid", ".midi"}
                ],
                key=lambda path: path.name.lower(),
            )
        except OSError as exc:
            messagebox.showerror(self._text("load_failed_title"), str(exc))
            return
        sound_playing = preserve_sound_playback and self._sound_playback_is_active()
        self.midi_note_range_labels = {path: "--" for path in self.midi_files}
        self.midi_duration_labels = {path: "--:--" for path in self.midi_files}
        self._populate_midi_list()
        self._start_midi_duration_scan(self.midi_files)
        self._clear_log()
        self._log(self._text("folder_loaded_log").format(folder=str(folder_path), count=len(self.midi_files)))
        if save_folder:
            self.last_midi_folder = str(folder_path)
            self._save_current_settings()

        if not self.midi_files:
            if not sound_playing:
                self.events = []
                self.summary = None
                self.duration_seconds = 0.0
                self.position_slider.configure(to=0)
                self._set_position(0.0)
                self._set_channels(())
                self.state_var.set(self._text("waiting"))
            if show_empty_message:
                messagebox.showinfo(self._text("no_midi_title"), self._text("no_midi_files"))
            return

        if sound_playing:
            if self.summary is not None:
                self._select_midi_path(self.summary.path)
            self.detail_tabs.select(self.midi_list_tab)
            return

        first_item = self.midi_tree.get_children()[0]
        self.midi_tree.selection_set(first_item)
        self.midi_tree.focus(first_item)
        self._on_midi_selected(None)
        self.detail_tabs.select(self.midi_list_tab)

    def _select_midi_path(self, target_path: Path) -> bool:
        target_name = target_path.name
        for index, path in enumerate(self.midi_files):
            if path == target_path or path.name == target_name:
                item = str(index)
                self.updating_midi_selection = True
                self.midi_tree.selection_set(item)
                self.midi_tree.focus(item)
                self.after_idle(self._finish_midi_selection_update)
                return True
        return False

    def _finish_midi_selection_update(self) -> None:
        self.updating_midi_selection = False

    def _load_midi_file(self, path: Path, stop_playback: bool = True) -> bool:
        if stop_playback and self.current_play_mode is not None:
            self.stop(wait=True)

        try:
            self.events, self.summary = parse_midi(path)
        except Exception as exc:
            messagebox.showerror(self._text("load_failed_title"), str(exc))
            return False

        self._set_channels(self.summary.channels)
        self.duration_seconds = self.summary.duration
        self.position_slider.configure(to=max(0.0, self.duration_seconds))
        self._set_position(0.0)
        channels = ", ".join(str(channel + 1) for channel in self.summary.channels) or self._text("none")
        self._log(
            self._text("loaded_log").format(
                name=path.name,
                event_count=self.summary.event_count,
                duration=self.summary.duration,
                channels=channels,
            )
        )
        return True

    def _populate_midi_list(self) -> None:
        for item in self.midi_tree.get_children():
            self.midi_tree.delete(item)

        for index, path in enumerate(self.midi_files):
            self.midi_tree.insert(
                "",
                "end",
                iid=str(index),
                text=path.name,
                values=(
                    self.midi_duration_labels.get(path, ""),
                    self.midi_note_range_labels.get(path, ""),
                ),
            )

    def _read_midi_list_labels(self, path: Path) -> tuple[str, str]:
        try:
            _events, summary = parse_midi(path)
        except Exception:
            return "--", "--:--"
        return (
            self._format_note_range(summary.note_range),
            self._format_time(summary.duration),
        )

    def _start_midi_duration_scan(self, paths: list[Path]) -> None:
        self.midi_duration_scan_cancel.set()
        self.midi_duration_scan_id += 1
        scan_id = self.midi_duration_scan_id
        cancel_event = threading.Event()
        self.midi_duration_scan_cancel = cancel_event

        def scan() -> None:
            for path in paths:
                if cancel_event.is_set():
                    return
                note_range_label, duration_label = self._read_midi_list_labels(path)
                self.midi_duration_queue.put(
                    (scan_id, path, note_range_label, duration_label)
                )

        threading.Thread(target=scan, daemon=True).start()

    def _drain_midi_duration_queue(self) -> None:
        while True:
            try:
                scan_id, path, note_range_label, duration_label = (
                    self.midi_duration_queue.get_nowait()
                )
            except queue.Empty:
                break
            if scan_id != self.midi_duration_scan_id:
                continue
            try:
                index = self.midi_files.index(path)
            except ValueError:
                continue
            self.midi_note_range_labels[path] = note_range_label
            self.midi_duration_labels[path] = duration_label
            item = str(index)
            if self.midi_tree.exists(item):
                self.midi_tree.set(item, "note_range", note_range_label)
                self.midi_tree.set(item, "duration", duration_label)
        if not self.exiting:
            self.after(100, self._drain_midi_duration_queue)

    def _on_midi_selected(self, _event: tk.Event) -> None:
        if self.updating_midi_selection:
            return

        selection = self.midi_tree.selection()
        if not selection:
            return

        index = int(selection[0])
        if 0 <= index < len(self.midi_files):
            selected_path = self.midi_files[index]
            switch_sound = (
                self.current_play_mode == "sound"
                and self.sound_player is not None
                and self.sound_player.is_playing
            )
            if switch_sound and self.summary is not None and selected_path == self.summary.path:
                return
            if self._load_midi_file(selected_path, stop_playback=not switch_sound) and self.summary:
                note_range_label = self._format_note_range(self.summary.note_range)
                duration_label = self._format_time(self.summary.duration)
                self.midi_note_range_labels[selected_path] = note_range_label
                self.midi_duration_labels[selected_path] = duration_label
                self.midi_tree.set(selection[0], "note_range", note_range_label)
                self.midi_tree.set(selection[0], "duration", duration_label)
                if switch_sound and self.sound_player:
                    self.sound_player.switch(self.events, start_time=0.0)

    def _on_midi_double_click(self, _event: tk.Event) -> None:
        if self.summary is not None:
            self.toggle_midi_playback()

    def toggle_keyboard_playback(self) -> None:
        if self.current_play_mode == "keys":
            self.stop()
        elif self.current_play_mode is None and not self._midi_input_is_running():
            self.play()

    def toggle_midi_playback(self) -> None:
        if self.current_play_mode == "sound":
            self.stop()
        elif self.current_play_mode is None:
            self.play_sound()

    def toggle_midi_input(self) -> None:
        if self.midi_input_bridge and self.midi_input_bridge.is_running:
            self.stop_midi_input()
        else:
            self.start_midi_input()

    def start_midi_input(self) -> None:
        if self.current_play_mode == "keys":
            return
        if self.midi_input_bridge and self.midi_input_bridge.is_running:
            return
        selected = self.midi_input_device_var.get()
        device_id = self._selected_midi_input_device_id()
        if device_id is None:
            messagebox.showinfo(self._text("no_midi_title"), self._text("no_midi_input_devices"))
            return

        test_mode = self.dry_run_var.get()
        output = KeyboardOutput(dry_run=test_mode)
        transpose_semitones, octave_shift = self._note_shift_values()
        self._close_realtime_sound_output()
        self.realtime_sound_output = RealtimeMidiSoundOutput(
            volume=self.sound_volume_var.get(),
            log=lambda message: self.log_queue.put(message),
            transpose_semitones=transpose_semitones,
            octave_shift=octave_shift,
            repeat_prevention=self.repeat_prevention_var.get(),
        )
        self.realtime_sound_output.set_enabled(test_mode)
        self.midi_input_bridge = MidiInputKeyboardBridge(
            device_id=device_id,
            output=output,
            log=lambda message: self.log_queue.put(message),
            on_state=lambda state: self.log_queue.put(f"__MIDI_INPUT_STATE__{state}"),
            on_midi_message=self.realtime_sound_output.process_message,
            auto_fit_note_range=self.auto_fit_note_range_var.get(),
            transpose_semitones=transpose_semitones,
            octave_shift=octave_shift,
            repeat_prevention=self.repeat_prevention_var.get(),
            key_bindings=self._current_key_bindings(),
        )
        try:
            self.midi_input_bridge.start()
            self.midi_input_device_var.set(selected)
            self._save_current_settings()
            self._refresh_playback_buttons()
            self._refresh_midi_input_button()
            self._refresh_option_states()
        except Exception as exc:
            self.midi_input_bridge = None
            self._close_realtime_sound_output()
            self._refresh_midi_input_button()
            self._refresh_option_states()
            messagebox.showwarning(self._text("load_failed_title"), str(exc))

    def stop_midi_input(self) -> None:
        if self.midi_input_bridge:
            self.midi_input_bridge.stop()
            self.midi_input_bridge = None
        self._close_realtime_sound_output()
        self._refresh_playback_buttons()
        self._refresh_midi_input_button()
        self._refresh_option_states()

    def _refresh_midi_input_devices(self) -> None:
        previous = self.midi_input_device_var.get()
        self.midi_input_devices = list_midi_input_devices()
        names = [name for _device_id, name in self.midi_input_devices]
        self.midi_input_select.configure(values=names)
        if previous in names:
            self.midi_input_device_var.set(previous)
        elif names:
            self.midi_input_device_var.set(names[0])
        else:
            self.midi_input_device_var.set("")
        self._save_current_settings()

    def _on_midi_input_device_changed(self, *_args: object) -> None:
        self._save_current_settings()

    def _selected_midi_input_device_id(self) -> int | None:
        selected = self.midi_input_device_var.get()
        for device_id, name in self.midi_input_devices:
            if name == selected:
                return device_id
        return None

    def play(self) -> None:
        if self.current_play_mode is not None or self._midi_input_is_running():
            return
        if not self.events:
            messagebox.showinfo(self._text("no_midi_title"), self._text("load_midi_first"))
            return

        events = self.events
        if not self._has_enabled_events(events):
            messagebox.showinfo(self._text("no_events_title"), self._text("no_events_enabled"))
            return

        start_time = self._play_start_position()
        self.ignore_player_position_until = 0.0
        output = KeyboardOutput(dry_run=self.dry_run_var.get())
        playback_id = self._next_playback_id()
        transpose_semitones, octave_shift = self._note_shift_values()
        self.player = MidiKeyboardPlayer(
            output=output,
            log=lambda message: self.log_queue.put(message),
            on_state=lambda state, pid=playback_id: self.log_queue.put(f"__STATE__{pid}__{state}"),
            on_position=lambda position, pid=playback_id: self.log_queue.put(f"__POSITION__{pid}__{position}"),
            on_optimization_progress=lambda progress, pid=playback_id: self.log_queue.put(
                f"__OPTIMIZATION__{pid}__{'done' if progress is None else progress}"
            ),
            enabled_channels=self._enabled_channels,
            enabled_sources=self._enabled_sources,
            auto_fit_note_range=self.auto_fit_note_range_var.get(),
            transpose_semitones=transpose_semitones,
            octave_shift=octave_shift,
            humanize_timing=self.humanize_timing_var.get(),
            chord_optimization=self.chord_optimization_var.get(),
            chord_strum=self.chord_strum_var.get(),
            repeat_prevention=self.repeat_prevention_var.get(),
            playback_speed_percent=self.playback_speed_var.get(),
            key_bindings=self._current_key_bindings(),
        )
        try:
            self.current_play_mode = "keys"
            self._refresh_playback_buttons()
            self._refresh_midi_input_button()
            self._refresh_option_states()
            mode = self._text("dry_run_mode") if self.dry_run_var.get() else self._text("real_keyboard_output")
            self._log(self._text("key_playback_started").format(mode=mode))
            self.player.play_with_countdown_sound(
                events,
                countdown_seconds=max(0, self.countdown_var.get()),
                start_time=start_time,
                on_countdown_tick=self._play_countdown_tick if self._countdown_tick_enabled() else None,
            )
        except RuntimeError as exc:
            self.current_play_mode = None
            self._refresh_playback_buttons()
            self._refresh_midi_input_button()
            self._refresh_option_states()
            messagebox.showwarning(self._text("already_playing_title"), str(exc))

    def play_sound(self) -> None:
        if self.current_play_mode is not None:
            return
        if self.summary is None:
            messagebox.showinfo(self._text("no_midi_title"), self._text("load_midi_first"))
            return

        start_time = self._play_start_position()
        self.ignore_player_position_until = 0.0
        playback_id = self._next_playback_id()
        transpose_semitones, octave_shift = self._note_shift_values()
        self.sound_player = MidiSoundPlayer(
            log=lambda message: self.log_queue.put(message),
            on_state=lambda state, pid=playback_id: self.log_queue.put(f"__SOUND_STATE__{pid}__{state}"),
            on_position=lambda position, pid=playback_id: self.log_queue.put(f"__POSITION__{pid}__{position}"),
            on_optimization_progress=lambda progress, pid=playback_id: self.log_queue.put(
                f"__OPTIMIZATION__{pid}__{'done' if progress is None else progress}"
            ),
            enabled_channels=self._enabled_channels,
            enabled_sources=self._enabled_sources,
            volume=self.sound_volume_var.get(),
            auto_fit_note_range=self.auto_fit_note_range_var.get(),
            transpose_semitones=transpose_semitones,
            octave_shift=octave_shift,
            humanize_timing=self.humanize_timing_var.get(),
            chord_optimization=self.chord_optimization_var.get(),
            chord_strum=self.chord_strum_var.get(),
            repeat_prevention=self.repeat_prevention_var.get(),
            playback_speed_percent=self.playback_speed_var.get(),
        )
        try:
            self.current_play_mode = "sound"
            self._refresh_playback_buttons()
            self.sound_player.play(self.events, start_time=start_time)
        except RuntimeError as exc:
            self.current_play_mode = None
            self._refresh_playback_buttons()
            messagebox.showwarning(self._text("already_playing_title"), str(exc))

    def stop(self, wait: bool = False) -> None:
        self._next_playback_id()
        self.ignore_player_position_until = time.perf_counter() + 1.0
        player = self.player
        sound_player = self.sound_player
        stopped_mode = self.current_play_mode
        if player:
            self.player.stop()
        if sound_player:
            self.sound_player.stop()
        if player:
            player.wait_until_stopped(timeout=2.0)
        if sound_player:
            sound_player.wait_until_stopped(timeout=2.0)
        self.player = None
        self.sound_player = None
        self.current_play_mode = None
        self.seeking_keys = False
        self._refresh_playback_buttons()
        self._refresh_midi_input_button()
        self._refresh_option_states()
        if stopped_mode == "sound":
            self.state_var.set("sound stopped")
            self._log(self._text("sound_playback_stopped"))
        elif stopped_mode == "keys":
            self.state_var.set("stopped")
        self._set_position(0.0)

    def _on_sound_volume_changed(self, _value: str) -> None:
        volume = int(float(_value))
        self.sound_volume_var.set(volume)
        self.sound_volume_label.configure(text=f"{volume}%")
        self._save_current_settings()
        if self.sound_player:
            self.sound_player.set_volume(volume)
        if self.realtime_sound_output:
            self.realtime_sound_output.set_volume(volume)

    def _on_sound_volume_pointer(self, event: tk.Event) -> str:
        volume = int(round(self._scale_value_from_event(self.sound_volume, event)))
        self.sound_volume_var.set(volume)
        self._on_sound_volume_changed(str(volume))
        return "break"

    def _close_realtime_sound_output(self) -> None:
        output = self.realtime_sound_output
        self.realtime_sound_output = None
        if output is not None:
            output.close()

    def _on_playback_speed_changed(self, value: str) -> None:
        speed = int(round(float(value)))
        self.playback_speed_var.set(speed)
        self.playback_speed_label.configure(text=f"{speed}%")
        if self.player:
            self.player.set_playback_speed(speed)
        if self.sound_player:
            self.sound_player.set_playback_speed(speed)
        self._save_current_settings()

    def _on_playback_speed_pointer(self, event: tk.Event) -> str:
        speed = int(round(self._scale_value_from_event(self.playback_speed, event)))
        self.playback_speed_var.set(speed)
        self._on_playback_speed_changed(str(speed))
        return "break"

    def _reset_playback_speed(self, _event: tk.Event | None = None) -> str:
        self.playback_speed_var.set(100)
        self._on_playback_speed_changed("100")
        return "break"

    def _on_position_slider_changed(self, value: str) -> None:
        if self.updating_position_from_player:
            return

        position = float(value)
        self._update_position_label(position)
        if self.current_play_mode is None:
            return

        now = time.perf_counter()
        if now - self.last_drag_seek_at >= 0.25:
            self.last_drag_seek_at = now
            self._seek_to(position)

    def _on_position_pointer_down(self, event: tk.Event) -> str:
        self.position_dragging = True
        position = self._scale_value_from_event(self.position_slider, event)
        self.position_var.set(position)
        self._update_position_label(position)
        self.last_drag_seek_at = time.perf_counter()
        self._seek_to(position)
        return "break"

    def _on_position_pointer_move(self, event: tk.Event) -> str:
        position = self._scale_value_from_event(self.position_slider, event)
        self.position_var.set(position)
        self._on_position_slider_changed(str(position))
        return "break"

    def _on_position_drag_end(self, _event: tk.Event) -> None:
        self.position_dragging = False
        position = self.position_var.get()
        self._set_position(position)
        self._seek_to(position)

    def _seek_to(self, position: float) -> None:
        position = max(0.0, min(self.duration_seconds, position))
        self.ignore_player_position_until = time.perf_counter() + 0.8
        if self.current_play_mode == "sound" and self.sound_player and self.sound_player.is_playing:
            self.sound_player.seek(position)
        elif self.current_play_mode == "keys" and self.player and self.player.is_playing:
            self.seeking_keys = True
            old_player = self.player
            old_player.stop()
            old_player.wait_until_stopped(timeout=2.0)
            if old_player.is_playing:
                self.seeking_keys = False
                self._log("Keyboard playback could not be stopped in time; seek was cancelled")
                return
            self.player = None
            self._restart_keys_from(position)

    def _play_start_position(self) -> float:
        position = self.position_var.get()
        if self.duration_seconds > 0 and position >= self.duration_seconds - 1.0:
            self._set_position(0.0)
            return 0.0
        return position

    def _restart_keys_from(self, position: float) -> None:
        events = self.events
        if not self._has_enabled_events(events):
            self.current_play_mode = None
            self.seeking_keys = False
            self._refresh_playback_buttons()
            return

        output = KeyboardOutput(dry_run=self.dry_run_var.get())
        playback_id = self._next_playback_id()
        transpose_semitones, octave_shift = self._note_shift_values()
        self.player = MidiKeyboardPlayer(
            output=output,
            log=lambda message: self.log_queue.put(message),
            on_state=lambda state, pid=playback_id: self.log_queue.put(f"__STATE__{pid}__{state}"),
            on_position=lambda current_position, pid=playback_id: self.log_queue.put(
                f"__POSITION__{pid}__{current_position}"
            ),
            on_optimization_progress=lambda progress, pid=playback_id: self.log_queue.put(
                f"__OPTIMIZATION__{pid}__{'done' if progress is None else progress}"
            ),
            enabled_channels=self._enabled_channels,
            enabled_sources=self._enabled_sources,
            auto_fit_note_range=self.auto_fit_note_range_var.get(),
            transpose_semitones=transpose_semitones,
            octave_shift=octave_shift,
            humanize_timing=self.humanize_timing_var.get(),
            chord_optimization=self.chord_optimization_var.get(),
            chord_strum=self.chord_strum_var.get(),
            repeat_prevention=self.repeat_prevention_var.get(),
            playback_speed_percent=self.playback_speed_var.get(),
        )
        self.player.play(events, countdown_seconds=0, start_time=position)

    def _on_channel_changed(self) -> None:
        if self.updating_channels:
            return
        self._commit_channel_selection()

    def _commit_channel_selection(self) -> None:
        track_channel_vars = self.__dict__.get("track_channel_vars", {})
        if track_channel_vars:
            selected_sources = frozenset(
                source for source, var in track_channel_vars.items() if var.get()
            )
            self.enabled_sources_snapshot = selected_sources
            self.enabled_channels_snapshot = frozenset(
                channel for _track, channel in selected_sources
            )
        else:
            selected_channels = frozenset(
                channel for channel, var in self.channel_vars.items() if var.get()
            )
            self.enabled_channels_snapshot = selected_channels
        if self.current_play_mode == "keys" and self.player and self.player.is_playing:
            if hasattr(self.player, "request_chord_optimization_refresh"):
                self.player.request_chord_optimization_refresh()
            self.player.request_release_all()
        elif self.current_play_mode == "sound" and self.sound_player and self.sound_player.is_playing:
            if hasattr(self.sound_player, "request_chord_optimization_refresh"):
                self.sound_player.request_chord_optimization_refresh()
            self.sound_player.release_all()

    def _on_countdown_changed(self, *_args: object) -> None:
        self._save_current_settings()

    def _on_countdown_sound_changed(self, *_args: object) -> None:
        self._save_current_settings()

    def _on_game_countdown_sound_changed(self, *_args: object) -> None:
        self._save_current_settings()

    def _on_humanize_timing_changed(self, *_args: object) -> None:
        value = self.humanize_timing_var.get()
        if self.player:
            self.player.set_humanize_timing(value)
        if self.sound_player:
            self.sound_player.set_humanize_timing(value)
        self._save_current_settings()

    def _on_chord_optimization_changed(self, *_args: object) -> None:
        value = self.chord_optimization_var.get()
        if self.player:
            self.player.set_chord_optimization(value)
        if self.sound_player:
            self.sound_player.set_chord_optimization(value)
        self._save_current_settings()

    def _toggle_chord_optimization(self, _event: tk.Event | None = None) -> str:
        self.chord_optimization_var.set(not self.chord_optimization_var.get())
        return "break"

    def _on_chord_strum_changed(self, *_args: object) -> None:
        value = self.chord_strum_var.get()
        if self.player:
            self.player.set_chord_strum(value)
        if self.sound_player:
            self.sound_player.set_chord_strum(value)
        self._save_current_settings()

    def _on_repeat_prevention_changed(self, *_args: object) -> None:
        value = self.repeat_prevention_var.get()
        if self.player:
            self.player.set_repeat_prevention(value)
        if self.sound_player:
            self.sound_player.set_repeat_prevention(value)
        if self.midi_input_bridge:
            self.midi_input_bridge.set_repeat_prevention(value)
        if self.realtime_sound_output:
            self.realtime_sound_output.set_repeat_prevention(value)
        self._save_current_settings()

    def _on_auto_fit_note_range_changed(self, *_args: object) -> None:
        value = self.auto_fit_note_range_var.get()
        if self.player:
            self.player.set_auto_fit_note_range(value)
        if self.sound_player:
            self.sound_player.set_auto_fit_note_range(value)
        if self.midi_input_bridge:
            self.midi_input_bridge.set_auto_fit_note_range(value)
        self._save_current_settings()

    def _on_note_shift_changed(self, *_args: object) -> None:
        transpose_semitones, octave_shift = self._note_shift_values()
        player = self.__dict__.get("player")
        sound_player = self.__dict__.get("sound_player")
        midi_input_bridge = self.__dict__.get("midi_input_bridge")
        realtime_sound_output = self.__dict__.get("realtime_sound_output")
        if player:
            player.set_note_shift(transpose_semitones, octave_shift)
        if sound_player:
            sound_player.set_note_shift(transpose_semitones, octave_shift)
        if midi_input_bridge:
            midi_input_bridge.set_note_shift(transpose_semitones, octave_shift)
        if realtime_sound_output:
            realtime_sound_output.set_note_shift(transpose_semitones, octave_shift)
        self._save_current_settings()

    def _reset_transpose_semitones(self, _event: tk.Event | None = None) -> str:
        self.transpose_semitones_var.set(0)
        return "break"

    def _reset_octave_shift(self, _event: tk.Event | None = None) -> str:
        self.octave_shift_var.set(0)
        return "break"

    def _on_app_pointer_down(self, event: tk.Event) -> None:
        numeric_fields = (
            self.countdown_spinbox,
            self.transpose_semitones_spinbox,
            self.octave_shift_spinbox,
        )
        if self.focus_get() in numeric_fields and event.widget not in numeric_fields:
            self.focus_set()

    def _on_dry_run_changed(self, *_args: object) -> None:
        self._save_current_settings()

    def _on_color_theme_changed(self, *_args: object) -> None:
        self.color_theme = color_theme_code_from_name(self.language, self.color_theme_var.get())
        self.color_theme_menu_var.set(self.color_theme)
        self._apply_theme()
        self._save_current_settings()

    def _set_color_theme(self, theme: str) -> None:
        self.color_theme = normalize_color_theme(theme)
        self.color_theme_var.set(COLOR_THEME_NAMES[self.language][self.color_theme])
        self.color_theme_menu_var.set(self.color_theme)
        self._apply_theme()
        self._save_current_settings()

    def _on_always_on_top_changed(self, *_args: object) -> None:
        self._apply_always_on_top()
        self._save_current_settings()

    def _on_tray_resident_changed(self, *_args: object) -> None:
        if not self.tray_resident_var.get() and self.tray_icon is not None:
            self.tray_icon.hide()
        self._save_current_settings()

    def _on_window_opacity_changed(self, *_args: object) -> None:
        self._apply_window_opacity()
        self._save_current_settings()

    def _set_window_opacity(self, opacity: int) -> None:
        self.window_opacity_var.set(max(30, min(100, opacity)))
        self._apply_window_opacity()
        self._save_current_settings()

    def _on_opacity_slider_changed(self, value: str) -> None:
        opacity = int(round(float(value)))
        self.window_opacity_var.set(opacity)
        self._apply_window_opacity()
        self._save_current_settings()

    def _reset_window_opacity(self, _event: tk.Event | None = None) -> str:
        self.window_opacity_var.set(100)
        self._on_opacity_slider_changed("100")
        return "break"

    def _on_play_shortcut_key_pressed(self, event: tk.Event) -> str:
        if self.shortcut_lock_var.get():
            return "break"
        shortcut = self._shortcut_from_event(event)
        if shortcut is not None:
            if shortcut_to_hotkey_spec(shortcut, "play") is None:
                self._log(f"Unsupported start shortcut: {shortcut}")
                return "break"
            if self._shortcuts_match(shortcut, self.keyboard_stop_shortcut_var.get()):
                self._log("Start and end shortcuts must be different")
                return "break"
            self.keyboard_play_shortcut_var.set(shortcut)
            self._on_shortcut_changed()
        return "break"

    def _on_stop_shortcut_key_pressed(self, event: tk.Event) -> str:
        if self.shortcut_lock_var.get():
            return "break"
        shortcut = self._shortcut_from_event(event)
        if shortcut is not None:
            if shortcut_to_hotkey_spec(shortcut, "stop") is None:
                self._log(f"Unsupported end shortcut: {shortcut}")
                return "break"
            if self._shortcuts_match(shortcut, self.keyboard_play_shortcut_var.get()):
                self._log("Start and end shortcuts must be different")
                return "break"
            self.keyboard_stop_shortcut_var.set(shortcut)
            self._on_shortcut_changed()
        return "break"

    def _on_shortcut_changed(self) -> None:
        self._bind_keyboard_shortcuts()
        self._save_current_settings()

    def _on_shortcut_lock_changed(self, *_args: object) -> None:
        self._refresh_shortcut_lock_state()
        self._save_current_settings()

    def _on_language_changed(self, *_args: object) -> None:
        previous_theme = self.color_theme
        self.language = language_code_from_name(self.language_var.get())
        self.color_theme = previous_theme
        self.language_menu_var.set(self.language)
        self.color_theme_var.set(COLOR_THEME_NAMES[self.language][self.color_theme])
        self.color_theme_menu_var.set(self.color_theme)
        self._refresh_text()
        self._fit_window_width_to_key_settings()
        channels = self.summary.channels if self.summary is not None else ()
        self._set_channels(channels, selected_sources=self._enabled_sources())
        self._save_current_settings()

    def _set_language(self, language: str) -> None:
        previous_theme = self.color_theme
        self.language = normalize_language(language)
        self.color_theme = previous_theme
        self.language_var.set(LANGUAGE_NAMES[self.language])
        self.language_menu_var.set(self.language)
        self.color_theme_var.set(COLOR_THEME_NAMES[self.language][self.color_theme])
        self.color_theme_menu_var.set(self.color_theme)
        self._refresh_text()
        self._fit_window_width_to_key_settings()
        channels = self.summary.channels if self.summary is not None else ()
        self._set_channels(channels, selected_sources=self._enabled_sources())
        self._save_current_settings()

    def _save_current_settings(self, immediate: bool = False) -> None:
        if immediate or self.exiting:
            if self.settings_save_after_id is not None:
                try:
                    self.after_cancel(self.settings_save_after_id)
                except tk.TclError:
                    pass
                self.settings_save_after_id = None
            self._flush_current_settings()
            return
        if self.settings_save_after_id is None:
            self.settings_save_after_id = self.after(300, self._flush_current_settings)

    def _flush_current_settings(self) -> None:
        self.settings_save_after_id = None
        try:
            save_settings(self._current_settings())
        except Exception as exc:
            message = f"Settings could not be saved: {exc}"
            if message != self.settings_save_error and "log_text" in self.__dict__:
                self._log(message)
            self.settings_save_error = message
            if not self.exiting:
                self.settings_save_after_id = self.after(2000, self._flush_current_settings)
        else:
            self.settings_save_error = ""

    def _current_settings(self) -> AppSettings:
        transpose_semitones, octave_shift = self._note_shift_values()
        return AppSettings(
            countdown_seconds=self._read_int_var(self.countdown_var, minimum=0, maximum=10, default=3),
            midi_sound_volume=self._read_int_var(self.sound_volume_var, minimum=0, maximum=100, default=80),
            dry_run=self.dry_run_var.get(),
            countdown_sound=self.countdown_sound_var.get(),
            game_countdown_sound=self.game_countdown_sound_var.get(),
            auto_fit_note_range=self.auto_fit_note_range_var.get(),
            transpose_semitones=transpose_semitones,
            octave_shift=octave_shift,
            humanize_timing=self.humanize_timing_var.get(),
            chord_optimization=self.chord_optimization_var.get(),
            chord_strum=self.chord_strum_var.get(),
            repeat_prevention=self.repeat_prevention_var.get(),
            playback_speed_percent=self._read_int_var(
                self.playback_speed_var,
                minimum=MIN_PLAYBACK_SPEED_PERCENT,
                maximum=MAX_PLAYBACK_SPEED_PERCENT,
                default=100,
            ),
            language=self.language,
            color_theme=self.color_theme,
            always_on_top=self.always_on_top_var.get(),
            tray_resident=self.tray_resident_var.get(),
            window_opacity=self._read_int_var(self.window_opacity_var, minimum=30, maximum=100, default=100),
            window_height=max(MIN_WINDOW_HEIGHT, self.saved_window_height),
            last_midi_folder=self.last_midi_folder,
            keyboard_play_shortcut=self.keyboard_play_shortcut_var.get().strip() or "F5",
            keyboard_stop_shortcut=self.keyboard_stop_shortcut_var.get().strip() or "F6",
            shortcut_locked=self.shortcut_lock_var.get(),
            midi_input_device=self.midi_input_device_var.get(),
            key_bindings=self._current_key_bindings(),
        )

    def _current_key_bindings(self) -> dict[int, str]:
        return normalized_key_bindings(self.__dict__.get("key_bindings"))

    @staticmethod
    def _read_int_var(variable: tk.IntVar, minimum: int, maximum: int, default: int) -> int:
        try:
            value = variable.get()
        except (tk.TclError, ValueError):
            return default
        return max(minimum, min(maximum, value))

    def _set_key_binding(self, note: int, key: str) -> None:
        updated = self._current_key_bindings()
        updated[note] = key
        self._apply_key_bindings(updated)

    def _reset_key_bindings_to_default(self) -> None:
        self._apply_key_bindings(DEFAULT_KEY_BINDINGS)

    def _apply_key_bindings(self, key_bindings: dict[int, str]) -> None:
        self.key_bindings = normalized_key_bindings(key_bindings)
        if self.player is not None and hasattr(self.player, "set_key_bindings"):
            self.player.set_key_bindings(self.key_bindings)
        if self.midi_input_bridge is not None and hasattr(self.midi_input_bridge, "set_key_bindings"):
            self.midi_input_bridge.set_key_bindings(self.key_bindings)
        self._save_current_settings()
        self._refresh_key_binding_window_values()

    def _note_shift_values(self) -> tuple[int, int]:
        return (
            self._read_int_var(
                self.transpose_semitones_var,
                minimum=MIN_TRANSPOSE_SEMITONES,
                maximum=MAX_TRANSPOSE_SEMITONES,
                default=0,
            ),
            self._read_int_var(
                self.octave_shift_var,
                minimum=MIN_OCTAVE_SHIFT,
                maximum=MAX_OCTAVE_SHIFT,
                default=0,
            ),
        )

    def _on_window_configure(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        if self.state() == "withdrawn":
            return
        height = int(event.height)
        if height >= MIN_WINDOW_HEIGHT:
            self.saved_window_height = height

    def _on_close(self) -> None:
        if self.tray_resident_var.get() and self.tray_icon is not None and not self.exiting:
            self._hide_to_tray()
            return
        self._exit_app()

    def _exit_app(self) -> None:
        self.exiting = True
        self.midi_duration_scan_cancel.set()
        self._save_current_settings(immediate=True)
        self._unbind_keyboard_shortcuts()
        if self.tray_icon is not None:
            self.tray_icon.uninstall()
        self.stop_midi_input()
        self.stop()
        if self.single_instance is not None:
            self.single_instance.close()
        self.destroy()

    def _hide_to_tray(self) -> None:
        self._save_current_settings()
        if self.tray_icon is not None:
            self.tray_icon.show()
        self.withdraw()

    def _restore_from_tray(self) -> None:
        if self.tray_icon is not None:
            self.tray_icon.hide()
        self.deiconify()
        if self.state() == "iconic":
            self.state("normal")
        self.lift()
        self.focus_force()
        self._apply_always_on_top()

    def _poll_single_instance(self) -> None:
        if (
            self.single_instance is not None
            and self.single_instance.consume_activation_request()
        ):
            self._restore_from_tray()
            self.single_instance.bring_existing_window_to_front()
            self.attributes("-topmost", True)
            self.after(100, self._apply_always_on_top)
        if not self.exiting:
            self.after(100, self._poll_single_instance)

    def _poll_tray_icon(self) -> None:
        if self.tray_icon is not None:
            if self.tray_icon.consume_exit_request():
                self._exit_app()
                return
            if self.tray_icon.consume_restore_request():
                self._restore_from_tray()
        if not self.exiting:
            self.after(100, self._poll_tray_icon)

    @staticmethod
    def _resource_path(relative_path: Path) -> Path:
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        return base / relative_path

    def _apply_window_icon(self, icon_path: Path, icon_png_path: Path) -> None:
        if icon_path.exists():
            try:
                self.iconbitmap(default=str(icon_path))
            except tk.TclError:
                pass
        if icon_png_path.exists():
            try:
                self.window_icon_image = tk.PhotoImage(file=str(icon_png_path))
                self.iconphoto(True, self.window_icon_image)
            except tk.TclError:
                pass

    def _refresh_playback_buttons(self) -> None:
        sound_button = self.__dict__.get("sound_button")
        if self.current_play_mode == "keys":
            self._configure_action_button(
                self.play_button,
                text=self._text("stop_keys"),
                state="normal",
                active=True,
            )
            if sound_button is not None:
                self._configure_action_button(sound_button, text=self._text("play_midi_sound"), state="disabled")
        elif self.current_play_mode == "sound":
            self._configure_action_button(self.play_button, text=self._text("play_keys"), state="disabled")
            if sound_button is not None:
                self._configure_action_button(
                    sound_button,
                    text=self._text("stop_midi"),
                    state="normal",
                    active=True,
                )
        elif self._midi_input_is_running():
            self._configure_action_button(self.play_button, text=self._text("play_keys"), state="disabled")
            if sound_button is not None:
                self._configure_action_button(sound_button, text=self._text("play_midi_sound"), state="normal")
        else:
            self._configure_action_button(self.play_button, text=self._text("play_keys"), state="normal")
            if sound_button is not None:
                self._configure_action_button(sound_button, text=self._text("play_midi_sound"), state="normal")

    def _refresh_midi_input_button(self) -> None:
        if "midi_input_button" not in self.__dict__ or "midi_input_select" not in self.__dict__:
            return
        if self._midi_input_is_running():
            self._configure_action_button(
                self.midi_input_button,
                text=self._text("stop_midi_input"),
                state="normal",
                active=True,
            )
            self.midi_input_select.configure(state="disabled")
        elif self.current_play_mode == "keys":
            self._configure_action_button(
                self.midi_input_button,
                text=self._text("start_midi_input"),
                state="disabled",
            )
            self.midi_input_select.configure(state="readonly")
        else:
            self._configure_action_button(
                self.midi_input_button,
                text=self._text("start_midi_input"),
                state="normal",
            )
            self.midi_input_select.configure(state="readonly")

    def _configure_action_button(
        self,
        button: ttk.Button,
        *,
        text: str,
        state: str,
        active: bool = False,
    ) -> None:
        if state == "disabled":
            button.configure(
                text=text,
                image="",
                state=state,
                style="DisabledAction.TButton",
            )
            return
        style = "ActiveAction.TButton" if active else "TButton"
        button.configure(text=text, image="", state=state, style=style)

    def _refresh_option_states(self) -> None:
        dry_run_state = tk.DISABLED if self.current_play_mode == "keys" or self._midi_input_is_running() else tk.NORMAL
        key_playback_state = tk.DISABLED if self.current_play_mode == "keys" else tk.NORMAL

        if "dry_run_check" in self.__dict__:
            self.dry_run_check.configure(state=dry_run_state)
        if "countdown_spinbox" in self.__dict__:
            self.countdown_spinbox.configure(state=key_playback_state)
        if "countdown_sound_check" in self.__dict__:
            self.countdown_sound_check.configure(state=key_playback_state)
        if "game_countdown_sound_check" in self.__dict__:
            self.game_countdown_sound_check.configure(state=key_playback_state)
        if "humanize_timing_check" in self.__dict__:
            self.humanize_timing_check.configure(state=tk.NORMAL)

    def _midi_input_is_running(self) -> bool:
        bridge = self.__dict__.get("midi_input_bridge")
        return bridge is not None and bridge.is_running

    def _sound_playback_is_active(self) -> bool:
        sound_player = self.__dict__.get("sound_player")
        return (
            self.__dict__.get("current_play_mode") == "sound"
            and sound_player is not None
            and sound_player.is_playing
        )

    def _set_channels(
        self,
        channels: tuple[int, ...],
        selected_channels: set[int] | None = None,
        selected_sources: set[tuple[int, int]] | None = None,
    ) -> None:
        summary = self.__dict__.get("summary")
        tracks = summary.tracks if summary is not None else ()
        if not tracks and channels:
            tracks = (MidiTrackSummary(index=0, channels=channels),)
        if selected_sources is None:
            if selected_channels is None:
                selected_sources = {
                    (track.index, channel)
                    for track in tracks
                    for channel in track.channels
                }
            else:
                selected_sources = {
                    (track.index, channel)
                    for track in tracks
                    for channel in track.channels
                    if channel in selected_channels
                }

        self.updating_channels = True
        for child in self.channel_frame.winfo_children():
            child.destroy()
        self.channel_vars.clear()
        self.track_channel_vars.clear()
        available_sources = [
            (track.index, channel)
            for track in tracks
            for channel in track.channels
        ]
        selected_sources.intersection_update(available_sources)
        self._add_channel_grid_header()

        if not available_sources:
            self.enabled_sources_snapshot = frozenset()
            self.enabled_channels_snapshot = frozenset()
            self.updating_channels = False
            self.channel_canvas.update_idletasks()
            self._update_channel_scrollregion()
            self.channel_canvas.yview_moveto(0.0)
            return

        for row, (track, channel) in enumerate(available_sources, start=1):
            source = (track, channel)
            var = tk.BooleanVar(value=source in selected_sources)
            self.track_channel_vars[source] = var
            row_frame = tk.Frame(
                self.channel_frame,
                borderwidth=0,
                relief=tk.FLAT,
            )
            row_frame.grid(row=row, column=0, sticky="ew", pady=(0, 1))
            row_frame.bind("<MouseWheel>", self._on_channel_mousewheel)
            row_frame.bind(
                "<Button-1>",
                lambda _event, variable=var: self._toggle_channel_var(variable),
            )
            row_frame._channel_var = var  # type: ignore[attr-defined]

            cell = tk.Label(
                row_frame,
                text=f"{track + 1}-{channel + 1}",
                anchor="center",
                borderwidth=0,
                relief=tk.FLAT,
                padx=0,
                pady=3,
            )
            cell.pack(fill=tk.X)
            cell.bind("<MouseWheel>", self._on_channel_mousewheel)
            cell.bind(
                "<Button-1>",
                lambda _event, variable=var: self._toggle_channel_var(variable),
            )
            self._style_channel_row(row_frame, var)

        self.enabled_sources_snapshot = frozenset(selected_sources)
        self.enabled_channels_snapshot = frozenset(
            channel for _track, channel in selected_sources
        )
        self.updating_channels = False
        self.channel_canvas.update_idletasks()
        self._update_channel_scrollregion()
        self.channel_canvas.yview_moveto(0.0)

    def _add_channel_grid_header(self) -> None:
        self.channel_frame.grid_columnconfigure(0, minsize=34)
        header_frame = tk.Frame(self.channel_frame, borderwidth=0, relief=tk.FLAT)
        header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 1))
        header_frame.bind("<MouseWheel>", self._on_channel_mousewheel)
        label = tk.Label(
            header_frame,
            text="T-C",
            anchor="center",
            borderwidth=0,
            relief=tk.FLAT,
            padx=5,
            pady=2,
        )
        label.pack(fill=tk.X)
        label.bind("<MouseWheel>", self._on_channel_mousewheel)
        self._style_channel_header_label(label)
        self._style_channel_cell(header_frame)

    def _toggle_channel_var(self, variable: tk.BooleanVar) -> None:
        variable.set(not variable.get())
        self._style_channel_grid_widgets(self.channel_frame, self._theme_palette())
        self._on_channel_changed()

    def _on_channel_frame_configure(self, _event: tk.Event | None = None) -> None:
        self._update_channel_scrollregion()

    def _on_channel_canvas_configure(self, event: tk.Event) -> None:
        self.channel_canvas.itemconfigure(self.channel_canvas_window, width=event.width)
        self._update_channel_scrollregion(event.width, event.height)

    def _update_channel_scrollregion(
        self,
        viewport_width: int | None = None,
        viewport_height: int | None = None,
    ) -> None:
        if viewport_width is None:
            viewport_width = self.channel_canvas.winfo_width()
        if viewport_height is None:
            viewport_height = self.channel_canvas.winfo_height()
        scrollregion = self._channel_scrollregion(
            self.channel_canvas.bbox("all"),
            viewport_width,
            viewport_height,
        )
        self.channel_canvas.configure(scrollregion=scrollregion)

    @staticmethod
    def _channel_scrollregion(
        content_bbox: tuple[int, int, int, int] | None,
        viewport_width: int,
        viewport_height: int,
    ) -> tuple[int, int, int, int]:
        content_right = content_bbox[2] if content_bbox is not None else 0
        content_bottom = content_bbox[3] if content_bbox is not None else 0
        return (
            0,
            0,
            max(1, content_right),
            max(1, viewport_height, content_bottom),
        )

    def _on_channel_mousewheel(self, event: tk.Event) -> str:
        if event.delta:
            units = -1 if event.delta > 0 else 1
            self.channel_canvas.yview_scroll(units, "units")
        return "break"

    def _drain_log_queue(self) -> None:
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if message.startswith("__STATE__"):
                parsed = self._parse_player_message(message, "__STATE__")
                if parsed is None:
                    continue
                _playback_id, state = parsed
                self.state_var.set(state)
                if state == "stopped":
                    if self.seeking_keys:
                        self.seeking_keys = False
                    elif self.current_play_mode == "keys":
                        if self.duration_seconds > 0 and self.position_var.get() >= self.duration_seconds - 1.0:
                            self._set_position(self.duration_seconds)
                        self.current_play_mode = None
                        self._refresh_playback_buttons()
                        self._refresh_midi_input_button()
                        self._refresh_option_states()
            elif message.startswith("__SOUND_STATE__"):
                parsed = self._parse_player_message(message, "__SOUND_STATE__")
                if parsed is None:
                    continue
                _playback_id, state = parsed
                self.state_var.set(state)
                if state == "sound ended":
                    self._set_position(self.duration_seconds)
                    if self.current_play_mode == "sound":
                        self.current_play_mode = None
                        self._refresh_playback_buttons()
                        self._refresh_midi_input_button()
                        self._refresh_option_states()
                elif state == "sound stopped":
                    if self.current_play_mode == "sound":
                        self.current_play_mode = None
                        self._refresh_playback_buttons()
                        self._refresh_midi_input_button()
                        self._refresh_option_states()
            elif message.startswith("__MIDI_INPUT_STATE__"):
                state = message.removeprefix("__MIDI_INPUT_STATE__")
                self.state_var.set(state)
                if state == "midi input failed" and self.midi_input_bridge is not None:
                    self.midi_input_bridge.stop()
                    self.midi_input_bridge = None
                    self._close_realtime_sound_output()
                self._refresh_playback_buttons()
                self._refresh_midi_input_button()
                self._refresh_option_states()
            elif message.startswith("__OPTIMIZATION__"):
                parsed = self._parse_player_message(message, "__OPTIMIZATION__")
                if parsed is None:
                    continue
                _playback_id, progress = parsed
                if progress == "done":
                    if self.current_play_mode == "keys":
                        self.state_var.set("playing")
                    elif self.current_play_mode == "sound":
                        self.state_var.set("sound playing")
                else:
                    try:
                        percent = max(0, min(100, int(progress)))
                    except ValueError:
                        continue
                    self.state_var.set(
                        self._text("optimization_progress").format(percent=percent)
                    )
            elif message.startswith("__POSITION__"):
                parsed = self._parse_player_message(message, "__POSITION__")
                if parsed is None:
                    continue
                if time.perf_counter() < self.ignore_player_position_until:
                    continue
                if not self.position_dragging:
                    _playback_id, position = parsed
                    self._set_position(float(position))
            else:
                self._log(message)
        self.after(60, self._drain_log_queue)

    def _log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def _refresh_text(self) -> None:
        self.title(self._text("title"))
        self._refresh_menu_bar()
        self._refresh_playback_buttons()
        self.auto_fit_note_range_check.configure(text=self._text("auto_fit_note_range"))
        self.transpose_semitones_label.configure(text=self._text("transpose_semitones"))
        self.octave_shift_label.configure(text=self._text("octave_shift"))
        self.chord_optimization_label.configure(text=self._text("chord_optimization"))
        self.chord_strum_check.configure(text=self._text("chord_strum"))
        self.repeat_prevention_check.configure(text=self._text("repeat_prevention"))
        self.color_theme_var.set(COLOR_THEME_NAMES[self.language][self.color_theme])
        self.key_settings.configure(text=self._text("key_playback_settings"))
        self.midi_input_settings.configure(text=self._text("midi_input_settings"))
        self._refresh_midi_input_button()
        self.midi_input_device_label.configure(text=self._text("midi_input_device"))
        self.refresh_midi_inputs_button.configure(text=self._text("refresh_midi_inputs"))
        self.sound_settings.configure(text=self._text("midi_sound_settings"))
        self.dry_run_check.configure(text=self._text("dry_run"))
        countdown_text = self._text("countdown")
        if self.language == "zh":
            countdown_text += "\u3000"
        self.countdown_label.configure(text=countdown_text)
        self.countdown_unit_label.configure(text=self._text("seconds_unit"))
        self.countdown_sound_check.configure(text=self._text("countdown_sound"))
        self.game_countdown_sound_check.configure(text=self._text("game_countdown_sound"))
        self.humanize_timing_check.configure(text=self._text("humanize_timing"))
        self.playback_speed_title.configure(text=self._text("playback_speed"))
        self.playback_speed_title.configure(
            width=self._sound_volume_label_width(),
            anchor=self._sound_volume_label_anchor(),
        )
        self.playback_speed_title.grid_configure(padx=(0, self._sound_volume_label_padx()))
        self.shortcut_label.configure(text=self._text("shortcut_settings"))
        self.keyboard_play_shortcut_label.configure(text=self._text("shortcut_start"))
        self.keyboard_stop_shortcut_label.configure(text=self._text("shortcut_end"))
        self.shortcut_lock_check.configure(text=self._text("shortcut_lock"))
        self.sound_volume_title.configure(
            width=self._sound_volume_label_width(),
            anchor=self._sound_volume_label_anchor(),
        )
        self.sound_volume_title.grid_configure(padx=(0, self._sound_volume_label_padx()))
        self.sound_volume_title.configure(text=self._text("midi_sound_volume"))
        self.position_title.configure(text=self._text("playback_position"))
        self.detail_tabs.tab(self.midi_list_tab, text=self._text("midi_list"))
        self.detail_tabs.tab(self.reload_tab, text="\u21bb")
        self.detail_tabs.tab(self.log_tab, text=self._text("playback_log"))
        self.midi_tree.heading("#0", text=self._text("name"), anchor="w")
        self.midi_tree.heading("duration", text=self._text("duration"), anchor="w")
        self.midi_tree.heading("note_range", text=self._text("note_range"), anchor="w")

        if self.summary is None:
            self.state_var.set(self._text("waiting"))

    def _refresh_menu_bar(self) -> None:
        if "menu_bar" not in self.__dict__:
            return

        self.menu_bar.entryconfigure(0, label=self._text("menu_midi"))
        self.menu_bar.entryconfigure(1, label=self._text("menu_view"))
        self.menu_bar.entryconfigure(2, label=self._text("menu_settings"))
        self.menu_bar.entryconfigure(3, label=self._text("menu_other"))

        self.midi_menu.entryconfigure(0, label=self._text("load_midi"))
        self.midi_menu.entryconfigure(2, label=self._text("exit"))
        self.view_menu.entryconfigure(0, label=self._text("window_opacity"))
        self.view_menu.entryconfigure(2, label=self._text("always_on_top"))
        self.settings_menu.entryconfigure(0, label=self._text("color_theme"))
        self.settings_menu.entryconfigure(1, label=self._text("language"))
        self.settings_menu.entryconfigure(2, label=self._text("key_bindings"))
        self.settings_menu.entryconfigure(4, label=self._text("tray_resident"))
        self.other_menu.entryconfigure(0, label=self._text("about_app"))

        self.theme_menu.delete(0, tk.END)
        self.color_theme_menu_var.set(self.color_theme)
        for code, label in COLOR_THEME_NAMES[self.language].items():
            self.theme_menu.add_radiobutton(
                label=label,
                variable=self.color_theme_menu_var,
                value=code,
                command=lambda value=code: self._set_color_theme(value),
            )

        self.language_menu_widget.delete(0, tk.END)
        self.language_menu_var.set(self.language)
        for code, label in LANGUAGE_NAMES.items():
            self.language_menu_widget.add_radiobutton(
                label=label,
                variable=self.language_menu_var,
                value=code,
                command=lambda value=code: self._set_language(value),
            )

    def _text(self, key: str) -> str:
        return TEXT[self.language][key]

    def _sound_volume_label_width(self) -> int:
        return 18 if self.language == "en" else 10

    def _opacity_label_width(self) -> int:
        return 7 if self.language == "en" else 6

    def _sound_volume_label_anchor(self) -> str:
        return "w" if self.language == "en" else "e"

    def _sound_volume_label_padx(self) -> int:
        return 6 if self.language == "en" else 8

    def _set_position(self, position: float) -> None:
        position = max(0.0, min(self.duration_seconds, position))
        self.updating_position_from_player = True
        try:
            self.position_var.set(position)
        finally:
            self.updating_position_from_player = False
        self._update_position_label(position)

    def _update_position_label(self, position: float) -> None:
        self.position_label.configure(
            text=f"{self._format_time(position)} / {self._format_time(self.duration_seconds)}"
        )

    @staticmethod
    def _format_time(seconds: float) -> str:
        total_seconds = max(0, int(seconds))
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"

    @classmethod
    def _format_note_range(cls, note_range: tuple[int, int] | None) -> str:
        if note_range is None:
            return "--"
        lowest, highest = note_range
        return f"{cls._format_midi_note(lowest)}-{cls._format_midi_note(highest)}"

    @staticmethod
    def _format_midi_note(note: int) -> str:
        names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
        return f"{names[note % 12]}{note // 12 - 1}"

    @staticmethod
    def _scale_value_from_event(scale: ttk.Scale, event: tk.Event) -> float:
        start = float(scale.cget("from"))
        end = float(scale.cget("to"))
        width = max(1, scale.winfo_width())
        ratio = max(0.0, min(1.0, event.x / width))
        return start + (end - start) * ratio

    def _bind_keyboard_shortcuts(self) -> None:
        self._unbind_keyboard_shortcuts()

        specs = []
        validation_errors: list[str] = []
        play_spec = shortcut_to_hotkey_spec(self.keyboard_play_shortcut_var.get(), "play")
        stop_spec = shortcut_to_hotkey_spec(self.keyboard_stop_shortcut_var.get(), "stop")
        if play_spec is not None:
            specs.append(play_spec)
        else:
            validation_errors.append(
                f"Unsupported start shortcut: {self.keyboard_play_shortcut_var.get()}"
            )
        if stop_spec is not None and (
            play_spec is None
            or stop_spec.modifiers != play_spec.modifiers
            or stop_spec.vk != play_spec.vk
        ):
            specs.append(stop_spec)
        elif stop_spec is None:
            validation_errors.append(
                f"Unsupported end shortcut: {self.keyboard_stop_shortcut_var.get()}"
            )
        else:
            validation_errors.append("Start and end shortcuts must be different")
        self.global_hotkeys = GlobalHotkeyManager(specs, self.hotkey_queue.put)
        self.global_hotkeys.start()
        registration_errors = [
            f"Global shortcut registration failed: {action}"
            for action in self.global_hotkeys.failed_actions
        ]
        failure_signature = tuple(validation_errors + registration_errors)
        if failure_signature != self.hotkey_failure_signature:
            for message in failure_signature:
                self._log(message)
            self.hotkey_failure_signature = failure_signature

        # Keep app-local bindings as a fallback when a global hotkey is unavailable.
        play_sequence = self._shortcut_to_sequence(self.keyboard_play_shortcut_var.get())
        stop_sequence = self._shortcut_to_sequence(self.keyboard_stop_shortcut_var.get())
        if play_sequence:
            self.bind_all(play_sequence, self._on_keyboard_play_shortcut)
            self.active_shortcut_sequences.append(play_sequence)
        if stop_sequence and stop_sequence != play_sequence:
            self.bind_all(stop_sequence, self._on_keyboard_stop_shortcut)
            self.active_shortcut_sequences.append(stop_sequence)

    def _unbind_keyboard_shortcuts(self) -> None:
        if self.global_hotkeys is not None:
            self.global_hotkeys.stop()
            self.global_hotkeys = None
        for sequence in self.active_shortcut_sequences:
            self.unbind_all(sequence)
        self.active_shortcut_sequences = []

    def _drain_hotkey_queue(self) -> None:
        while True:
            try:
                action = self.hotkey_queue.get_nowait()
            except queue.Empty:
                break
            if action == "play":
                self._on_keyboard_play_shortcut(None)
            elif action == "stop":
                self._on_keyboard_stop_shortcut(None)
        self.after(30, self._drain_hotkey_queue)

    def _ensure_keyboard_shortcuts(self) -> None:
        if self.exiting:
            return
        if self.global_hotkeys is None or not self.global_hotkeys.is_healthy:
            self._bind_keyboard_shortcuts()
        self.after(3000, self._ensure_keyboard_shortcuts)

    def _on_keyboard_play_shortcut(self, _event: tk.Event | None) -> str | None:
        if _event is not None and self._shortcut_entry_has_focus():
            return None
        if self.current_play_mode is None and not self._midi_input_is_running():
            self.play()
        return "break"

    def _on_keyboard_stop_shortcut(self, _event: tk.Event | None) -> str | None:
        if _event is not None and self._shortcut_entry_has_focus():
            return None
        if self.current_play_mode == "keys":
            self.stop()
        return "break"

    def _shortcut_entry_has_focus(self) -> bool:
        focused = self.focus_get()
        return focused in {self.keyboard_play_shortcut_entry, self.keyboard_stop_shortcut_entry}

    @staticmethod
    def _shortcuts_match(first: str, second: str) -> bool:
        first_spec = shortcut_to_hotkey_spec(first, "first")
        second_spec = shortcut_to_hotkey_spec(second, "second")
        return (
            first_spec is not None
            and second_spec is not None
            and first_spec.modifiers == second_spec.modifiers
            and first_spec.vk == second_spec.vk
        )

    def _refresh_shortcut_lock_state(self) -> None:
        state = "disabled" if self.shortcut_lock_var.get() else "readonly"
        self.keyboard_play_shortcut_entry.configure(state=state)
        self.keyboard_stop_shortcut_entry.configure(state=state)

    @staticmethod
    def _shortcut_from_event(event: tk.Event) -> str | None:
        key = getattr(event, "keysym", "")
        if not key or key in {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R"}:
            return None

        state = int(getattr(event, "state", 0))
        modifiers = []
        if App._shortcut_modifier_pressed(event, state, 0x0004, 0x11):
            modifiers.append("Ctrl")
        if App._shortcut_modifier_pressed(event, state, 0x0008, 0x12):
            modifiers.append("Alt")
        if App._shortcut_modifier_pressed(event, state, 0x0001, 0x10):
            modifiers.append("Shift")

        key_aliases = {
            "Return": "Enter",
            "Escape": "Esc",
            "space": "Space",
        }
        display_key = key_aliases.get(key, key)
        if len(display_key) == 1:
            display_key = display_key.upper()
        return "+".join(modifiers + [display_key])

    @staticmethod
    def _shortcut_modifier_pressed(event: tk.Event, state: int, state_mask: int, virtual_key: int) -> bool:
        if sys.platform == "win32" and hasattr(event, "serial"):
            try:
                return bool(ctypes.windll.user32.GetAsyncKeyState(virtual_key) & 0x8000)
            except Exception:
                pass
        return bool(state & state_mask)

    @staticmethod
    def _shortcut_to_sequence(shortcut: str) -> str | None:
        value = shortcut.strip()
        if not value:
            return None
        if value.startswith("<") and value.endswith(">"):
            value = value[1:-1]
        value = value.replace("+", "-").replace(" ", "")
        parts = [part for part in value.split("-") if part]
        if not parts:
            return None

        modifiers = []
        for part in parts[:-1]:
            lowered = part.lower()
            if lowered in {"ctrl", "control"}:
                modifiers.append("Control")
            elif lowered == "alt":
                modifiers.append("Alt")
            elif lowered == "shift":
                modifiers.append("Shift")
            else:
                modifiers.append(part)

        key = parts[-1]
        key_aliases = {
            "esc": "Escape",
            "escape": "Escape",
            "enter": "Return",
            "return": "Return",
            "space": "space",
        }
        key = key_aliases.get(key.lower(), key)
        if len(key) == 1:
            key = key.lower()
        return f"<{'-'.join(modifiers + [key])}>"

    @staticmethod
    def _sequence_to_display(sequence: str) -> str:
        value = sequence.strip("<>")
        value = value.replace("Control", "Ctrl")
        return value.replace("-", "+")

    def _apply_theme(self) -> None:
        palette = self._theme_palette()

        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        self.configure(bg=palette["bg"])
        self.root_frame.configure(background=palette["bg"])
        self.style.configure(".", background=palette["bg"], foreground=palette["fg"], fieldbackground=palette["field"])
        self.style.configure("TFrame", background=palette["bg"])
        self.style.configure("TLabel", background=palette["bg"], foreground=palette["fg"])
        self.style.configure(
            "Credit.TLabel",
            background=palette["bg"],
            foreground=palette["disabled_fg"],
            font=("Segoe UI", 8),
        )
        self.style.configure("TLabelFrame", background=palette["bg"], foreground=palette["fg"])
        self.style.configure("TLabelFrame.Label", background=palette["bg"], foreground=palette["fg"])
        self.style.configure(
            "PrimarySection.TLabelframe",
            background=palette["bg"],
            foreground=palette["fg"],
        )
        self.style.configure(
            "PrimarySection.TLabelframe.Label",
            background=palette["bg"],
            foreground=palette["fg"],
            font=self.section_heading_font,
        )
        self.style.configure(
            "TrackChannel.TLabelframe",
            background=palette["bg"],
            foreground=palette["fg"],
        )
        self.style.configure(
            "TrackChannel.TLabelframe.Label",
            background=palette["bg"],
            foreground=palette["fg"],
        )
        self.style.configure("TCheckbutton", background=palette["bg"], foreground=palette["fg"])
        self.style.configure("TButton", background=palette["panel"], foreground=palette["fg"])
        self.style.map(
            "TButton",
            background=[
                ("disabled", palette["bg"]),
                ("pressed", palette["select"]),
                ("active", palette["field"]),
            ],
            foreground=[
                ("disabled", palette["disabled_fg"]),
                ("pressed", "#ffffff"),
            ],
        )
        self.style.configure(
            "ActiveAction.TButton",
            background=palette["select"],
            foreground="#ffffff",
        )
        self.style.map(
            "ActiveAction.TButton",
            background=[
                ("disabled", palette["bg"]),
                ("pressed", palette["select"]),
                ("active", palette["select"]),
                ("!disabled", palette["select"]),
            ],
            foreground=[
                ("disabled", palette["disabled_fg"]),
                ("!disabled", "#ffffff"),
            ],
        )
        self.style.configure(
            "DisabledAction.TButton",
            background=palette["bg"],
            foreground=palette["disabled_fg"],
        )
        self.style.map(
            "DisabledAction.TButton",
            background=[("disabled", palette["bg"])],
            foreground=[("disabled", palette["disabled_fg"])],
        )
        self.style.configure("TEntry", fieldbackground=palette["field"], foreground=palette["fg"])
        self.style.configure(
            "DuplicateKeyBinding.TEntry",
            fieldbackground="#fee2e2",
            foreground="#991b1b",
            insertcolor="#991b1b",
        )
        self.style.map(
            "DuplicateKeyBinding.TEntry",
            fieldbackground=[("readonly", "#fee2e2")],
            foreground=[("readonly", "#991b1b")],
        )
        self.style.configure("TSpinbox", fieldbackground=palette["field"], foreground=palette["fg"])
        self.style.configure(
            "TCombobox",
            background=palette["panel"],
            fieldbackground=palette["field"],
            foreground=palette["fg"],
            arrowcolor=palette["fg"],
        )
        self.style.map(
            "TCombobox",
            fieldbackground=[("readonly", palette["field"])],
            selectbackground=[("readonly", palette["field"])],
            selectforeground=[("readonly", palette["fg"])],
        )
        self.style.configure(
            "Horizontal.TScale",
            background=palette["bg"],
            troughcolor=palette["track"],
            lightcolor=palette["track"],
            darkcolor=palette["track"],
        )
        self.style.configure(
            "TScrollbar",
            background=palette["track"],
            troughcolor=palette["field"],
            bordercolor=palette["field"],
            arrowcolor=palette["fg"],
            lightcolor=palette["track"],
            darkcolor=palette["track"],
        )
        self.style.configure(
            "MidiList.Vertical.TScrollbar",
            background=palette["track"],
            troughcolor=palette["field"],
            bordercolor=palette["field"],
            arrowcolor=palette["fg"],
            lightcolor=palette["track"],
            darkcolor=palette["track"],
        )
        self.style.map(
            "TScrollbar",
            background=[("active", palette["select"]), ("pressed", palette["select"])],
            arrowcolor=[("active", "#ffffff"), ("pressed", "#ffffff")],
        )
        self.style.map(
            "MidiList.Vertical.TScrollbar",
            background=[("active", palette["track"]), ("pressed", palette["select"])],
            arrowcolor=[("active", palette["fg"]), ("pressed", "#ffffff")],
        )
        self.style.layout(
            "Borderless.TNotebook",
            [("Notebook.client", {"sticky": "nswe", "border": "0"})],
        )
        self.style.configure(
            "Borderless.TNotebook",
            background=palette["bg"],
            foreground=palette["fg"],
            borderwidth=0,
            relief=tk.FLAT,
        )
        self.style.configure(
            "Borderless.TNotebook.Tab",
            background=palette["panel"],
            foreground=palette["fg"],
            borderwidth=0,
            relief=tk.FLAT,
        )
        self.style.map(
            "Borderless.TNotebook.Tab",
            background=[("selected", palette["field"])],
        )
        self.style.configure(
            "Treeview",
            background=palette["field"],
            fieldbackground=palette["field"],
            foreground=palette["fg"],
            borderwidth=0,
            relief=tk.FLAT,
        )
        self.style.layout(
            "Treeview",
            [("Treeview.treearea", {"sticky": "nswe"})],
        )
        self.style.configure("Treeview.Heading", background=palette["panel"], foreground=palette["fg"])
        self.style.map("Treeview", background=[("selected", palette["select"])], foreground=[("selected", "#ffffff")])

        self.log_text.configure(
            background=palette["field"],
            foreground=palette["fg"],
            insertbackground=palette["fg"],
            selectbackground=palette["select"],
            selectforeground="#ffffff",
        )
        self.channel_box.configure(
            background=palette["bg"],
            highlightbackground=palette["panel"],
            highlightcolor=palette["panel"],
        )
        self.channel_canvas.configure(background=palette["bg"])
        self.channel_frame.configure(background=palette["track"])
        self.shortcut_settings.configure(
            background=palette["bg"],
            highlightbackground=palette["panel"],
            highlightcolor=palette["panel"],
        )
        self.countdown_settings.configure(
            background=palette["bg"],
            highlightbackground=palette["panel"],
            highlightcolor=palette["panel"],
        )
        self.performance_optimization_settings.configure(
            background=palette["bg"],
            highlightbackground=palette["panel"],
            highlightcolor=palette["panel"],
        )
        about_window = self.__dict__.get("about_window")
        if about_window is not None and about_window.winfo_exists():
            about_window.configure(background=palette["bg"])
        for check in (
            self.auto_fit_note_range_check,
            self.dry_run_check,
            self.countdown_sound_check,
            self.game_countdown_sound_check,
            self.humanize_timing_check,
            self.chord_strum_check,
            self.repeat_prevention_check,
            self.shortcut_lock_check,
        ):
            self._style_checkbutton(check, palette)
        self._style_chord_optimization_control(palette)
        self._style_channel_grid_widgets(self.channel_frame, palette)
        self.__dict__.pop("_midi_scrollbar_heading_bottom", None)
        self.after_idle(self._align_midi_scrollbar)

    def _style_checkbutton(self, check: tk.Checkbutton, palette: dict[str, str] | None = None) -> None:
        if palette is None:
            palette = self._theme_palette()
        check.configure(
            background=palette["bg"],
            foreground=palette["fg"],
            disabledforeground=palette["disabled_fg"],
            activebackground=palette["bg"],
            activeforeground=palette["fg"],
            selectcolor=palette["field"],
            highlightthickness=0,
            relief=tk.FLAT,
        )

    def _style_chord_optimization_control(
        self,
        palette: dict[str, str] | None = None,
    ) -> None:
        if palette is None:
            palette = self._theme_palette()
        self._style_checkbutton(self.chord_optimization_check, palette)
        self.chord_optimization_control.configure(background=palette["panel"])
        self.chord_optimization_label.configure(
            background=palette["panel"],
            foreground=palette["fg"],
            activebackground=palette["field"],
            activeforeground=palette["fg"],
        )

    def _style_channel_label(
        self,
        label: tk.Label,
        palette: dict[str, str] | None = None,
    ) -> None:
        if palette is None:
            palette = self._theme_palette()
        label.configure(
            background=palette["bg"],
            foreground=palette["fg"],
            highlightbackground=palette["track"],
        )

    def _style_channel_header_label(
        self,
        label: tk.Label,
        palette: dict[str, str] | None = None,
    ) -> None:
        if palette is None:
            palette = self._theme_palette()
        label.configure(
            background=palette["panel"],
            foreground=palette["fg"],
            highlightbackground=palette["track"],
        )

    def _style_channel_row(
        self,
        row: tk.Frame,
        variable: tk.BooleanVar,
        palette: dict[str, str] | None = None,
    ) -> None:
        if palette is None:
            palette = self._theme_palette()
        enabled = variable.get()
        background = palette["select"] if enabled else palette["bg"]
        foreground = "#ffffff" if enabled else palette["fg"]
        row.configure(background=background)
        for child in row.winfo_children():
            if isinstance(child, tk.Label):
                child.configure(
                    background=background,
                    foreground=foreground,
                    highlightbackground=palette["track"],
                )

    def _style_channel_cell(
        self,
        cell: tk.Frame,
        palette: dict[str, str] | None = None,
    ) -> None:
        if palette is None:
            palette = self._theme_palette()
        cell.configure(
            background=palette["bg"],
            highlightbackground=palette["track"],
            highlightcolor=palette["track"],
        )

    def _style_channel_grid_widgets(
        self,
        widget: tk.Widget,
        palette: dict[str, str],
    ) -> None:
        for child in widget.winfo_children():
            if isinstance(child, tk.Checkbutton):
                self._style_checkbutton(child, palette)
            elif isinstance(child, tk.Label):
                self._style_channel_header_label(child, palette)
            elif isinstance(child, tk.Frame):
                variable = getattr(child, "_channel_var", None)
                if isinstance(variable, tk.BooleanVar):
                    self._style_channel_row(child, variable, palette)
                else:
                    self._style_channel_cell(child, palette)
                    self._style_channel_grid_widgets(child, palette)

    def _theme_palette(self) -> dict[str, str]:
        palettes = {
            "light": {
                "bg": "#f3f4f6",
                "panel": "#e5e7eb",
                "field": "#ffffff",
                "track": "#cbd5e1",
                "fg": "#111827",
                "muted": "#4b5563",
                "disabled_bg": "#94a3b8",
                "disabled_fg": "#334155",
                "select": "#2563eb",
            },
            "dark": {
                "bg": "#111827",
                "panel": "#1f2937",
                "field": "#0b1220",
                "track": "#334155",
                "fg": "#e5e7eb",
                "muted": "#9ca3af",
                "disabled_bg": "#111827",
                "disabled_fg": "#4b5563",
                "select": "#2563eb",
            },
            "green": {
                "bg": "#eef7f0",
                "panel": "#d8eadc",
                "field": "#ffffff",
                "track": "#9fc7ab",
                "fg": "#10291a",
                "muted": "#496455",
                "disabled_bg": "#98b8a2",
                "disabled_fg": "#355442",
                "select": "#15803d",
            },
            "yellow": {
                "bg": "#f8f6e7",
                "panel": "#ebe5bf",
                "field": "#fffdf2",
                "track": "#d1bf63",
                "fg": "#2c260d",
                "muted": "#665c2f",
                "disabled_bg": "#b8aa6b",
                "disabled_fg": "#564b20",
                "select": "#b45309",
            },
            "blue": {
                "bg": "#eef5fb",
                "panel": "#d8e6f2",
                "field": "#ffffff",
                "track": "#9db9d4",
                "fg": "#102033",
                "muted": "#4b6075",
                "disabled_bg": "#94a9bd",
                "disabled_fg": "#33485c",
                "select": "#2563eb",
            },
            "sky_blue": {
                "bg": "#e8faff",
                "panel": "#bcefff",
                "field": "#ffffff",
                "track": "#84dfff",
                "fg": "#083344",
                "muted": "#276174",
                "disabled_bg": "#8ecfe3",
                "disabled_fg": "#2d6476",
                "select": "#0284c7",
            },
            "red": {
                "bg": "#fbf0f1",
                "panel": "#efd7da",
                "field": "#ffffff",
                "track": "#d6a0a8",
                "fg": "#301317",
                "muted": "#70474d",
                "disabled_bg": "#bf9aa0",
                "disabled_fg": "#62343a",
                "select": "#dc2626",
            },
            "pink": {
                "bg": "#fbf0f7",
                "panel": "#f1d5e7",
                "field": "#fff7fb",
                "track": "#dda4c6",
                "fg": "#301322",
                "muted": "#70445e",
                "disabled_bg": "#c69ab5",
                "disabled_fg": "#63314c",
                "select": "#db2777",
            },
            "orange": {
                "bg": "#fbf3ea",
                "panel": "#efdcc5",
                "field": "#fffaf4",
                "track": "#d7ae7b",
                "fg": "#301d0c",
                "muted": "#6b5236",
                "disabled_bg": "#bfa17d",
                "disabled_fg": "#604425",
                "select": "#ea580c",
            },
        }
        return palettes.get(self.color_theme, palettes["sky_blue"])

    def _apply_always_on_top(self) -> None:
        self.attributes("-topmost", bool(self.always_on_top_var.get()))

    def _apply_window_opacity(self) -> None:
        opacity = self._read_int_var(self.window_opacity_var, minimum=30, maximum=100, default=100)
        if "opacity_value_label" in self.__dict__:
            self.opacity_value_label.configure(text=f"{opacity}%")
        self.attributes("-alpha", opacity / 100)

    def _update_opacity_label(self) -> None:
        opacity = self._read_int_var(self.window_opacity_var, minimum=30, maximum=100, default=100)
        if "opacity_value_label" in self.__dict__:
            self.opacity_value_label.configure(text=f"{opacity}%")

    def _enabled_channels(self) -> set[int]:
        snapshot = self.__dict__.get("enabled_channels_snapshot")
        if snapshot is not None:
            return set(snapshot)
        return {channel for channel, var in self.channel_vars.items() if var.get()}

    def _enabled_sources(self) -> set[tuple[int, int]]:
        snapshot = self.__dict__.get("enabled_sources_snapshot")
        if snapshot is not None:
            return set(snapshot)
        track_channel_vars = self.__dict__.get("track_channel_vars", {})
        if track_channel_vars:
            return {
                source for source, var in track_channel_vars.items() if var.get()
            }
        enabled_channels = self._enabled_channels()
        return {
            (event.track, event.channel)
            for event in self.events
            if (
                event.track is not None
                and event.channel is not None
                and event.channel in enabled_channels
            )
        }

    def _event_source_is_enabled(self, event: MidiEvent) -> bool:
        if event.channel is None:
            return False
        if (
            event.track is not None
            and "enabled_sources_snapshot" in self.__dict__
        ):
            return (event.track, event.channel) in self._enabled_sources()
        return event.channel in self._enabled_channels()

    def _has_enabled_events(self, events: list[MidiEvent]) -> bool:
        return any(self._event_source_is_enabled(event) for event in events)

    @staticmethod
    def _play_countdown_sound(remaining: int) -> None:
        frequency = 1040 if remaining == 1 else 780
        winsound.Beep(frequency, 120)

    def _countdown_tick_enabled(self) -> bool:
        countdown_sound = self.__dict__.get("countdown_sound_var")
        game_countdown_sound = self.__dict__.get("game_countdown_sound_var")
        return bool(
            (countdown_sound is not None and countdown_sound.get())
            or (game_countdown_sound is not None and game_countdown_sound.get())
        )

    def _play_countdown_tick(self, remaining: int) -> None:
        self._log_from_worker(f"Countdown: {remaining}")
        if self.countdown_sound_var.get():
            self._play_countdown_sound(remaining)
        if not self.game_countdown_sound_var.get():
            return
        player = self.__dict__.get("player")
        output = getattr(player, "output", None)
        if output is None:
            return
        key = self._current_key_bindings()[48]
        self._tap_countdown_game_key(output, key)
        self._log_from_worker(f"Countdown game key: {key}")

    @staticmethod
    def _tap_countdown_game_key(output: KeyboardOutput, key: str) -> None:
        output.press(key)
        try:
            time.sleep(GAME_COUNTDOWN_KEY_HOLD_SECONDS)
        finally:
            output.release(key)

    def _log_from_worker(self, message: str) -> None:
        log_queue = self.__dict__.get("log_queue")
        if log_queue is not None:
            log_queue.put(message)

    def _next_playback_id(self) -> int:
        self.playback_id += 1
        return self.playback_id

    def _parse_player_message(self, message: str, prefix: str) -> tuple[int, str] | None:
        payload = message.removeprefix(prefix)
        try:
            playback_id_text, value = payload.split("__", 1)
            playback_id = int(playback_id_text)
        except ValueError:
            return None
        if playback_id != self.playback_id:
            return None
        return playback_id, value


def main() -> None:
    single_instance = SingleInstance(APP_WINDOW_TITLE)
    if not single_instance.is_primary:
        single_instance.notify_existing()
        single_instance.close()
        return

    try:
        app = App(single_instance=single_instance)
        app.mainloop()
    finally:
        single_instance.close()


if __name__ == "__main__":
    main()
