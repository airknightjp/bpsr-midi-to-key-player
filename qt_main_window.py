from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QActionGroup, QCloseEvent, QDesktopServices, QIcon, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QTabBar,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app_controller import AppController, UI_SCALE_PERCENT_OPTIONS
from app_state import AppState
from config import BASE_NOTE_MAX, BASE_NOTE_MIN, NOTE_NAMES, SUPPORTED_BINDING_KEYS
from i18n import COLOR_THEME_NAMES, LANGUAGE_NAMES, TEXT
from qt_components import (
    DoubleClickLabel,
    SectionPanel,
    ReadableSpinBox,
    SeekSlider,
    ShortcutCaptureEdit,
    ThemedBackground,
    TrackChannelTable,
    VerticalValueSlider,
    make_refresh_icon,
)
from qt_styles import THEMES, build_stylesheet, register_windows_fonts


APP_VERSION = "1.2.0"
PROJECT_URL = "https://github.com/airknightjp/bpsr-midi-to-key-player"


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


class MidiMainWindow(QMainWindow):
    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self.controller = controller
        register_windows_fonts()
        self.state = controller.state
        self._rendering = False
        self._closing_for_exit = False
        self._last_language = ""
        self._last_theme = ""
        self._applied_scale = 0
        self._applied_always_on_top: bool | None = None
        self._applied_section_visibility: tuple[bool, ...] | None = None
        self._section_heights: dict[str, int] = {}
        self._full_visibility_height: int | None = None
        self._last_rows_signature: tuple[tuple[str, str, str], ...] = ()
        self._last_sources_signature: tuple[tuple[int, int, bool], ...] = ()
        self._build_ui()
        self._create_tray_icon()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(35)
        self._poll_timer.timeout.connect(self.controller.poll)
        self._poll_timer.start()
        self._hotkey_timer = QTimer(self)
        self._hotkey_timer.setInterval(3000)
        self._hotkey_timer.timeout.connect(self.controller.ensure_hotkeys)
        self._hotkey_timer.start()
        self.controller.attach_view(self)

    def _build_ui(self) -> None:
        self.setWindowTitle("BPSR MIDI to KEY Player")
        icon_path = resource_path("assets/app_icon_whale.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        root = ThemedBackground()
        root.setObjectName("AppRoot")
        self.root_background = root
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(0)
        self.root_layout = root_layout
        self.setCentralWidget(root)

        self.realtime_panel = SectionPanel("")
        self._build_realtime_section()
        root_layout.addWidget(self.realtime_panel)
        self.realtime_gap = self._make_gap(12)
        root_layout.addWidget(self.realtime_gap)

        self.key_panel = SectionPanel("")
        self._build_key_section()
        root_layout.addWidget(self.key_panel)
        self.key_gap = self._make_gap(12)
        root_layout.addWidget(self.key_gap)

        self.settings_panel = QWidget()
        self.settings_panel.setObjectName("SettingsPanel")
        self.settings_layout = QVBoxLayout(self.settings_panel)
        self.settings_layout.setContentsMargins(10, 10, 10, 10)
        self.settings_layout.setSpacing(0)
        self._build_settings_section()
        root_layout.addWidget(self.settings_panel)
        self.settings_gap = self._make_gap(6)
        root_layout.addWidget(self.settings_gap)

        self.player_panel = QWidget()
        self.player_layout = QVBoxLayout(self.player_panel)
        self.player_layout.setContentsMargins(0, 0, 0, 0)
        self.player_layout.setSpacing(0)
        self._build_player_section()
        root_layout.addWidget(self.player_panel, 1)

    @staticmethod
    def _make_gap(height: int) -> QWidget:
        gap = QWidget()
        gap.setFixedHeight(height)
        return gap

    def _build_realtime_section(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(0)
        self.realtime_row = row
        self.realtime_button = QPushButton()
        self.realtime_button.setFixedWidth(126)
        self.realtime_button.clicked.connect(self.controller.toggle_midi_input)
        row.addWidget(self.realtime_button)
        self.device_label = QLabel()
        self.device_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(14)
        row.addWidget(self.device_label)
        row.addSpacing(6)
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(288)
        self.device_combo.currentTextChanged.connect(
            lambda value: self._set_option("midi_input_device", value)
        )
        row.addWidget(self.device_combo, 1)
        row.addSpacing(8)
        self.device_refresh_button = QToolButton()
        self.device_refresh_button.setObjectName("RefreshButton")
        self.device_refresh_button.setToolTip("Refresh MIDI devices")
        self.device_refresh_button.clicked.connect(self.controller.refresh_midi_input_devices)
        row.addWidget(self.device_refresh_button)
        self.realtime_panel.body_layout.addLayout(row)

    def _build_key_section(self) -> None:
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(0)
        grid.setVerticalSpacing(0)
        self.key_grid = grid
        self.keyboard_play_button = QPushButton()
        self.keyboard_play_button.setMinimumSize(126, 62)
        self.keyboard_play_button.clicked.connect(self.controller.toggle_keyboard_playback)
        grid.addWidget(self.keyboard_play_button, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        grid.setColumnMinimumWidth(0, 126)
        grid.setColumnMinimumWidth(1, 14)

        self.countdown_label = QLabel()
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.countdown_spin = ReadableSpinBox()
        self.countdown_spin.setRange(0, 10)
        self.countdown_spin.setMaximumWidth(70)
        self.countdown_spin.valueChanged.connect(lambda value: self._set_option("countdown_seconds", value))
        self.seconds_label = QLabel()
        self.countdown_sound_check = QCheckBox()
        self.countdown_sound_check.toggled.connect(lambda value: self._set_option("countdown_sound", value))
        self.game_sound_check = QCheckBox()
        self.game_sound_check.toggled.connect(lambda value: self._set_option("game_countdown_sound", value))
        self.countdown_group = QFrame()
        self.countdown_group.setProperty("subgroup", True)
        countdown = QHBoxLayout(self.countdown_group)
        countdown.setContentsMargins(6, 4, 6, 4)
        countdown.setSpacing(0)
        self.countdown_group_layout = countdown
        countdown.addWidget(self.countdown_spin)
        countdown.addSpacing(2)
        countdown.addWidget(self.seconds_label)
        countdown.addSpacing(6)
        countdown.addWidget(self.countdown_sound_check)
        countdown.addSpacing(6)
        countdown.addWidget(self.game_sound_check)
        grid.addWidget(self.countdown_label, 0, 2)
        grid.setColumnMinimumWidth(3, 6)
        grid.addWidget(self.countdown_group, 0, 4, Qt.AlignmentFlag.AlignLeft)
        grid.setColumnStretch(4, 1)

        self.shortcut_caption = QLabel()
        self.shortcut_start_label = QLabel()
        self.shortcut_start_edit = ShortcutCaptureEdit()
        self.shortcut_start_edit.shortcutCaptured.connect(
            lambda value: self._set_option("keyboard_play_shortcut", value)
        )
        self.shortcut_pause_label = QLabel()
        self.shortcut_pause_edit = ShortcutCaptureEdit()
        self.shortcut_pause_edit.shortcutCaptured.connect(
            lambda value: self._set_option("keyboard_pause_shortcut", value)
        )
        self.shortcut_end_label = QLabel()
        self.shortcut_end_edit = ShortcutCaptureEdit()
        self.shortcut_end_edit.shortcutCaptured.connect(
            lambda value: self._set_option("keyboard_stop_shortcut", value)
        )
        self.shortcut_lock_check = QCheckBox()
        self.shortcut_lock_check.toggled.connect(lambda value: self._set_option("shortcut_locked", value))
        self.shortcut_caption.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.shortcut_group = QFrame()
        self.shortcut_group.setProperty("subgroup", True)
        shortcuts = QHBoxLayout(self.shortcut_group)
        shortcuts.setContentsMargins(6, 4, 6, 4)
        shortcuts.setSpacing(0)
        self.shortcut_group_layout = shortcuts
        shortcuts.addWidget(self.shortcut_start_label)
        shortcuts.addSpacing(2)
        shortcuts.addWidget(self.shortcut_start_edit)
        shortcuts.addSpacing(6)
        shortcuts.addWidget(self.shortcut_pause_label)
        shortcuts.addSpacing(2)
        shortcuts.addWidget(self.shortcut_pause_edit)
        shortcuts.addSpacing(6)
        shortcuts.addWidget(self.shortcut_end_label)
        shortcuts.addSpacing(2)
        shortcuts.addWidget(self.shortcut_end_edit)
        shortcuts.addSpacing(6)
        shortcuts.addWidget(self.shortcut_lock_check)
        grid.setColumnMinimumWidth(5, 10)
        grid.addWidget(self.shortcut_caption, 0, 6)
        grid.setColumnMinimumWidth(7, 4)
        grid.addWidget(self.shortcut_group, 0, 8, Qt.AlignmentFlag.AlignRight)

        self.key_panel.body_layout.addLayout(grid)

    def _build_settings_section(self) -> None:
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(0)
        self.settings_grid = grid
        self.common_caption = QLabel()
        self.common_caption.setProperty("caption", True)
        self.performance_caption = QLabel()
        self.performance_caption.setProperty("caption", True)
        grid.addWidget(self.common_caption, 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        grid.addWidget(self.performance_caption, 0, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.dry_run_check = self._option_check("dry_run")
        self.auto_fit_check = self._option_check("auto_fit_note_range")
        self.repeat_check = self._option_check("repeat_prevention")
        self.humanize_check = self._option_check("humanize_timing")
        self.strum_check = self._option_check("chord_strum")
        self.optimization_check = self._option_check("chord_optimization")
        for row, widget in enumerate((self.dry_run_check, self.auto_fit_check, self.repeat_check), 1):
            widget.setProperty("settingsItem", True)
            grid.addWidget(widget, row, 0)
        for row, widget in enumerate((self.humanize_check, self.strum_check, self.optimization_check), 1):
            widget.setProperty("settingsItem", True)
            grid.addWidget(widget, row, 1)
        grid.setColumnStretch(2, 1)
        self.settings_layout.addLayout(grid)

    def _option_check(self, name: str) -> QCheckBox:
        check = QCheckBox()
        check.toggled.connect(lambda value, option=name: self._set_option(option, value))
        return check

    def _build_player_section(self) -> None:
        status_box = QWidget()
        status_row = QGridLayout(status_box)
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setHorizontalSpacing(0)
        status_row.setVerticalSpacing(0)
        self.status_layout = status_row
        self.status_label = QLabel("waiting..")
        status_row.addWidget(self.status_label, 0, 0, 1, 4)
        self.position_label = DoubleClickLabel()
        self.position_label.doubleClicked.connect(lambda: self.controller.seek(0.0))
        self.position_slider = SeekSlider()
        self.position_slider.setRange(0, 1000)
        self.position_slider.seekRequested.connect(self._seek_from_slider)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self.position_label, 1, 0)
        status_row.addWidget(self.position_slider, 1, 2)
        status_row.addWidget(self.time_label, 1, 3)
        status_row.setColumnStretch(2, 1)
        self.player_layout.addWidget(status_box)
        self.player_body_gap = self._make_gap(12)
        self.player_layout.addWidget(self.player_body_gap)

        body = QHBoxLayout()
        body.setSpacing(0)
        self.player_body_layout = body
        self.slider_pane = QWidget()
        slider_layout = QHBoxLayout(self.slider_pane)
        slider_layout.setContentsMargins(0, 0, 0, 0)
        slider_layout.setSpacing(0)
        self.slider_layout = slider_layout
        self.volume_control = VerticalValueSlider(0, 100, 80)
        self.volume_control.valueChanged.connect(lambda value: self._set_option("midi_sound_volume", value))
        self.volume_control.resetRequested.connect(lambda: self._set_option("midi_sound_volume", 100))
        slider_layout.addWidget(self.volume_control)
        self.speed_control = VerticalValueSlider(10, 200, 100)
        self.speed_control.valueChanged.connect(lambda value: self._set_option("playback_speed_percent", value))
        self.speed_control.resetRequested.connect(lambda: self._set_option("playback_speed_percent", 100))
        slider_layout.addWidget(self.speed_control)
        body.addWidget(self.slider_pane)
        self.slider_track_gap = QWidget()
        self.slider_track_gap.setFixedWidth(6)
        body.addWidget(self.slider_track_gap)
        self.track_channels = TrackChannelTable()
        self.track_channels.sourceToggled.connect(self.controller.toggle_track_channel)
        self.track_channels.allEnabledRequested.connect(self.controller.enable_all_track_channels)
        self.track_channel_container = QWidget()
        self.track_channel_container.setFixedWidth(28)
        track_channel_layout = QVBoxLayout(self.track_channel_container)
        track_channel_layout.setContentsMargins(0, 1, 0, 0)
        track_channel_layout.setSpacing(0)
        self.track_channel_layout = track_channel_layout
        track_channel_layout.addWidget(self.track_channels)
        body.addWidget(self.track_channel_container)
        self.player_detail_gap = self._make_gap(2)
        body.addWidget(self.player_detail_gap)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(0, 0, 0, 0)
        tab_row.setSpacing(0)
        self.tab_row = tab_row
        self.tab_bar = QTabBar()
        self.tab_bar.setDrawBase(False)
        self.tab_bar.setExpanding(False)
        self.tab_bar.currentChanged.connect(self._change_player_page)
        self.tab_bar.tabBarDoubleClicked.connect(self._player_tab_double_clicked)
        self.tab_bar_container = QWidget()
        tab_bar_container_layout = QVBoxLayout(self.tab_bar_container)
        tab_bar_container_layout.setContentsMargins(0, 1, 0, 0)
        tab_bar_container_layout.setSpacing(0)
        tab_bar_container_layout.addWidget(self.tab_bar)
        self.tab_bar_container_layout = tab_bar_container_layout
        tab_row.addWidget(self.tab_bar_container)
        tab_row.addSpacing(8)
        self.transpose_label = QLabel()
        self.transpose_spin = ReadableSpinBox()
        self.transpose_spin.setRange(-12, 12)
        self.transpose_spin.setMaximumWidth(70)
        self.transpose_spin.valueChanged.connect(lambda value: self._set_option("transpose_semitones", value))
        self.octave_label = QLabel()
        self.octave_spin = ReadableSpinBox()
        self.octave_spin.setRange(-3, 3)
        self.octave_spin.setMaximumWidth(66)
        self.octave_spin.valueChanged.connect(lambda value: self._set_option("octave_shift", value))
        self.transform_controls = QWidget()
        transform_layout = QHBoxLayout(self.transform_controls)
        transform_layout.setContentsMargins(0, 0, 0, 2)
        transform_layout.setSpacing(0)
        self.transform_layout = transform_layout
        self.transpose_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.octave_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        transform_layout.addWidget(self.transpose_label)
        transform_layout.addSpacing(4)
        transform_layout.addWidget(self.transpose_spin)
        transform_layout.addSpacing(12)
        transform_layout.addWidget(self.octave_label)
        transform_layout.addSpacing(4)
        transform_layout.addWidget(self.octave_spin)
        tab_row.addWidget(self.transform_controls, 0, Qt.AlignmentFlag.AlignTop)
        tab_row.addStretch(1)
        content_layout.addLayout(tab_row)

        self.player_stack = QStackedWidget()
        self.midi_table = QTableWidget(0, 3)
        self.midi_table.setAlternatingRowColors(True)
        self.midi_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.midi_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.midi_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.midi_table.verticalHeader().hide()
        self.midi_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.midi_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.midi_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.midi_table.setColumnWidth(1, 82)
        self.midi_table.setColumnWidth(2, 92)
        self.midi_table.itemSelectionChanged.connect(self._midi_selection_changed)
        self.midi_table.itemDoubleClicked.connect(lambda _item: self.controller.toggle_sound_playback())
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.player_stack.addWidget(self.midi_table)
        self.player_stack.addWidget(self.log_output)
        content_layout.addWidget(self.player_stack, 1)
        body.addWidget(content, 1)
        self.player_layout.addLayout(body, 1)

    def _create_tray_icon(self) -> None:
        self.tray_icon = QSystemTrayIcon(self.windowIcon(), self)
        tray_menu = QMenu(self)
        show_action = tray_menu.addAction("BPSR MIDI to KEY Player")
        show_action.triggered.connect(self._restore_from_tray)
        tray_menu.addSeparator()
        exit_action = tray_menu.addAction("Exit")
        exit_action.triggered.connect(self.exit_application)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(
            lambda reason: self._restore_from_tray()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick
            else None
        )

    def render(self, state: AppState) -> None:
        self.state = state
        self._rendering = True
        try:
            if state.language != self._last_language:
                self._apply_text(state)
                self._build_menus(state)
                self._last_language = state.language
            if state.color_theme != self._last_theme or state.ui_scale_percent != self._applied_scale:
                old_scale = self._applied_scale or state.ui_scale_percent
                self.setStyleSheet(build_stylesheet(state.color_theme, state.ui_scale_percent))
                self._apply_layout_scale(state.ui_scale_percent)
                self._apply_theme_assets(state.color_theme, state.ui_scale_percent)
                if self._applied_scale and old_scale != state.ui_scale_percent:
                    ratio = state.ui_scale_percent / old_scale
                    self.resize(round(self.width() * ratio), round(self.height() * ratio))
                    if self._full_visibility_height is not None:
                        self._full_visibility_height = round(self._full_visibility_height * ratio)
                    for name, height in tuple(self._section_heights.items()):
                        self._section_heights[name] = max(1, round(height * ratio))
                    self.controller.set_window_geometry(self.width(), self.height())
                self._last_theme = state.color_theme
                self._applied_scale = state.ui_scale_percent
            self.setWindowOpacity(state.window_opacity / 100)
            if state.always_on_top != self._applied_always_on_top:
                was_visible = self.isVisible()
                self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, state.always_on_top)
                self._applied_always_on_top = state.always_on_top
                if was_visible:
                    self.show()
            self._apply_section_visibility(state)
            self._render_realtime(state)
            self._render_key_section(state)
            self._render_settings(state)
            self._render_player(state)
        finally:
            self._rendering = False

    def _apply_text(self, state: AppState) -> None:
        text = TEXT[state.language]
        self.setWindowTitle(text["title"])
        self.realtime_panel.set_title(text["midi_input_settings"])
        self.key_panel.set_title(text["key_playback_settings"])
        self.device_label.setText(text["midi_input_device"])
        self.countdown_label.setText(text["countdown"])
        self.seconds_label.setText(text["seconds_unit"])
        self.countdown_sound_check.setText(text["countdown_sound"])
        self.game_sound_check.setText(text["game_countdown_sound"])
        self.shortcut_caption.setText(text["shortcut_settings"])
        self.shortcut_start_label.setText(text["shortcut_start"])
        self.shortcut_pause_label.setText(text["shortcut_pause_resume"])
        self.shortcut_end_label.setText(text["shortcut_end"])
        self.shortcut_lock_check.setText(text["shortcut_lock"])
        self.common_caption.setText(text["common_settings_label"])
        self.performance_caption.setText(text["performance_optimization_settings"])
        self.dry_run_check.setText(text["dry_run"])
        self.auto_fit_check.setText(text["auto_fit_note_range"])
        self.repeat_check.setText(text["repeat_prevention"])
        self.humanize_check.setText(text["humanize_timing"])
        self.strum_check.setText(text["chord_strum"])
        self.optimization_check.setText(text["chord_optimization"])
        self.position_label.setText(text["playback_position"])
        self.volume_control.label.setText(self._vertical_label_text(text["midi_sound_volume"]))
        self.speed_control.label.setText(self._vertical_label_text(text["playback_speed"]))
        self.transpose_label.setText(text["transpose_semitones"])
        self.octave_label.setText(text["octave_shift"])
        while self.tab_bar.count():
            self.tab_bar.removeTab(0)
        self.tab_bar.addTab(text["midi_list"])
        self.tab_bar.addTab(text["playback_log"])
        self._update_midi_tab_icon(state.color_theme, state.ui_scale_percent)
        self.midi_table.setHorizontalHeaderLabels([text["name"], text["duration"], text["note_range"]])
        for column in range(self.midi_table.columnCount()):
            self.midi_table.horizontalHeaderItem(column).setTextAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )

    @staticmethod
    def _vertical_label_text(value: str) -> str:
        return "\n".join(character for character in value if not character.isspace())

    def _apply_layout_scale(self, percent: int) -> None:
        scale = percent / 100.0
        px = lambda value: max(1, round(value * scale))
        margin = px(12)
        self.root_layout.setContentsMargins(margin, margin, margin, margin)
        self.realtime_panel.apply_scale(scale)
        self.key_panel.apply_scale(scale)
        self.realtime_panel.setFixedHeight(px(57))
        self.key_panel.setFixedHeight(px(67))
        self.settings_panel.setFixedHeight(px(83))
        settings_margin = px(10)
        self.settings_layout.setContentsMargins(
            settings_margin,
            max(0, settings_margin - 1),
            settings_margin,
            settings_margin,
        )
        self.settings_grid.setRowMinimumHeight(
            0,
            max(self.common_caption.sizeHint().height(), self.performance_caption.sizeHint().height()) + 1,
        )
        self.realtime_button.setFixedWidth(px(126))
        self.device_label.setFixedWidth(px(76))
        self.device_combo.setMinimumWidth(px(288))
        self.device_refresh_button.setFixedWidth(px(34))
        self.keyboard_play_button.setFixedSize(px(126), px(62))
        self.countdown_label.setFixedWidth(px(76))
        self.countdown_spin.setFixedWidth(px(70))
        shortcut_width = self._shortcut_edit_width(scale)
        self.shortcut_start_edit.setFixedWidth(shortcut_width)
        self.shortcut_pause_edit.setFixedWidth(shortcut_width)
        self.shortcut_end_edit.setFixedWidth(shortcut_width)
        self.countdown_group_layout.setContentsMargins(px(6), px(4), px(6), px(4))
        self.shortcut_group_layout.setContentsMargins(px(6), px(4), px(6), px(4))
        for column, width in ((0, 126), (1, 8), (3, 6), (5, 10), (7, 4)):
            self.key_grid.setColumnMinimumWidth(column, px(width))
        self.settings_grid.setHorizontalSpacing(px(8))
        self.status_layout.setVerticalSpacing(px(6))
        self.status_layout.setColumnMinimumWidth(1, px(6))
        self.position_slider.setFixedHeight(px(16))
        self.time_label.setFixedWidth(px(80))
        self.volume_control.apply_scale(scale)
        self.speed_control.apply_scale(scale)
        self.slider_pane.setFixedWidth(px(68))
        self.slider_track_gap.setFixedWidth(px(6))
        self.track_channels.apply_scale(scale)
        self.track_channel_container.setFixedWidth(self.track_channels.width())
        self.track_channel_layout.setContentsMargins(0, px(1), 0, 0)
        tab_header_height = px(28)
        self.tab_bar.setFixedHeight(tab_header_height)
        self.tab_bar_container.setFixedHeight(tab_header_height + 1)
        self.tab_bar_container_layout.setContentsMargins(0, 1, 0, 0)
        self.track_channels.horizontalHeader().setFixedHeight(max(1, tab_header_height - 1))
        self.transform_controls.setFixedHeight(tab_header_height)
        self.transpose_spin.setFixedWidth(px(70))
        self.octave_spin.setFixedWidth(px(66))
        self.transform_layout.setContentsMargins(0, 0, 0, px(2))
        self._set_spacer_width(self.transform_layout, 1, px(4))
        self._set_spacer_width(self.transform_layout, 3, px(12))
        self._set_spacer_width(self.transform_layout, 5, px(4))
        self.player_detail_gap.setFixedWidth(px(2))
        self.midi_table.setColumnWidth(1, px(80))
        self.midi_table.setColumnWidth(2, px(90))
        self.midi_table.horizontalHeader().setFixedHeight(px(24))
        for row in range(self.midi_table.rowCount()):
            self.midi_table.setRowHeight(row, px(22))
        self._set_spacer_width(self.realtime_row, 1, px(8))
        self._set_spacer_width(self.realtime_row, 3, px(6))
        self._set_spacer_width(self.realtime_row, 5, px(8))
        self._set_spacer_width(self.countdown_group_layout, 1, px(2))
        self._set_spacer_width(self.countdown_group_layout, 3, px(6))
        self._set_spacer_width(self.countdown_group_layout, 5, px(6))
        self._set_spacer_width(self.shortcut_group_layout, 1, px(2))
        self._set_spacer_width(self.shortcut_group_layout, 3, px(6))
        self._set_spacer_width(self.shortcut_group_layout, 5, px(2))
        self._set_spacer_width(self.shortcut_group_layout, 7, px(6))
        self._set_spacer_width(self.shortcut_group_layout, 9, px(2))
        self._set_spacer_width(self.shortcut_group_layout, 11, px(6))
        self._set_spacer_width(self.tab_row, 1, px(8))
        self.player_body_gap.setFixedHeight(px(12))
        self._update_section_gaps(self.state)

    def _shortcut_edit_width(self, scale: float) -> int:
        labels = (
            self.shortcut_start_edit.text() or "F9",
            self.shortcut_pause_edit.text() or "F10",
            self.shortcut_end_edit.text() or "F11",
        )
        content_width = max(
            self.shortcut_start_edit.fontMetrics().horizontalAdvance(label)
            for label in labels
        )
        return max(round(48 * scale), content_width + round(22 * scale))

    def _apply_theme_assets(self, theme_name: str, percent: int) -> None:
        palette = THEMES.get(theme_name, THEMES["sky_blue"])
        self.root_background.set_ocean_enabled(theme_name == "sky_blue")
        icon_size = max(12, round(16 * percent / 100))
        refresh_icon = make_refresh_icon(palette.text, icon_size)
        self.device_refresh_button.setIcon(refresh_icon)
        self.device_refresh_button.setIconSize(QSize(icon_size, icon_size))
        self._update_midi_tab_icon(theme_name, percent)
        self.track_channels.set_colors(
            palette.accent,
            palette.accent_text,
            palette.canvas,
            palette.text,
        )

    def _update_midi_tab_icon(self, theme_name: str, percent: int) -> None:
        if self.tab_bar.count() == 0:
            return
        palette = THEMES.get(theme_name, THEMES["sky_blue"])
        icon_size = max(10, round(14 * percent / 100))
        self.tab_bar.setIconSize(QSize(icon_size, icon_size))
        self.tab_bar.setTabIcon(0, make_refresh_icon(palette.text, icon_size))

    @staticmethod
    def _set_spacer_width(layout, index: int, width: int) -> None:  # type: ignore[no-untyped-def]
        item = layout.itemAt(index)
        spacer = item.spacerItem() if item else None
        if spacer is not None:
            spacer.changeSize(width, 0)
            layout.invalidate()

    def _update_section_gaps(self, state: AppState) -> None:
        visible = [
            state.section_visibility["midi_input"],
            state.section_visibility["key_playback"],
            state.section_visibility["common_settings"],
            state.section_visibility["player"],
        ]
        gaps = (self.realtime_gap, self.key_gap, self.settings_gap)
        scale = state.ui_scale_percent / 100.0
        all_visible = all(visible)
        for index, gap in enumerate(gaps):
            show = visible[index] and any(visible[index + 1 :])
            base_height = 6 if index == 2 and all_visible else 12
            gap.setFixedHeight(max(1, round(base_height * scale)))
            gap.setVisible(show)

    def _apply_section_visibility(self, state: AppState) -> None:
        sections = (
            ("midi_input", self.realtime_panel),
            ("key_playback", self.key_panel),
            ("common_settings", self.settings_panel),
            ("player", self.player_panel),
        )
        visibility = tuple(state.section_visibility[name] for name, _widget in sections)
        previous = self._applied_section_visibility
        if visibility == previous:
            return

        if previous is not None:
            for (name, widget), was_visible in zip(sections, previous):
                if was_visible:
                    self._section_heights[name] = max(1, widget.height())
            if self._full_visibility_height is None:
                self._full_visibility_height = (
                    self.height() + self._hidden_section_height(previous, state.ui_scale_percent)
                )

        for (name, widget), visible in zip(sections, visibility):
            widget.setVisible(visible)
            if name not in self._section_heights:
                self._section_heights[name] = max(1, widget.sizeHint().height())
        self._update_section_gaps(state)
        self.root_layout.activate()
        self.setMinimumSize(self.minimumSizeHint())

        if previous is not None and self.isVisible() and not self.isMaximized():
            target_height = self._full_visibility_height - self._hidden_section_height(
                visibility,
                state.ui_scale_percent,
            )
            self.resize(self.width(), max(self.minimumSizeHint().height(), target_height))

        self._applied_section_visibility = visibility

    def _hidden_section_height(self, visibility: tuple[bool, ...], percent: int) -> int:
        names = ("midi_input", "key_playback", "common_settings", "player")
        full_panel_height = sum(self._section_heights.get(name, 0) for name in names)
        visible_panel_height = sum(
            self._section_heights.get(name, 0)
            for name, visible in zip(names, visibility)
            if visible
        )
        scale = percent / 100.0
        full_gap_height = sum(max(1, round(height * scale)) for height in (12, 12, 6))
        all_visible = all(visibility)
        visible_gap_height = 0
        for index in range(3):
            if visibility[index] and any(visibility[index + 1 :]):
                base_height = 6 if index == 2 and all_visible else 12
                visible_gap_height += max(1, round(base_height * scale))
        return max(
            0,
            full_panel_height + full_gap_height - visible_panel_height - visible_gap_height,
        )

    def _sync_full_visibility_height(self) -> None:
        visibility = self._applied_section_visibility
        if visibility is None:
            return
        sections = (
            ("midi_input", self.realtime_panel),
            ("key_playback", self.key_panel),
            ("common_settings", self.settings_panel),
            ("player", self.player_panel),
        )
        for (name, widget), visible in zip(sections, visibility):
            if visible:
                self._section_heights[name] = max(1, widget.height())
        self._full_visibility_height = self.height() + self._hidden_section_height(
            visibility,
            self.state.ui_scale_percent,
        )

    def _render_realtime(self, state: AppState) -> None:
        text = TEXT[state.language]
        self.realtime_button.setText(text["stop_midi_input"] if state.midi_input_running else text["start_midi_input"])
        self.realtime_button.setProperty("active", state.midi_input_running)
        self.realtime_button.style().unpolish(self.realtime_button)
        self.realtime_button.style().polish(self.realtime_button)
        realtime_enabled = (
            state.current_mode not in {"keys", "keys_paused"}
            or state.midi_input_running
        )
        self.realtime_button.setEnabled(realtime_enabled)
        devices = state.midi_input_devices or [text["no_midi_input_devices"]]
        if [self.device_combo.itemText(i) for i in range(self.device_combo.count())] != devices:
            with QSignalBlocker(self.device_combo):
                self.device_combo.clear()
                self.device_combo.addItems(devices)
        with QSignalBlocker(self.device_combo):
            self.device_combo.setCurrentText(state.midi_input_device or devices[0])
        self.device_combo.setEnabled(not state.midi_input_running and bool(state.midi_input_devices))

    def _render_key_section(self, state: AppState) -> None:
        text = TEXT[state.language]
        keyboard_active = state.keyboard_playing or state.keyboard_paused
        self.keyboard_play_button.setText(text["stop_keys"] if keyboard_active else text["play_keys"])
        self.keyboard_play_button.setProperty("active", keyboard_active)
        self.keyboard_play_button.style().unpolish(self.keyboard_play_button)
        self.keyboard_play_button.style().polish(self.keyboard_play_button)
        self.keyboard_play_button.setEnabled(not state.midi_input_running and not state.sound_playing)
        self._set_spin_value(self.countdown_spin, state.countdown_seconds)
        self._set_check(self.countdown_sound_check, state.countdown_sound)
        self._set_check(self.game_sound_check, state.game_countdown_sound)
        self.shortcut_start_edit.setText(state.keyboard_play_shortcut)
        self.shortcut_pause_edit.setText(state.keyboard_pause_shortcut)
        self.shortcut_end_edit.setText(state.keyboard_stop_shortcut)
        self._set_check(self.shortcut_lock_check, state.shortcut_locked)
        self.shortcut_start_edit.setEnabled(not state.shortcut_locked)
        self.shortcut_pause_edit.setEnabled(not state.shortcut_locked)
        self.shortcut_end_edit.setEnabled(not state.shortcut_locked)

    def _render_settings(self, state: AppState) -> None:
        for check, value in (
            (self.dry_run_check, state.dry_run),
            (self.auto_fit_check, state.auto_fit_note_range),
            (self.repeat_check, state.repeat_prevention),
            (self.humanize_check, state.humanize_timing),
            (self.strum_check, state.chord_strum),
            (self.optimization_check, state.chord_optimization),
        ):
            self._set_check(check, value)

    def _render_player(self, state: AppState) -> None:
        self.status_label.setText(state.status)
        self.volume_control.set_value(state.midi_sound_volume)
        self.speed_control.set_value(state.playback_speed_percent)
        self._set_spin_value(self.transpose_spin, state.transpose_semitones)
        self._set_spin_value(self.octave_spin, state.octave_shift)
        duration = max(0.0, state.duration)
        slider_value = round(1000 * state.position / duration) if duration else 0
        with QSignalBlocker(self.position_slider):
            if not self.position_slider.isSliderDown():
                self.position_slider.setValue(slider_value)
        self.time_label.setText(
            f"{self.controller.format_time(state.position)} / {self.controller.format_time(duration)}"
        )
        rows_signature = tuple((row.name, row.duration, row.note_range) for row in state.midi_rows)
        if rows_signature != self._last_rows_signature:
            self._last_rows_signature = rows_signature
            with QSignalBlocker(self.midi_table):
                self.midi_table.setRowCount(len(state.midi_rows))
                for row_index, row in enumerate(state.midi_rows):
                    for column, value in enumerate((row.name, row.duration, row.note_range)):
                        item = QTableWidgetItem(value)
                        item.setData(Qt.ItemDataRole.UserRole, str(row.path))
                        self.midi_table.setItem(row_index, column, item)
                    self.midi_table.setRowHeight(
                        row_index,
                        max(1, round(22 * state.ui_scale_percent / 100)),
                    )
        if 0 <= state.selected_midi_index < self.midi_table.rowCount():
            with QSignalBlocker(self.midi_table):
                self.midi_table.selectRow(state.selected_midi_index)
        sources_signature = tuple((item.track, item.channel, item.enabled) for item in state.track_channels)
        if sources_signature != self._last_sources_signature:
            self._last_sources_signature = sources_signature
            self.track_channels.set_items(state.track_channels)

    def _build_menus(self, state: AppState) -> None:
        text = TEXT[state.language]
        self.menuBar().clear()
        file_menu = self.menuBar().addMenu(text["menu_midi"])
        load_action = file_menu.addAction(text["load_midi"])
        load_action.triggered.connect(self._choose_midi_folder)
        file_menu.addSeparator()
        file_menu.addAction(text["exit"], self.exit_application)

        view_menu = self.menuBar().addMenu(text["menu_view"])
        scale_menu = view_menu.addMenu(text["ui_scale"])
        scale_group = QActionGroup(scale_menu)
        scale_group.setExclusive(True)
        for percent in UI_SCALE_PERCENT_OPTIONS:
            action = scale_menu.addAction(f"{percent}%")
            action.setCheckable(True)
            action.setChecked(percent == state.ui_scale_percent)
            action.triggered.connect(lambda _checked=False, value=percent: self._set_option("ui_scale_percent", value))
            scale_group.addAction(action)
        opacity_menu = view_menu.addMenu(text["window_opacity"])
        opacity_group = QActionGroup(opacity_menu)
        opacity_group.setExclusive(True)
        for percent in (100, 90, 80, 70, 60, 50, 40):
            action = opacity_menu.addAction(f"{percent}%")
            action.setCheckable(True)
            action.setChecked(percent == state.window_opacity)
            action.triggered.connect(lambda _checked=False, value=percent: self._set_option("window_opacity", value))
            opacity_group.addAction(action)
        view_menu.addSeparator()
        always_action = view_menu.addAction(text["always_on_top"])
        always_action.setCheckable(True)
        always_action.setChecked(state.always_on_top)
        always_action.toggled.connect(lambda value: self._set_option("always_on_top", value))
        view_menu.addSeparator()
        for section, key in (
            ("midi_input", "midi_input_settings"),
            ("key_playback", "key_playback_settings"),
            ("common_settings", "midi_sound_settings"),
            ("player", "player_section"),
        ):
            action = view_menu.addAction(text[key])
            action.setCheckable(True)
            action.setChecked(state.section_visibility[section])
            action.toggled.connect(lambda checked, name=section: self.controller.set_section_visible(name, checked))

        settings_menu = self.menuBar().addMenu(text["menu_settings"])
        theme_menu = settings_menu.addMenu(text["color_theme"])
        theme_group = QActionGroup(theme_menu)
        theme_group.setExclusive(True)
        sky_blue_icon = QIcon(str(resource_path("assets/app_icon_whale.png")))
        self.theme_actions: dict[str, object] = {}
        for theme, title in COLOR_THEME_NAMES[state.language].items():
            action = theme_menu.addAction(title)
            if theme == "sky_blue":
                action.setIcon(sky_blue_icon)
            action.setCheckable(True)
            action.setChecked(theme == state.color_theme)
            action.triggered.connect(lambda _checked=False, value=theme: self._set_option("color_theme", value))
            theme_group.addAction(action)
            self.theme_actions[theme] = action
        language_menu = settings_menu.addMenu(text["language"])
        language_group = QActionGroup(language_menu)
        language_group.setExclusive(True)
        for language, title in LANGUAGE_NAMES.items():
            action = language_menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(language == state.language)
            action.triggered.connect(lambda _checked=False, value=language: self._set_option("language", value))
            language_group.addAction(action)
        settings_menu.addAction(text["key_bindings"], self._open_key_bindings)
        tray_action = settings_menu.addAction(text["tray_resident"])
        tray_action.setCheckable(True)
        tray_action.setChecked(state.tray_resident)
        tray_action.toggled.connect(lambda value: self._set_option("tray_resident", value))

        other_menu = self.menuBar().addMenu(text["menu_other"])
        other_menu.addAction(text["about_app"], self._open_about)

    def _set_option(self, name: str, value: object) -> None:
        if not self._rendering:
            self.controller.set_option(name, value)

    def _choose_midi_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, TEXT[self.state.language]["load_midi"])
        if folder:
            self.controller.load_midi_folder(folder)

    def _change_player_page(self, index: int) -> None:
        if index >= 0:
            self.player_stack.setCurrentIndex(index)

    def _player_tab_double_clicked(self, index: int) -> None:
        if index == 0:
            self.controller.reload_midi_folder()

    def _midi_selection_changed(self) -> None:
        if self._rendering:
            return
        rows = self.midi_table.selectionModel().selectedRows()
        if rows:
            self.controller.select_midi(rows[0].row())

    def _seek_from_slider(self, slider_value: int) -> None:
        if self.state.duration:
            self.controller.seek(self.state.duration * slider_value / 1000)

    def append_log(self, message: str) -> None:
        self.log_output.appendPlainText(str(message))

    def clear_log(self) -> None:
        self.log_output.clear()

    def show_message(self, level: str, title: str, message: str) -> None:
        icon = {
            "error": QMessageBox.Icon.Critical,
            "warning": QMessageBox.Icon.Warning,
            "info": QMessageBox.Icon.Information,
        }.get(level, QMessageBox.Icon.Information)
        box = QMessageBox(icon, title, message, QMessageBox.StandardButton.Ok, self)
        box.exec()

    def _open_about(self) -> None:
        text = TEXT[self.state.language]
        dialog = QDialog(self)
        dialog.setWindowTitle(text["about_title"])
        dialog.setFixedWidth(round(360 * self.state.ui_scale_percent / 100))
        layout = QVBoxLayout(dialog)
        title = QLabel("BPSR MIDI to KEY Player")
        title.setProperty("sectionTitle", True)
        layout.addWidget(title)
        version = QLabel(f'{text["version"]} {APP_VERSION}')
        version.setProperty("caption", True)
        layout.addWidget(version)
        layout.addWidget(QLabel("Copyright (c) 2026 airknightjp"))
        buttons = QHBoxLayout()
        github = QPushButton("GitHub")
        github.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PROJECT_URL)))
        close = QPushButton(text["close"])
        close.clicked.connect(dialog.accept)
        buttons.addWidget(github)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        dialog.exec()

    def _open_key_bindings(self) -> None:
        KeyBindingsDialog(self.controller, self.state.language, self).exec()

    def exit_application(self) -> None:
        self._closing_for_exit = True
        self.tray_icon.hide()
        QApplication.instance().quit()

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._closing_for_exit and self.state.tray_resident and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()
            self.hide()
            event.ignore()
            return
        self._closing_for_exit = True
        event.accept()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        if not self._rendering and self.isVisible() and not self.isMaximized():
            self._sync_full_visibility_height()
            self.controller.set_window_geometry(self.width(), self.height())

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(event)
        if not self.isMaximized():
            self._sync_full_visibility_height()
            self.controller.set_window_geometry(self.width(), self.height())

    @staticmethod
    def _set_check(check: QCheckBox, checked: bool) -> None:
        with QSignalBlocker(check):
            check.setChecked(checked)

    @staticmethod
    def _set_spin_value(spin: QSpinBox, value: int) -> None:
        with QSignalBlocker(spin):
            spin.setValue(value)


class BindingCaptureEdit(ShortcutCaptureEdit):
    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.text().lower()
        aliases = {
            Qt.Key.Key_Space: "space",
            Qt.Key.Key_Return: "enter",
            Qt.Key.Key_Enter: "enter",
            Qt.Key.Key_Tab: "tab",
        }
        key = aliases.get(event.key(), key)
        if key in SUPPORTED_BINDING_KEYS:
            self.setText(key)
            self.shortcutCaptured.emit(key)
        event.accept()


class KeyBindingsDialog(QDialog):
    def __init__(self, controller: AppController, language: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.language = language
        self.edits: dict[int, BindingCaptureEdit] = {}
        self.note_labels: dict[int, QLabel] = {}
        text = TEXT[language]
        self.setWindowTitle(text["key_bindings"])
        self.resize(400, 480)
        root = QVBoxLayout(self)
        bindings_row = QHBoxLayout()
        bindings_row.setContentsMargins(0, 0, 0, 0)
        bindings_row.setSpacing(6)
        group_widgets: list[QWidget] = []
        group_layouts: list[QGridLayout] = []
        for _group in range(3):
            group_widget = QWidget()
            group_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
            group_grid = QGridLayout(group_widget)
            group_grid.setContentsMargins(0, 0, 0, 0)
            group_grid.setHorizontalSpacing(6)
            group_widgets.append(group_widget)
            group_layouts.append(group_grid)
            bindings_row.addWidget(group_widget)
        bindings = controller.current_key_bindings()
        for offset, note in enumerate(range(BASE_NOTE_MIN, BASE_NOTE_MAX + 1)):
            group = offset // 12
            row = offset % 12
            note_name = f"{NOTE_NAMES[note % 12]}{note // 12 - 1}"
            label = QLabel(note_name)
            edit = BindingCaptureEdit()
            edit.setFixedWidth(56)
            edit.setText(bindings[note])
            edit.shortcutCaptured.connect(lambda key, midi_note=note: self._binding_changed(midi_note, key))
            self.note_labels[note] = label
            self.edits[note] = edit
            group_layouts[group].addWidget(label, row, 0)
            group_layouts[group].addWidget(edit, row, 1)
        root.addLayout(bindings_row, 1)
        buttons = QHBoxLayout()
        restore = QPushButton(text["restore_default_key_bindings"])
        restore.clicked.connect(self._restore_defaults)
        close = QPushButton(text["close"])
        close.clicked.connect(self.accept)
        buttons.addWidget(restore)
        buttons.addStretch(1)
        buttons.addWidget(close)
        root.addLayout(buttons)
        self.ensurePolished()
        for label in self.note_labels.values():
            label.ensurePolished()
        for edit in self.edits.values():
            edit.ensurePolished()
        scale = controller.state.ui_scale_percent / 100.0
        edit_width = max(
            56,
            max(edit.fontMetrics().horizontalAdvance("space") for edit in self.edits.values())
            + round(16 * scale),
        )
        for edit in self.edits.values():
            edit.setFixedWidth(edit_width)
        for group, (group_widget, group_grid) in enumerate(zip(group_widgets, group_layouts)):
            first_note = BASE_NOTE_MIN + group * 12
            label_width = max(
                self.note_labels[note].sizeHint().width()
                for note in range(first_note, first_note + 12)
            )
            group_widget.setFixedWidth(label_width + group_grid.horizontalSpacing() + edit_width)
            group_grid.invalidate()
        bindings_row.invalidate()
        root.invalidate()
        root.activate()
        self.setFixedWidth(self.sizeHint().width())
        self._refresh_duplicates()

    def _binding_changed(self, note: int, key: str) -> None:
        self.controller.set_key_binding(note, key)
        self._refresh_duplicates()

    def _restore_defaults(self) -> None:
        self.controller.reset_key_bindings()
        for note, key in self.controller.current_key_bindings().items():
            self.edits[note].setText(key)
        self._refresh_duplicates()

    def _refresh_duplicates(self) -> None:
        counts: dict[str, int] = {}
        for edit in self.edits.values():
            counts[edit.text()] = counts.get(edit.text(), 0) + 1
        for edit in self.edits.values():
            edit.setStyleSheet("color: #c62828; font-weight: 600;" if counts.get(edit.text(), 0) > 1 else "")
