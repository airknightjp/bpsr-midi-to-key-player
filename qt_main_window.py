from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QSignalBlocker, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QActionGroup, QCloseEvent, QDesktopServices, QIcon, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QButtonGroup,
    QRadioButton,
    QSizePolicy,
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
from config import (
    BASE_NOTE_MAX,
    BASE_NOTE_MIN,
    DEFAULT_PANEL_ORDER,
    INPUT_CONVERSION_MIDI_FILE,
    INPUT_CONVERSION_REALTIME,
    NOTE_NAMES,
    SOUND_PLAYBACK_MODE_CONTINUOUS,
    SOUND_PLAYBACK_MODE_OFF,
    SOUND_PLAYBACK_MODE_REPEAT_ONE,
    SUPPORTED_BINDING_KEYS,
    normalize_panel_order,
)
from i18n import COLOR_THEME_NAMES, LANGUAGE_NAMES, SOUND_SOURCE_NAMES, TEXT
from note_visualization import build_piano_roll_notes
from qt_components import (
    ContentPanel,
    FallingNotesWidget,
    InteractiveIconButton,
    KnobValueControl,
    PanelDragHandle,
    PanelInsertionIndicator,
    PianoKeyboardWidget,
    SeekSlider,
    ShortcutCaptureEdit,
    ThemedBackground,
    TrackChannelTable,
    make_feature_icon,
    make_refresh_icon,
    make_transport_icon,
)
from qt_styles import THEMES, build_stylesheet, register_windows_fonts
from update_service import (
    AvailableUpdate,
    UpdateService,
    automatic_update_check_due,
    automatic_update_supported,
    launch_update_installer,
    read_pending_update_error,
)


APP_VERSION = "1.4.0"
PROJECT_URL = "https://github.com/airknightjp/bpsr-midi-to-key-player"
COMPACT_KNOB_DIAMETER = 36
KEYBOARD_PANEL_HEIGHT = 71
KEYBOARD_PANEL_MARGIN = 7


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


class MidiMainWindow(QMainWindow):
    event_dispatch_requested = Signal()
    activation_requested = Signal()

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
        self._applied_opacity: int | None = None
        self._applied_always_on_top: bool | None = None
        self._applied_section_visibility: tuple[bool, ...] | None = None
        self._applied_panel_order: tuple[str, ...] = ()
        self._section_heights: dict[str, int] = {}
        self._full_visibility_height: int | None = None
        self._render_signatures: dict[str, object] = {}
        self._rendered_midi_rows: object | None = None
        self._rendered_track_channels: object | None = None
        self._available_update: AvailableUpdate | None = None
        self._manual_update_check = False
        self._build_ui()
        self._focus_clear_controls = (
            self.sound_source_combo,
            self.shortcut_start_edit,
            self.shortcut_pause_edit,
            self.shortcut_end_edit,
        )
        application = QApplication.instance()
        self._focus_filter_installed = application is not None
        if application is not None:
            application.installEventFilter(self)
        self._create_tray_icon()
        self.update_service = UpdateService(self)
        self.update_service.checkCompleted.connect(
            self._update_check_completed
        )
        self.update_service.checkFailed.connect(
            self._update_check_failed
        )
        self.event_dispatch_requested.connect(
            self.controller.process_pending_events,
            Qt.ConnectionType.QueuedConnection,
        )
        self.activation_requested.connect(
            self._restore_from_tray,
            Qt.ConnectionType.QueuedConnection,
        )
        self._output_note_release_timer = QTimer(self)
        self._output_note_release_timer.setSingleShot(True)
        self._output_note_release_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._output_note_release_timer.timeout.connect(
            self.controller.process_output_note_releases
        )
        self._rhythm_score_timer = QTimer(self)
        self._rhythm_score_timer.setSingleShot(True)
        self._rhythm_score_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._rhythm_score_timer.timeout.connect(
            self.controller.process_rhythm_score_update
        )
        self._hotkey_timer = QTimer(self)
        self._hotkey_timer.setInterval(3000)
        self._hotkey_timer.timeout.connect(self.controller.ensure_hotkeys)
        self._hotkey_timer.start()
        self.controller.set_event_notifier(self.event_dispatch_requested.emit)
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

        self.conversion_control_panel = QFrame()
        self.conversion_control_panel.setObjectName("SettingsPanel")
        conversion_controls = QHBoxLayout(self.conversion_control_panel)
        conversion_controls.setContentsMargins(8, 4, 8, 4)
        conversion_controls.setSpacing(0)
        self.conversion_control_layout = conversion_controls
        self.conversion_start_button = InteractiveIconButton()
        self.conversion_start_button.setObjectName("ConversionStartButton")
        self.conversion_start_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        self.conversion_start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.conversion_start_button.clicked.connect(
            self.controller.toggle_input_conversion
        )
        conversion_controls.addWidget(
            self.conversion_start_button,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        conversion_controls.addSpacing(10)
        self.realtime_mode_radio = QRadioButton()
        self.midi_file_mode_radio = QRadioButton()
        self.input_conversion_group = QButtonGroup(self)
        self.input_conversion_group.addButton(self.realtime_mode_radio)
        self.input_conversion_group.addButton(self.midi_file_mode_radio)
        self.realtime_mode_radio.toggled.connect(
            lambda checked: checked
            and self._set_option(
                "input_conversion_mode", INPUT_CONVERSION_REALTIME
            )
        )
        self.midi_file_mode_radio.toggled.connect(
            lambda checked: checked
            and self._set_option(
                "input_conversion_mode", INPUT_CONVERSION_MIDI_FILE
            )
        )
        self.conversion_mode_panel = QWidget()
        conversion_modes = QVBoxLayout(self.conversion_mode_panel)
        conversion_modes.setContentsMargins(0, 0, 0, 0)
        conversion_modes.setSpacing(2)
        conversion_modes.addStretch(1)
        conversion_modes.addWidget(self.realtime_mode_radio)
        conversion_modes.addWidget(self.midi_file_mode_radio)
        conversion_modes.addStretch(1)
        self.conversion_mode_layout = conversion_modes
        conversion_controls.addWidget(self.conversion_mode_panel)
        conversion_controls.addSpacing(12)

        self.realtime_panel = ContentPanel()
        self._build_realtime_section()
        self.key_panel = ContentPanel()
        self._build_key_section()
        self.conversion_settings_stack = QStackedWidget()
        self.conversion_settings_stack.setFrameShape(QFrame.Shape.NoFrame)
        self.conversion_settings_stack.setLineWidth(0)
        self.conversion_settings_stack.addWidget(self.realtime_panel)
        self.conversion_settings_stack.addWidget(self.key_panel)
        conversion_controls.addWidget(self.conversion_settings_stack, 1)
        root_layout.addWidget(self.conversion_control_panel)
        self.conversion_control_gap = self._make_gap(6)
        root_layout.addWidget(self.conversion_control_gap)

        self.settings_panel = QWidget()
        self.settings_panel.setObjectName("SettingsPanel")
        self.settings_layout = QVBoxLayout(self.settings_panel)
        self.settings_layout.setContentsMargins(10, 10, 10, 10)
        self.settings_layout.setSpacing(0)
        self._build_settings_section()
        root_layout.addWidget(self.settings_panel)
        self.piano_roll_gap = self._make_gap(6)
        root_layout.addWidget(self.piano_roll_gap)
        self.piano_roll_panel = QWidget()
        self.piano_roll_panel.setObjectName("SettingsPanel")
        self.piano_roll_layout = QHBoxLayout(self.piano_roll_panel)
        self.piano_roll_layout.setContentsMargins(7, 7, 7, 7)
        self.piano_roll_layout.setSpacing(0)
        self.piano_roll = FallingNotesWidget()
        self.piano_roll_layout.addWidget(self.piano_roll)
        root_layout.addWidget(self.piano_roll_panel)
        self.settings_lower_gap = self._make_gap(6)
        root_layout.addWidget(self.settings_lower_gap)
        self.settings_lower_panel = QWidget()
        self.settings_lower_panel.setObjectName("SettingsPanel")
        self.settings_lower_layout = QHBoxLayout(self.settings_lower_panel)
        self.settings_lower_layout.setContentsMargins(10, 10, 10, 10)
        self.settings_lower_layout.setSpacing(0)
        self.output_keyboard = PianoKeyboardWidget()
        self.settings_lower_layout.addWidget(self.output_keyboard)
        root_layout.addWidget(self.settings_lower_panel)
        self.settings_gap = self._make_gap(6)
        root_layout.addWidget(self.settings_gap)

        self.player_panel = QWidget()
        self.player_panel.setObjectName("SettingsPanel")
        self.player_layout = QVBoxLayout(self.player_panel)
        self.player_layout.setContentsMargins(8, 8, 8, 8)
        self.player_layout.setSpacing(0)
        self._build_player_section()
        root_layout.addWidget(self.player_panel, 1)
        self._setup_panel_reordering()

    @staticmethod
    def _make_gap(height: int) -> QWidget:
        gap = QWidget()
        gap.setFixedHeight(height)
        return gap

    def _setup_panel_reordering(self) -> None:
        self._panel_widgets = {
            "input_conversion": self.conversion_control_panel,
            "common_settings": self.settings_panel,
            "piano_roll": self.piano_roll_panel,
            "keyboard": self.settings_lower_panel,
            "player": self.player_panel,
        }
        self._panel_gaps = (
            self.conversion_control_gap,
            self.piano_roll_gap,
            self.settings_lower_gap,
            self.settings_gap,
        )
        self._panel_drag_handles = {
            panel_id: PanelDragHandle(panel_id, panel)
            for panel_id, panel in self._panel_widgets.items()
        }
        self._panel_insertion_indicator = PanelInsertionIndicator(
            self.root_background
        )
        self._dragging_panel_id: str | None = None
        self._panel_drag_effect: QGraphicsOpacityEffect | None = None
        for handle in self._panel_drag_handles.values():
            handle.dragStarted.connect(self._panel_drag_started)
            handle.dragFinished.connect(self._panel_drag_finished)
        self.root_background.panelDragMoved.connect(self._panel_drag_moved)
        self.root_background.panelDragLeft.connect(
            self._panel_insertion_indicator.hide
        )
        self.root_background.panelDropped.connect(self._panel_dropped)

    def _panel_drag_started(self, panel_id: str) -> None:
        panel = self._panel_widgets.get(panel_id)
        if panel is None or not panel.isVisible():
            return
        if self._dragging_panel_id is not None:
            self._panel_drag_finished(self._dragging_panel_id)
        self._dragging_panel_id = panel_id
        self._panel_drag_effect = QGraphicsOpacityEffect(panel)
        self._panel_drag_effect.setOpacity(0.40)
        panel.setGraphicsEffect(self._panel_drag_effect)

    def _panel_drag_finished(self, panel_id: str) -> None:
        if panel_id != self._dragging_panel_id:
            return
        panel = self._panel_widgets.get(panel_id)
        if panel is not None:
            panel.setGraphicsEffect(None)
        self._panel_drag_effect = None
        self._panel_insertion_indicator.hide()
        self._dragging_panel_id = None

    def _panel_drag_moved(self, panel_id: str, drag_y: int) -> None:
        if panel_id != self._dragging_panel_id:
            return
        insertion = self._panel_insertion(panel_id, drag_y)
        if insertion is None:
            self._panel_insertion_indicator.hide()
            return
        _remaining, _insert_at, reference, line_y = insertion
        self._panel_insertion_indicator.show_at(
            reference.geometry().left(),
            line_y,
            reference.width(),
        )

    def _apply_panel_order(self, panel_order: object) -> None:
        order = normalize_panel_order(panel_order)
        if order == self._applied_panel_order:
            return
        for panel in self._panel_widgets.values():
            self.root_layout.removeWidget(panel)
        for gap in self._panel_gaps:
            self.root_layout.removeWidget(gap)
        for index, panel_id in enumerate(order):
            panel = self._panel_widgets[panel_id]
            self.root_layout.addWidget(panel, 1 if panel_id == "player" else 0)
            if index < len(self._panel_gaps):
                self.root_layout.addWidget(self._panel_gaps[index])
        self._applied_panel_order = order
        self._update_section_gaps(
            self.state,
            self._effective_section_visibility(self.state),
        )
        self.root_layout.activate()

    def _panel_dropped(self, panel_id: str, drop_y: int) -> None:
        insertion = self._panel_insertion(panel_id, drop_y)
        if insertion is None:
            return
        remaining, insert_at, _reference, _line_y = insertion
        remaining.insert(insert_at, panel_id)
        self.controller.set_panel_order(tuple(remaining))

    def _panel_insertion(
        self,
        panel_id: str,
        drop_y: int,
    ) -> tuple[list[str], int, QWidget, int] | None:
        order = list(normalize_panel_order(self.state.panel_order))
        if panel_id not in order:
            return None
        remaining = [item for item in order if item != panel_id]
        visible_remaining = [
            item for item in remaining if self._panel_widgets[item].isVisible()
        ]
        insert_before = next(
            (
                item
                for item in visible_remaining
                if drop_y < self._panel_widgets[item].geometry().center().y()
            ),
            None,
        )
        if insert_before is not None:
            insert_at = remaining.index(insert_before)
            reference = self._panel_widgets[insert_before]
            line_y = reference.geometry().top()
        elif visible_remaining:
            last_visible = visible_remaining[-1]
            insert_at = remaining.index(last_visible) + 1
            reference = self._panel_widgets[last_visible]
            line_y = reference.geometry().bottom() + 1
        else:
            insert_at = len(remaining)
            reference = self._panel_widgets[panel_id]
            line_y = reference.geometry().top()
        return remaining, insert_at, reference, line_y

    def _build_realtime_section(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(0)
        row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.realtime_row = row
        self.device_controls_frame = QFrame()
        self.device_controls_frame.setProperty("subgroup", True)
        self.device_controls_layout = QHBoxLayout(self.device_controls_frame)
        self.device_controls_layout.setContentsMargins(12, 8, 12, 8)
        self.device_controls_layout.setSpacing(0)
        self.device_icon_frame = QFrame()
        self.device_icon_frame.setProperty("subgroup", True)
        self.device_icon_layout = QHBoxLayout(self.device_icon_frame)
        self.device_icon_layout.setContentsMargins(3, 3, 3, 3)
        self.device_icon_layout.setSpacing(0)
        self.device_label = QLabel()
        self.device_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.device_icon_layout.addWidget(self.device_label)
        self.device_group = QFrame()
        self.device_group.setProperty("subgroup", True)
        self.device_group.setProperty("frameless", True)
        self.device_group_layout = QHBoxLayout(self.device_group)
        self.device_group_layout.setContentsMargins(6, 4, 6, 4)
        self.device_group_layout.setSpacing(0)
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(288)
        self.device_combo.currentTextChanged.connect(
            lambda value: self._set_option("midi_input_device", value)
        )
        self.device_group_layout.addWidget(self.device_combo)
        self.device_group_layout.addSpacing(8)
        self.device_refresh_button = QToolButton()
        self.device_refresh_button.setObjectName("RefreshButton")
        self.device_refresh_button.setToolTip("Refresh MIDI devices")
        self.device_refresh_button.clicked.connect(self.controller.refresh_midi_input_devices)
        self.device_group_layout.addWidget(self.device_refresh_button)
        self.device_controls_layout.addWidget(
            self.device_icon_frame,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        self.device_controls_layout.addSpacing(6)
        self.device_controls_layout.addWidget(
            self.device_group,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        row.addWidget(
            self.device_controls_frame,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        row.addStretch(1)
        self.realtime_panel.body_layout.addLayout(row)

    def _build_key_section(self) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.key_row = row
        self.key_controls_frame = QFrame()
        self.key_controls_frame.setProperty("subgroup", True)
        self.key_controls_layout = QHBoxLayout(self.key_controls_frame)
        self.key_controls_layout.setContentsMargins(12, 8, 12, 8)
        self.key_controls_layout.setSpacing(0)
        self.countdown_icon_frame = QFrame()
        self.countdown_icon_frame.setProperty("subgroup", True)
        self.countdown_icon_layout = QHBoxLayout(self.countdown_icon_frame)
        self.countdown_icon_layout.setContentsMargins(3, 3, 3, 3)
        self.countdown_icon_layout.setSpacing(0)
        self.countdown_label = QLabel()
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.countdown_icon_layout.addWidget(self.countdown_label)
        self.countdown_control = KnobValueControl(
            0,
            10,
            3,
            horizontal=True,
            horizontal_knob_size=COMPACT_KNOB_DIAMETER,
            horizontal_minimum_width=41,
            caption=False,
        )
        self.countdown_control.label.hide()
        self.countdown_control.valueChanged.connect(
            lambda value: self._set_option("countdown_seconds", value)
        )
        self.seconds_label = QLabel()
        self.countdown_sound_check = QCheckBox()
        self.countdown_sound_check.toggled.connect(lambda value: self._set_option("countdown_sound", value))
        self.game_sound_check = QCheckBox()
        self.game_sound_check.toggled.connect(lambda value: self._set_option("game_countdown_sound", value))
        self.countdown_group = QFrame()
        self.countdown_group.setProperty("subgroup", True)
        self.countdown_group.setProperty("frameless", True)
        countdown = QHBoxLayout(self.countdown_group)
        countdown.setContentsMargins(6, 4, 6, 4)
        countdown.setSpacing(0)
        self.countdown_group_layout = countdown
        countdown.addWidget(self.countdown_control)
        countdown.addSpacing(2)
        countdown.addWidget(self.seconds_label)
        countdown.addSpacing(6)
        countdown.addWidget(self.countdown_sound_check)
        countdown.addSpacing(6)
        countdown.addWidget(self.game_sound_check)
        self.key_controls_layout.addWidget(
            self.countdown_icon_frame,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        self.key_controls_layout.addSpacing(6)
        self.key_controls_layout.addWidget(
            self.countdown_group,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )

        self.shortcut_icon_frame = QFrame()
        self.shortcut_icon_frame.setProperty("subgroup", True)
        self.shortcut_icon_layout = QHBoxLayout(self.shortcut_icon_frame)
        self.shortcut_icon_layout.setContentsMargins(3, 3, 3, 3)
        self.shortcut_icon_layout.setSpacing(0)
        self.shortcut_caption = QLabel()
        self.shortcut_icon_layout.addWidget(self.shortcut_caption)
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
        self.shortcut_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.shortcut_group = QFrame()
        self.shortcut_group.setProperty("subgroup", True)
        self.shortcut_group.setProperty("frameless", True)
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
        self.key_controls_layout.addSpacing(10)
        self.key_controls_layout.addWidget(
            self.shortcut_icon_frame,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        self.key_controls_layout.addSpacing(4)
        self.key_controls_layout.addWidget(
            self.shortcut_group,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        row.addWidget(self.key_controls_frame, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)

        self.key_panel.body_layout.addLayout(row)

    def _build_settings_section(self) -> None:
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        self.settings_grid = grid
        self.dry_run_check = self._option_check("dry_run")
        self.auto_fit_check = self._option_check("auto_fit_note_range")
        self.repeat_check = self._option_check("repeat_prevention")
        self.humanize_check = self._option_check("humanize_timing")
        self.strum_check = self._option_check("chord_strum")
        self.optimization_check = self._option_check("chord_optimization")
        self.auto_sustain_check = self._option_check("auto_sustain")
        for column, widget in enumerate(
            (self.dry_run_check, self.auto_fit_check, self.repeat_check)
        ):
            widget.setProperty("settingsItem", True)
            grid.addWidget(
                widget,
                0,
                column,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            )
        for column, widget in enumerate(
            (
                self.humanize_check,
                self.strum_check,
                self.optimization_check,
                self.auto_sustain_check,
            ),
        ):
            widget.setProperty("settingsItem", True)
            grid.addWidget(
                widget,
                1,
                column,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            )
        grid.setColumnStretch(4, 1)
        self.settings_layout.addLayout(grid)

    def _option_check(self, name: str) -> QCheckBox:
        check = QCheckBox()
        check.toggled.connect(lambda value, option=name: self._set_option(option, value))
        return check

    def _build_player_section(self) -> None:
        self.player_header = QWidget()
        self.player_header_layout = QGridLayout(self.player_header)
        self.player_header_layout.setContentsMargins(0, 0, 0, 0)
        self.player_header_layout.setSpacing(0)

        position_row = QHBoxLayout()
        position_row.setContentsMargins(0, 0, 0, 0)
        position_row.setSpacing(6)
        self.position_row_layout = position_row
        self.position_slider = SeekSlider()
        self.position_slider.setRange(0, 1000)
        self.position_slider.seekRequested.connect(self._seek_from_slider)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        position_row.addWidget(self.position_slider, 1)
        position_row.addWidget(self.time_label)
        self.player_header_layout.addLayout(position_row, 0, 0)

        self.slider_pane = QWidget()
        slider_layout = QHBoxLayout(self.slider_pane)
        slider_layout.setContentsMargins(0, 0, 0, 0)
        slider_layout.setSpacing(2)
        slider_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.slider_layout = slider_layout
        self.volume_control = KnobValueControl(
            0,
            100,
            80,
            horizontal=True,
            horizontal_knob_size=COMPACT_KNOB_DIAMETER,
            horizontal_minimum_width=62,
        )
        self.volume_control.valueChanged.connect(lambda value: self._set_option("midi_sound_volume", value))
        self.volume_control.resetRequested.connect(lambda: self._set_option("midi_sound_volume", 100))
        self.speed_control = KnobValueControl(
            10,
            200,
            100,
            horizontal=True,
            horizontal_knob_size=COMPACT_KNOB_DIAMETER,
            horizontal_minimum_width=62,
        )
        self.speed_control.valueChanged.connect(lambda value: self._set_option("playback_speed_percent", value))
        self.speed_control.resetRequested.connect(lambda: self._set_option("playback_speed_percent", 100))
        self.audio_runtime_label = QLabel()
        self.audio_runtime_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.audio_runtime_label.setProperty("caption", True)
        self.menuBar().setCornerWidget(
            self.audio_runtime_label,
            Qt.Corner.TopRightCorner,
        )
        slider_layout.addWidget(self.speed_control)

        self.transpose_control = KnobValueControl(
            -12,
            12,
            0,
            horizontal=True,
            horizontal_knob_size=COMPACT_KNOB_DIAMETER,
            horizontal_minimum_width=86,
        )
        self.transpose_control.valueChanged.connect(
            lambda value: self._set_option("transpose_semitones", value)
        )
        self.transpose_control.resetRequested.connect(
            lambda: self._set_option("transpose_semitones", 0)
        )
        self.octave_control = KnobValueControl(
            -3,
            3,
            0,
            horizontal=True,
            horizontal_knob_size=COMPACT_KNOB_DIAMETER,
            horizontal_minimum_width=86,
        )
        self.octave_control.valueChanged.connect(
            lambda value: self._set_option("octave_shift", value)
        )
        self.octave_control.resetRequested.connect(
            lambda: self._set_option("octave_shift", 0)
        )
        self.transform_controls = QWidget()
        transform_layout = QHBoxLayout(self.transform_controls)
        transform_layout.setContentsMargins(0, 0, 0, 0)
        transform_layout.setSpacing(0)
        self.transform_layout = transform_layout
        transform_layout.addWidget(self.transpose_control)
        transform_layout.addSpacing(12)
        transform_layout.addWidget(self.octave_control)

        transport = QHBoxLayout()
        transport.setContentsMargins(0, 0, 0, 0)
        transport.setSpacing(1)
        self.transport_layout = transport
        self.previous_track_button = self._make_player_transport_button(
            self.controller.select_previous_midi
        )
        self.sound_play_pause_button = self._make_player_transport_button(
            self.controller.toggle_sound_pause
        )
        self.next_track_button = self._make_player_transport_button(
            self.controller.select_next_midi
        )
        self.sound_playback_mode_button = self._make_player_transport_button(
            self.controller.cycle_sound_playback_mode
        )
        self.transport_left = QWidget()
        transport_left_layout = QHBoxLayout(self.transport_left)
        transport_left_layout.setContentsMargins(0, 0, 0, 0)
        transport_left_layout.setSpacing(0)
        transport_left_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.transport_left_layout = transport_left_layout
        transport_left_layout.addWidget(self.volume_control)
        transport_left_layout.addStretch(1)
        transport_left_layout.addWidget(self.slider_pane)
        transport_left_layout.addSpacing(1)
        transport_left_layout.addWidget(self.previous_track_button)

        self.transport_right = QWidget()
        transport_right_layout = QHBoxLayout(self.transport_right)
        transport_right_layout.setContentsMargins(0, 0, 0, 0)
        transport_right_layout.setSpacing(0)
        transport_right_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.transport_right_layout = transport_right_layout
        transport_right_layout.addWidget(self.next_track_button)
        transport_right_layout.addSpacing(1)
        transport_right_layout.addWidget(self.sound_playback_mode_button)
        transport_right_layout.addSpacing(1)
        transport_right_layout.addWidget(self.transform_controls)
        transport_right_layout.addStretch(1)

        transport.addStretch(1)
        transport.addWidget(self.transport_left)
        transport.addWidget(self.sound_play_pause_button)
        transport.addWidget(self.transport_right)
        transport.addStretch(1)
        self.player_header_layout.addLayout(transport, 1, 0)

        self.player_layout.addWidget(self.player_header)
        self.player_body_gap = self._make_gap(0)
        self.player_layout.addWidget(self.player_body_gap)

        body = QHBoxLayout()
        body.setSpacing(0)
        self.player_body_layout = body
        self.track_channels = TrackChannelTable()
        self.track_channels.sourceToggled.connect(self.controller.toggle_track_channel)
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
        tab_bar_container_layout.setContentsMargins(0, 0, 0, 0)
        tab_bar_container_layout.setSpacing(0)
        tab_bar_container_layout.addWidget(self.tab_bar)
        self.tab_bar_container_layout = tab_bar_container_layout
        tab_row.addWidget(
            self.tab_bar_container,
            0,
            Qt.AlignmentFlag.AlignBottom,
        )
        tab_row.addStretch(1)
        self.sound_source_controls = QWidget()
        sound_source_layout = QHBoxLayout(self.sound_source_controls)
        sound_source_layout.setContentsMargins(0, 0, 0, 2)
        sound_source_layout.setSpacing(4)
        self.sound_source_layout = sound_source_layout
        self.sound_source_label = QLabel()
        self.sound_source_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.sound_source_combo = QComboBox()
        self.sound_source_combo.currentIndexChanged.connect(self._sound_source_changed)
        sound_source_layout.addWidget(self.sound_source_label)
        sound_source_layout.addWidget(self.sound_source_combo)
        tab_row.addWidget(
            self.sound_source_controls,
            0,
            Qt.AlignmentFlag.AlignBottom,
        )
        self.player_header_layout.addLayout(
            tab_row,
            1,
            0,
            2,
            1,
            Qt.AlignmentFlag.AlignBottom,
        )

        self.player_stack = QStackedWidget()
        self.midi_table = QTableWidget(0, 4)
        self.midi_table.setAlternatingRowColors(True)
        self.midi_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.midi_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.midi_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.midi_table.verticalHeader().hide()
        self.midi_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.midi_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.midi_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.midi_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.midi_table.setColumnWidth(1, 182)
        self.midi_table.setColumnWidth(2, 82)
        self.midi_table.setColumnWidth(3, 92)
        self.midi_table.cellClicked.connect(
            lambda row, _column: self._select_midi_row(row)
        )
        self.midi_table.currentCellChanged.connect(
            lambda row, _column, _previous_row, _previous_column: QTimer.singleShot(
                0,
                lambda selected_row=row: self._select_midi_row(selected_row),
            )
        )
        self.midi_table.itemDoubleClicked.connect(lambda _item: self.controller.toggle_sound_playback())
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.player_stack.addWidget(self.midi_table)
        self.player_stack.addWidget(self.log_output)
        content_layout.addWidget(self.player_stack, 1)
        body.addWidget(content, 1)
        self.player_layout.addLayout(body, 1)

    @staticmethod
    def _make_player_transport_button(callback) -> InteractiveIconButton:  # type: ignore[no-untyped-def]
        button = InteractiveIconButton()
        button.setObjectName("PlayerTransportButton")
        button.setText("")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.set_interaction_scaling_enabled(False)
        button.clicked.connect(callback)
        return button

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
            language_changed = state.language != self._last_language
            if language_changed:
                self._apply_text(state)
                self._build_menus(state)
                if self._applied_scale:
                    self._apply_layout_scale(state.ui_scale_percent)
                self._last_language = state.language
            style_changed = (
                state.color_theme != self._last_theme
                or state.ui_scale_percent != self._applied_scale
            )
            if style_changed:
                old_scale = self._applied_scale or state.ui_scale_percent
                self.setStyleSheet(
                    build_stylesheet(
                        state.color_theme,
                        state.ui_scale_percent,
                    )
                )
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
            if state.window_opacity != self._applied_opacity:
                self.setWindowOpacity(state.window_opacity / 100)
                self._applied_opacity = state.window_opacity
            if state.always_on_top != self._applied_always_on_top:
                was_visible = self.isVisible()
                self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, state.always_on_top)
                self._applied_always_on_top = state.always_on_top
                if was_visible:
                    self.show()
            self._apply_panel_order(state.panel_order)
            self._apply_section_visibility(state)
            conversion_signature = (
                state.language,
                state.color_theme,
                state.ui_scale_percent,
                state.input_conversion_mode,
                state.midi_input_running,
                state.current_mode,
                state.section_visibility["input_conversion"],
            )
            if self._signature_changed("conversion", conversion_signature):
                self._render_conversion_controls(state)
            realtime_signature = (
                state.language,
                state.midi_input_running,
                state.current_mode,
                tuple(state.midi_input_devices),
                state.midi_input_device,
            )
            if self._signature_changed("realtime", realtime_signature):
                self._render_realtime(state)

            key_signature = (
                state.language,
                state.ui_scale_percent,
                state.current_mode,
                state.midi_input_running,
                state.countdown_seconds,
                state.countdown_sound,
                state.game_countdown_sound,
                state.keyboard_play_shortcut,
                state.keyboard_pause_shortcut,
                state.keyboard_stop_shortcut,
                state.shortcut_locked,
            )
            if self._signature_changed("key", key_signature):
                self._render_key_section(state)

            simultaneous_sound_and_realtime = (
                state.midi_input_running and state.sound_playing
            )
            keyboard_display_notes = (
                state.realtime_visible_output_notes
                if simultaneous_sound_and_realtime
                else state.active_output_notes
            )
            keyboard_retrigger_events = (
                state.realtime_output_retrigger_events
                if simultaneous_sound_and_realtime
                else state.output_note_retrigger_events
            )
            settings_signature = (
                state.input_conversion_mode,
                state.dry_run,
                state.auto_fit_note_range,
                state.repeat_prevention,
                state.humanize_timing,
                state.chord_strum,
                state.chord_optimization,
                state.auto_sustain,
            )
            if self._signature_changed("settings", settings_signature):
                self._render_settings(state)

            if state.section_visibility["keyboard"]:
                keyboard_visual_signature = (
                    keyboard_display_notes,
                    keyboard_retrigger_events,
                )
                if self._signature_changed(
                    "keyboard_visualization",
                    keyboard_visual_signature,
                ):
                    self._render_output_keyboard(
                        keyboard_display_notes,
                        keyboard_retrigger_events,
                    )
            piano_roll_running = self.controller.piano_roll_playback_running()
            self.position_slider.set_playback_running(piano_roll_running)
            if state.section_visibility["piano_roll"]:
                optimization_plan = (
                    self.controller.current_chord_optimization_plan()
                )
                piano_roll_sequence_signature = (
                    id(self.controller.events),
                    len(self.controller.events),
                    tuple(
                        (item.track, item.channel, item.enabled)
                        for item in state.track_channels
                    ),
                    state.auto_fit_note_range,
                    state.transpose_semitones,
                    state.octave_shift,
                    state.humanize_timing,
                    state.chord_optimization,
                    state.chord_strum,
                    state.repeat_prevention,
                    state.playback_speed_percent,
                    id(optimization_plan),
                )
                if self._signature_changed(
                    "piano_roll_sequence",
                    piano_roll_sequence_signature,
                ):
                    self.piano_roll.set_sequence_notes(
                        build_piano_roll_notes(
                            self.controller.events,
                            enabled_sources=self.controller.enabled_sources(),
                            enabled_channels=self.controller.enabled_channels(),
                            auto_fit_note_range=state.auto_fit_note_range,
                            transpose_semitones=state.transpose_semitones,
                            octave_shift=state.octave_shift,
                            chord_optimization_plan=(
                                optimization_plan
                                if state.chord_optimization
                                else None
                            ),
                            humanize_timing=state.humanize_timing,
                            chord_strum=state.chord_strum,
                            repeat_prevention=state.repeat_prevention,
                            playback_speed_percent=(
                                state.playback_speed_percent
                            ),
                        )
                    )
                piano_roll_playback_signature = (
                    state.position,
                    state.playback_speed_percent,
                    piano_roll_running,
                )
                if self._signature_changed(
                    "piano_roll_playback",
                    piano_roll_playback_signature,
                ):
                    self.piano_roll.set_playback_state(
                        state.position,
                        state.playback_speed_percent,
                        piano_roll_running,
                    )
                piano_roll_live_signature = (
                    state.active_output_notes,
                    state.realtime_output_notes,
                )
                if self._signature_changed(
                    "piano_roll_live",
                    piano_roll_live_signature,
                ):
                    self.piano_roll.set_live_state(
                        state.active_output_notes
                        | state.realtime_output_notes,
                        (),
                    )
                piano_roll_score_signature = (
                    state.rhythm_score,
                    state.rhythm_combo,
                    state.rhythm_judgment,
                    state.rhythm_multiplier_tenths,
                )
                if self._signature_changed(
                    "piano_roll_score",
                    piano_roll_score_signature,
                ):
                    self.piano_roll.set_score(
                        state.rhythm_score,
                        state.rhythm_combo,
                        state.rhythm_judgment,
                        state.rhythm_multiplier_tenths,
                    )
                if self._signature_changed(
                    "piano_roll_hits",
                    state.rhythm_hit_events,
                ):
                    self.piano_roll.set_hit_events(
                        state.rhythm_hit_events
                    )

            player_controls_signature = (
                state.language,
                state.midi_sound_volume,
                state.playback_speed_percent,
                state.transpose_semitones,
                state.octave_shift,
                state.sound_source,
                state.audio_qt_frames,
                state.audio_buffer_frames,
            )
            if self._signature_changed("player_controls", player_controls_signature):
                self._render_player_controls(state)
            transport_signature = (
                state.language,
                state.color_theme,
                state.ui_scale_percent,
                state.current_mode,
                state.selected_midi_index,
                len(state.midi_rows),
                state.sound_playback_mode,
            )
            if self._signature_changed("transport", transport_signature):
                self._render_transport_controls(state)
            if self._signature_changed("position", (state.position, state.duration)):
                self._render_player_position(state)
            if state.midi_rows is not self._rendered_midi_rows:
                self._rendered_midi_rows = state.midi_rows
                self._render_midi_rows(state)
                self._render_midi_selection(state)
                self._render_signatures["midi_selection"] = state.selected_midi_index
            elif self._signature_changed("midi_selection", state.selected_midi_index):
                self._render_midi_selection(state)
            if state.track_channels is not self._rendered_track_channels:
                self._rendered_track_channels = state.track_channels
                self._render_track_channels(state)
        finally:
            self._rendering = False

    def _signature_changed(self, name: str, signature: object) -> bool:
        if name in self._render_signatures and self._render_signatures[name] == signature:
            return False
        self._render_signatures[name] = signature
        return True

    def _apply_text(self, state: AppState) -> None:
        text = TEXT[state.language]
        self.setWindowTitle(text["title"])
        self.realtime_mode_radio.setText(text["midi_input_settings"])
        self.midi_file_mode_radio.setText(text["key_playback_settings"])
        self.device_label.setText("")
        self.device_label.setToolTip(text["midi_input_device"])
        self.device_label.setAccessibleName(text["midi_input_device"])
        self.device_icon_frame.setToolTip(text["midi_input_device"])
        self.device_icon_frame.setAccessibleName(text["midi_input_device"])
        self.countdown_label.setText("")
        self.countdown_label.setToolTip(text["countdown"])
        self.countdown_label.setAccessibleName(text["countdown"])
        self.countdown_icon_frame.setToolTip(text["countdown"])
        self.countdown_icon_frame.setAccessibleName(text["countdown"])
        self.countdown_control.setToolTip("")
        self.countdown_control.setAccessibleName(text["countdown"])
        self.seconds_label.setText(text["seconds_unit"])
        self.countdown_sound_check.setText(text["countdown_sound"])
        self.game_sound_check.setText(text["game_countdown_sound"])
        self.shortcut_caption.setText("")
        self.shortcut_caption.setToolTip(text["shortcut_settings"])
        self.shortcut_caption.setAccessibleName(text["shortcut_settings"])
        self.shortcut_icon_frame.setToolTip(text["shortcut_settings"])
        self.shortcut_icon_frame.setAccessibleName(text["shortcut_settings"])
        self.shortcut_start_label.setText(text["shortcut_start"])
        self.shortcut_pause_label.setText(text["shortcut_pause_resume"])
        self.shortcut_end_label.setText(text["shortcut_end"])
        self.shortcut_lock_check.setText(text["shortcut_lock"])
        self.dry_run_check.setText(text["dry_run"])
        self.auto_fit_check.setText(text["auto_fit_note_range"])
        self.repeat_check.setText(text["repeat_prevention"])
        self.humanize_check.setText(text["humanize_timing"])
        self.strum_check.setText(text["chord_strum"])
        self.optimization_check.setText(text["chord_optimization"])
        self.auto_sustain_check.setText(text["auto_sustain"])
        self.previous_track_button.setToolTip(text["previous_track"])
        self.previous_track_button.setAccessibleName(text["previous_track"])
        self.next_track_button.setToolTip(text["next_track"])
        self.next_track_button.setAccessibleName(text["next_track"])
        self.volume_control.label.setText(text["midi_sound_volume"])
        self.speed_control.label.setText(text["playback_speed"])
        self.transpose_control.label.setText(text["transpose_semitones"])
        self.octave_control.label.setText(text["octave_shift"])
        self.sound_source_label.setText(text["sound_source"])
        with QSignalBlocker(self.sound_source_combo):
            self.sound_source_combo.clear()
            for source, title in SOUND_SOURCE_NAMES[state.language].items():
                self.sound_source_combo.addItem(title, source)
        while self.tab_bar.count():
            self.tab_bar.removeTab(0)
        self.tab_bar.addTab(text["midi_list"])
        self.tab_bar.addTab(text["playback_log"])
        self._update_midi_tab_icon(state.color_theme, state.ui_scale_percent)
        self.midi_table.setHorizontalHeaderLabels(
            [
                text["name"],
                text["folder"],
                text["duration"],
                text["note_range"],
            ]
        )
        for column in range(self.midi_table.columnCount()):
            self.midi_table.horizontalHeaderItem(column).setTextAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )

    def _apply_layout_scale(self, percent: int) -> None:
        scale = percent / 100.0
        px = lambda value: max(1, round(value * scale))
        margin = px(12)
        self.root_layout.setContentsMargins(margin, margin, margin, margin)
        self.realtime_panel.apply_scale(scale)
        self.key_panel.apply_scale(scale)
        self.conversion_control_panel.setFixedHeight(px(85))
        self.conversion_control_layout.setContentsMargins(px(8), px(4), px(8), px(4))
        self.conversion_start_button.setFixedSize(px(55), px(55))
        for handle in self._panel_drag_handles.values():
            handle.apply_scale(scale)
        self._panel_insertion_indicator.apply_scale(scale)
        self.conversion_settings_stack.setFixedHeight(px(77))
        self.realtime_panel.setFixedHeight(px(77))
        self.key_panel.setFixedHeight(px(77))
        self.settings_panel.setFixedHeight(px(77))
        self.piano_roll_gap.setFixedHeight(px(6))
        self.piano_roll_panel.setFixedHeight(px(KEYBOARD_PANEL_HEIGHT))
        self.piano_roll_layout.setContentsMargins(
            px(KEYBOARD_PANEL_MARGIN),
            px(KEYBOARD_PANEL_MARGIN),
            px(KEYBOARD_PANEL_MARGIN),
            px(KEYBOARD_PANEL_MARGIN),
        )
        self.settings_lower_gap.setFixedHeight(px(6))
        self.settings_lower_panel.setFixedHeight(px(KEYBOARD_PANEL_HEIGHT))
        self.settings_lower_layout.setContentsMargins(
            px(KEYBOARD_PANEL_MARGIN),
            px(KEYBOARD_PANEL_MARGIN),
            px(KEYBOARD_PANEL_MARGIN),
            px(KEYBOARD_PANEL_MARGIN),
        )
        self.player_layout.setContentsMargins(px(8), px(8), px(8), px(8))
        settings_margin = px(10)
        self.settings_layout.setContentsMargins(
            settings_margin,
            settings_margin,
            settings_margin,
            settings_margin,
        )
        self.device_label.setFixedSize(px(28), px(28))
        self.device_combo.setMinimumWidth(px(288))
        self.device_refresh_button.setFixedWidth(px(34))
        self.device_icon_frame.setFixedWidth(px(36))
        self.device_icon_layout.setContentsMargins(px(3), px(3), px(3), px(3))
        self.device_controls_layout.setContentsMargins(px(12), px(8), px(12), px(8))
        self.device_group_layout.setContentsMargins(px(6), px(4), px(6), px(4))
        self.countdown_label.setFixedSize(px(28), px(28))
        self.shortcut_caption.setFixedSize(px(28), px(28))
        self.countdown_icon_frame.setFixedWidth(px(36))
        self.shortcut_icon_frame.setFixedWidth(px(36))
        self.countdown_icon_layout.setContentsMargins(px(3), px(3), px(3), px(3))
        self.shortcut_icon_layout.setContentsMargins(px(3), px(3), px(3), px(3))
        self.key_controls_layout.setContentsMargins(px(12), px(8), px(12), px(8))
        self.countdown_control.apply_scale(scale)
        shortcut_width = self._shortcut_edit_width(scale)
        self.shortcut_start_edit.setFixedWidth(shortcut_width)
        self.shortcut_pause_edit.setFixedWidth(shortcut_width)
        self.shortcut_end_edit.setFixedWidth(shortcut_width)
        self.countdown_group_layout.setContentsMargins(px(6), px(4), px(6), px(4))
        self.shortcut_group_layout.setContentsMargins(px(6), px(4), px(6), px(4))
        feature_group_height = px(44)
        self.device_icon_frame.setFixedHeight(feature_group_height)
        self.device_group.setFixedHeight(feature_group_height)
        self.countdown_icon_frame.setFixedHeight(feature_group_height)
        self.shortcut_icon_frame.setFixedHeight(feature_group_height)
        self.countdown_group.setFixedHeight(feature_group_height)
        self.shortcut_group.setFixedHeight(feature_group_height)
        self._set_spacer_width(self.key_controls_layout, 1, px(6))
        self._set_spacer_width(self.key_controls_layout, 3, px(10))
        self._set_spacer_width(self.key_controls_layout, 5, px(4))
        self.settings_grid.setHorizontalSpacing(px(12))
        self.settings_grid.setVerticalSpacing(px(6))
        self.output_keyboard.apply_scale(scale)
        self.piano_roll.apply_scale(scale)
        self.player_header_layout.setSpacing(0)
        self.player_header_layout.setRowMinimumHeight(2, px(10))
        self.position_row_layout.setSpacing(px(6))
        self.transport_layout.setSpacing(px(1))
        self.position_slider.setFixedHeight(px(24))
        self.time_label.setFixedWidth(px(80))
        transport_button_width = px(24)
        transport_button_height = px(28)
        for button in (
            self.previous_track_button,
            self.sound_play_pause_button,
            self.next_track_button,
            self.sound_playback_mode_button,
        ):
            button.setFixedSize(transport_button_width, transport_button_height)
        self.volume_control.apply_scale(scale)
        self.speed_control.apply_scale(scale)
        self.audio_runtime_label.setFixedWidth(px(158))
        self.audio_runtime_label.setFixedHeight(px(24))
        self.audio_runtime_label.setContentsMargins(0, 0, px(8), 0)
        self.slider_layout.setSpacing(px(2))
        self.slider_pane.setFixedWidth(self.speed_control.width())
        self.transpose_control.apply_scale(scale)
        self.octave_control.apply_scale(scale)
        self.transform_layout.setContentsMargins(0, 0, 0, 0)
        self._set_spacer_width(self.transform_layout, 1, px(12))
        self.transform_controls.setFixedWidth(
            self.transpose_control.width()
            + self.octave_control.width()
            + px(12)
        )
        self.track_channels.apply_scale(scale)
        self.track_channel_container.setFixedWidth(self.track_channels.width())
        player_control_height = px(36)
        list_control_height = px(28)
        self.track_channel_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        self.tab_bar.setFixedHeight(list_control_height)
        self.tab_bar_container.setFixedHeight(list_control_height)
        self.tab_bar_container_layout.setContentsMargins(0, 0, 0, 0)
        self.slider_pane.setFixedHeight(player_control_height)
        self.transform_controls.setFixedHeight(player_control_height)
        self.transport_left.setFixedHeight(player_control_height)
        self.transport_right.setFixedHeight(player_control_height)
        self._set_spacer_width(self.transport_left_layout, 3, px(1))
        self._set_spacer_width(self.transport_right_layout, 1, px(1))
        self._set_spacer_width(self.transport_right_layout, 3, px(1))
        self._update_transport_side_widths(scale)
        self.sound_source_controls.setFixedHeight(list_control_height)
        self.sound_source_combo.setFixedWidth(px(138))
        self.sound_source_layout.setContentsMargins(0, 0, 0, px(2))
        self.sound_source_layout.setSpacing(px(4))
        self.player_detail_gap.setFixedWidth(px(2))
        self.tab_row.setContentsMargins(
            self.track_channels.width() + self.player_detail_gap.width(),
            0,
            0,
            0,
        )
        self.midi_table.setColumnWidth(1, px(180))
        self.midi_table.setColumnWidth(2, px(80))
        self.midi_table.setColumnWidth(3, px(90))
        self.midi_table.horizontalHeader().setFixedHeight(px(24))
        for row in range(self.midi_table.rowCount()):
            self.midi_table.setRowHeight(row, px(22))
        self._set_spacer_width(self.device_controls_layout, 1, px(6))
        self._set_spacer_width(self.device_group_layout, 1, px(8))
        self._set_spacer_width(self.conversion_control_layout, 1, px(10))
        self._set_spacer_width(self.conversion_control_layout, 3, px(12))
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
        self._set_spacer_width(self.tab_row, 3, px(8))
        self.player_body_gap.setFixedHeight(0)
        self._update_section_gaps(
            self.state,
            self._effective_section_visibility(self.state),
        )
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
        scale = max(1.0, percent / 100)
        self.conversion_start_button.set_theme_backdrop(
            self.root_background,
            palette.canvas,
            min(6, round(4 * scale)),
        )
        for handle in self._panel_drag_handles.values():
            handle.set_color(palette.muted)
        self._panel_insertion_indicator.set_color(palette.accent)
        icon_size = max(12, round(16 * percent / 100))
        refresh_icon = make_refresh_icon(palette.text, icon_size)
        self.device_refresh_button.setIcon(refresh_icon)
        self.device_refresh_button.setIconSize(QSize(icon_size, icon_size))
        feature_icon_size = max(16, round(24 * percent / 100))
        feature_icon_color = palette.accent if theme_name == "dark" else palette.text
        self.device_label.setPixmap(
            make_feature_icon(
                "input_device",
                feature_icon_color,
                feature_icon_size,
            ).pixmap(feature_icon_size, feature_icon_size)
        )
        self.countdown_label.setPixmap(
            make_feature_icon(
                "countdown",
                feature_icon_color,
                feature_icon_size,
            ).pixmap(feature_icon_size, feature_icon_size)
        )
        self.shortcut_caption.setPixmap(
            make_feature_icon(
                "shortcut",
                feature_icon_color,
                feature_icon_size,
            ).pixmap(feature_icon_size, feature_icon_size)
        )
        self._update_midi_tab_icon(theme_name, percent)
        self.track_channels.set_colors(
            palette.accent,
            palette.accent_text,
            palette.canvas,
            palette.text,
        )
        for control in (
            self.volume_control,
            self.speed_control,
            self.transpose_control,
            self.octave_control,
            self.countdown_control,
        ):
            control.set_colors(
                palette.surface,
                palette.panel_alt,
                palette.border,
                palette.text,
                palette.accent,
                palette.accent_hover,
            )
        self.output_keyboard.set_colors(
            "#e8edf3" if theme_name == "dark" else palette.surface,
            palette.border,
            "#4b5563" if theme_name == "dark" else palette.muted,
            palette.accent,
            palette.accent_hover,
            palette.accent_text,
        )
        self.piano_roll.set_colors(
            "#000000",
            palette.border,
            palette.panel_alt,
            palette.accent,
            palette.accent_hover,
        )
        if theme_name == "sky_blue":
            whale_frames = tuple(
                str(resource_path(f"assets/whale_slider_frame_{index}.png"))
                for index in range(3)
            )
            self.position_slider.set_whale_handle_frames(
                whale_frames,
                max(1, round(24 * percent / 100)),
                2.0 * percent / 100,
            )
        else:
            self.position_slider.clear_whale_handle_frames()

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

    def _update_transport_side_widths(self, scale: float) -> None:
        gap = max(1, round(scale))
        self._set_spacer_width(self.transport_left_layout, 3, gap)
        left_content_width = (
            self.volume_control.width()
            + self.slider_pane.width()
            + gap
            + self.previous_track_button.minimumWidth()
        )
        right_content_width = (
            self.next_track_button.minimumWidth()
            + gap
            + self.sound_playback_mode_button.minimumWidth()
            + gap
            + self.transform_controls.width()
        )
        volume_knob_offset = (
            self.volume_control.width()
            - self.volume_control.knob.width()
            + self.volume_control.knob.rect().center().x()
        )
        octave_knob_offset = (
            right_content_width
            - self.octave_control.knob.width()
            + self.octave_control.knob.rect().center().x()
        )
        mirrored_side_width = volume_knob_offset + octave_knob_offset + gap
        transport_side_width = max(
            left_content_width,
            right_content_width,
            mirrored_side_width,
        )
        self.transport_left.setFixedWidth(transport_side_width)
        self.transport_right.setFixedWidth(transport_side_width)
        self.volume_control.layout().activate()
        self.octave_control.layout().activate()
        self.transform_layout.activate()
        self.transport_left_layout.activate()
        self.transport_right_layout.activate()
        volume_center = self.volume_control.knob.mapTo(
            self.transport_left,
            self.volume_control.knob.rect().center(),
        ).x()
        octave_center = self.octave_control.knob.mapTo(
            self.transport_right,
            self.octave_control.knob.rect().center(),
        ).x()
        measured_side_width = volume_center + octave_center + gap
        if measured_side_width > transport_side_width:
            self.transport_left.setFixedWidth(measured_side_width)
            self.transport_right.setFixedWidth(measured_side_width)
            self.transport_left_layout.activate()
            self.transport_right_layout.activate()
        volume_center = self.volume_control.knob.mapTo(
            self.transport_left,
            self.volume_control.knob.rect().center(),
        ).x()
        octave_center = self.octave_control.knob.mapTo(
            self.transport_right,
            self.octave_control.knob.rect().center(),
        ).x()
        speed_center = self.speed_control.knob.mapTo(
            self.transport_left,
            self.speed_control.knob.rect().center(),
        ).x()
        transpose_center = self.transpose_control.knob.mapTo(
            self.transport_right,
            self.transpose_control.knob.rect().center(),
        ).x()
        speed_gap = max(
            gap,
            gap
            + speed_center
            + transpose_center
            - volume_center
            - octave_center,
        )
        self._set_spacer_width(
            self.transport_left_layout,
            3,
            speed_gap,
        )
        self.transport_left_layout.activate()

    @staticmethod
    def _effective_section_visibility(state: AppState) -> tuple[bool, ...]:
        return tuple(
            state.section_visibility[panel_id]
            for panel_id in DEFAULT_PANEL_ORDER
        )

    def _update_section_gaps(
        self,
        state: AppState,
        visibility: tuple[bool, ...],
    ) -> None:
        scale = state.ui_scale_percent / 100.0
        gap_height = max(1, round(6 * scale))
        for gap in self._panel_gaps:
            gap.setFixedHeight(gap_height)
            gap.hide()
        order = normalize_panel_order(state.panel_order)
        panel_visibility = self._panel_visibility(visibility)
        visible_panels = [
            panel_id for panel_id in order if panel_visibility[panel_id]
        ]
        for panel_id in visible_panels[:-1]:
            position = order.index(panel_id)
            if position < len(self._panel_gaps):
                self._panel_gaps[position].show()

    @staticmethod
    def _panel_visibility(visibility: tuple[bool, ...]) -> dict[str, bool]:
        return dict(zip(DEFAULT_PANEL_ORDER, visibility, strict=True))

    def _apply_section_visibility(self, state: AppState) -> None:
        visibility = self._effective_section_visibility(state)
        previous = self._applied_section_visibility
        if visibility == previous:
            return

        if previous is not None:
            previous_panels = self._panel_visibility(previous)
            for panel_id, visible in previous_panels.items():
                if visible:
                    self._section_heights[panel_id] = max(
                        1,
                        self._panel_widgets[panel_id].height(),
                    )
            if self._full_visibility_height is None:
                self._full_visibility_height = (
                    self.height() + self._hidden_section_height(previous, state.ui_scale_percent)
                )

        self.conversion_control_panel.setVisible(visibility[0])
        self.realtime_mode_radio.setVisible(visibility[0])
        self.midi_file_mode_radio.setVisible(visibility[0])
        self.conversion_settings_stack.setVisible(visibility[0])
        self.settings_panel.setVisible(visibility[1])
        self.piano_roll_panel.setVisible(visibility[2])
        self.settings_lower_panel.setVisible(visibility[3])
        self.player_panel.setVisible(visibility[4])
        piano_roll_visibility_changed = (
            previous is None or previous[2] != visibility[2]
        )
        keyboard_visibility_changed = (
            previous is None or previous[3] != visibility[3]
        )
        if piano_roll_visibility_changed:
            self.piano_roll.set_rendering_enabled(
                visibility[2],
                latest_hit_events=state.rhythm_hit_events,
            )
            if visibility[2]:
                for signature in (
                    "piano_roll_sequence",
                    "piano_roll_playback",
                    "piano_roll_live",
                    "piano_roll_score",
                    "piano_roll_hits",
                ):
                    self._render_signatures.pop(signature, None)
        if keyboard_visibility_changed:
            simultaneous_sound_and_realtime = (
                state.midi_input_running and state.sound_playing
            )
            current_retrigger_events = (
                state.realtime_output_retrigger_events
                if simultaneous_sound_and_realtime
                else state.output_note_retrigger_events
            )
            self.output_keyboard.set_rendering_enabled(
                visibility[3],
                current_retrigger_events=current_retrigger_events,
            )
            if visibility[3]:
                self._render_signatures.pop(
                    "keyboard_visualization",
                    None,
                )
        for panel_id, panel in self._panel_widgets.items():
            self._section_heights.setdefault(
                panel_id,
                max(1, panel.sizeHint().height()),
            )
        self._update_section_gaps(state, visibility)
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
        panel_visibility = self._panel_visibility(visibility)
        full_panel_height = sum(
            self._section_heights.get(panel_id, 0)
            for panel_id in DEFAULT_PANEL_ORDER
        )
        visible_panel_height = sum(
            self._section_heights.get(panel_id, 0)
            for panel_id, visible in panel_visibility.items()
            if visible
        )
        scale = percent / 100.0
        gap_height = max(1, round(6 * scale))
        full_gap_height = gap_height * (len(DEFAULT_PANEL_ORDER) - 1)
        visible_count = sum(panel_visibility.values())
        visible_gap_height = gap_height * max(0, visible_count - 1)
        return max(
            0,
            full_panel_height + full_gap_height - visible_panel_height - visible_gap_height,
        )

    def _sync_full_visibility_height(self) -> None:
        visibility = self._applied_section_visibility
        if visibility is None:
            return
        for panel_id, visible in self._panel_visibility(visibility).items():
            if visible:
                self._section_heights[panel_id] = max(
                    1,
                    self._panel_widgets[panel_id].height(),
                )
        self._full_visibility_height = self.height() + self._hidden_section_height(
            visibility,
            self.state.ui_scale_percent,
        )

    def _render_realtime(self, state: AppState) -> None:
        text = TEXT[state.language]
        devices = state.midi_input_devices or [text["no_midi_input_devices"]]
        if [self.device_combo.itemText(i) for i in range(self.device_combo.count())] != devices:
            with QSignalBlocker(self.device_combo):
                self.device_combo.clear()
                self.device_combo.addItems(devices)
        with QSignalBlocker(self.device_combo):
            self.device_combo.setCurrentText(state.midi_input_device or devices[0])
        self.device_combo.setEnabled(not state.midi_input_running and bool(state.midi_input_devices))

    def _render_key_section(self, state: AppState) -> None:
        self.countdown_control.set_value(state.countdown_seconds)
        self._set_check(self.countdown_sound_check, state.countdown_sound)
        self._set_check(self.game_sound_check, state.game_countdown_sound)
        self.shortcut_start_edit.setText(state.keyboard_play_shortcut)
        self.shortcut_pause_edit.setText(state.keyboard_pause_shortcut)
        self.shortcut_end_edit.setText(state.keyboard_stop_shortcut)
        self._set_check(self.shortcut_lock_check, state.shortcut_locked)
        self.shortcut_start_edit.setEnabled(not state.shortcut_locked)
        self.shortcut_pause_edit.setEnabled(not state.shortcut_locked)
        self.shortcut_end_edit.setEnabled(not state.shortcut_locked)

    def _render_conversion_controls(self, state: AppState) -> None:
        text = TEXT[state.language]
        keyboard_active = state.keyboard_playing or state.keyboard_paused
        conversion_active = state.midi_input_running or keyboard_active
        with QSignalBlocker(self.realtime_mode_radio):
            self.realtime_mode_radio.setChecked(
                state.input_conversion_mode == INPUT_CONVERSION_REALTIME
            )
        with QSignalBlocker(self.midi_file_mode_radio):
            self.midi_file_mode_radio.setChecked(
                state.input_conversion_mode == INPUT_CONVERSION_MIDI_FILE
            )
        selected_panel = (
            self.realtime_panel
            if state.input_conversion_mode == INPUT_CONVERSION_REALTIME
            else self.key_panel
        )
        self.conversion_settings_stack.setCurrentWidget(selected_panel)
        self.conversion_settings_stack.setVisible(
            state.section_visibility["input_conversion"]
        )
        self.realtime_mode_radio.setEnabled(not conversion_active)
        self.midi_file_mode_radio.setEnabled(not conversion_active)

        if state.midi_input_running:
            button_text = text["stop_midi_input"]
        elif keyboard_active:
            button_text = text["stop_keys"]
        else:
            button_text = text["shortcut_start"]
        self.conversion_start_button.setText(button_text)
        self.conversion_start_button.setToolTip(button_text)
        self.conversion_start_button.setAccessibleName(button_text)
        self.conversion_start_button.setProperty("active", conversion_active)
        self.conversion_start_button.style().unpolish(self.conversion_start_button)
        self.conversion_start_button.style().polish(self.conversion_start_button)

        if conversion_active:
            enabled = True
        elif state.input_conversion_mode == INPUT_CONVERSION_REALTIME:
            enabled = state.current_mode not in {"keys", "keys_paused"}
        else:
            enabled = (
                state.current_mode in {None, "sound_paused"}
                and not state.midi_input_running
            )
        self.conversion_start_button.setEnabled(
            enabled and state.section_visibility["input_conversion"]
        )
        palette = THEMES.get(state.color_theme, THEMES["sky_blue"])
        if state.color_theme == "dark":
            icon_color = (
                palette.accent
                if self.conversion_start_button.isEnabled()
                else palette.muted
            )
        else:
            icon_color = (
                palette.accent
                if conversion_active
                else palette.text
                if self.conversion_start_button.isEnabled()
                else palette.disabled
            )
        icon_size = max(24, round(40 * state.ui_scale_percent / 100))
        if state.keyboard_paused:
            icon_action = "pause"
        elif conversion_active:
            icon_action = "stop"
        else:
            icon_action = "play"
        icon_signature = (
            icon_action,
            icon_color,
            icon_size,
        )
        if self._render_signatures.get("conversion_button_icon") != icon_signature:
            self._render_signatures["conversion_button_icon"] = icon_signature
            self.conversion_start_button.setIcon(
                make_transport_icon(icon_signature[0], icon_color, icon_size)
            )
            self.conversion_start_button.set_base_icon_size(
                QSize(icon_size, icon_size)
            )

    def _render_settings(self, state: AppState) -> None:
        for check, value in (
            (self.dry_run_check, state.dry_run),
            (self.auto_fit_check, state.auto_fit_note_range),
            (self.repeat_check, state.repeat_prevention),
            (self.humanize_check, state.humanize_timing),
            (self.strum_check, state.chord_strum),
            (self.optimization_check, state.chord_optimization),
            (self.auto_sustain_check, state.auto_sustain),
        ):
            self._set_check(check, value)
        unsupported_in_realtime = (
            state.input_conversion_mode == INPUT_CONVERSION_REALTIME
        )
        for check in (
            self.humanize_check,
            self.strum_check,
            self.optimization_check,
        ):
            check.setEnabled(True)
            if check.property("unsupported") != unsupported_in_realtime:
                check.setProperty("unsupported", unsupported_in_realtime)
                check.style().unpolish(check)
                check.style().polish(check)

    def _render_output_keyboard(
        self,
        active_notes: object,
        retrigger_events: object,
    ) -> None:
        self.output_keyboard.set_active_notes(active_notes)
        self.output_keyboard.set_retrigger_events(retrigger_events)

    def _render_player_controls(self, state: AppState) -> None:
        self.volume_control.set_value(state.midi_sound_volume)
        self.speed_control.set_value(state.playback_speed_percent)
        self.transpose_control.set_value(state.transpose_semitones)
        self.octave_control.set_value(state.octave_shift)
        source_index = self.sound_source_combo.findData(state.sound_source)
        if source_index >= 0:
            with QSignalBlocker(self.sound_source_combo):
                self.sound_source_combo.setCurrentIndex(source_index)
        self.audio_runtime_label.setText(
            TEXT[state.language]["audio_runtime"].format(
                qt=state.audio_qt_frames,
                buffer=state.audio_buffer_frames,
            )
        )

    def _render_transport_controls(self, state: AppState) -> None:
        text = TEXT[state.language]
        palette = THEMES.get(state.color_theme, THEMES["sky_blue"])
        blocked = state.keyboard_playing or state.keyboard_paused
        selected = state.selected_midi_index
        row_count = len(state.midi_rows)
        self.previous_track_button.setEnabled(not blocked and selected > 0)
        self.next_track_button.setEnabled(
            not blocked and 0 <= selected < row_count - 1
        )
        self.sound_play_pause_button.setEnabled(
            not blocked and 0 <= selected < row_count
        )
        self.sound_playback_mode_button.setEnabled(True)

        playing = state.sound_playing
        play_action = "pause" if playing else "play"
        play_text = text["pause_sound"] if playing else text["play_sound"]
        self.sound_play_pause_button.setToolTip(play_text)
        self.sound_play_pause_button.setAccessibleName(play_text)

        mode = state.sound_playback_mode
        if mode == SOUND_PLAYBACK_MODE_CONTINUOUS:
            mode_action = "repeat_all"
            mode_text = text["playback_mode_continuous"]
        elif mode == SOUND_PLAYBACK_MODE_REPEAT_ONE:
            mode_action = "repeat_one"
            mode_text = text["playback_mode_repeat_one"]
        else:
            mode_action = "repeat_off"
            mode_text = text["playback_mode_off"]
        self.sound_playback_mode_button.setToolTip(mode_text)
        self.sound_playback_mode_button.setAccessibleName(mode_text)

        icon_size = max(16, round(20 * state.ui_scale_percent / 100))
        navigation_color = palette.text
        disabled_color = palette.disabled
        button_icons = (
            (
                self.previous_track_button,
                "previous",
                navigation_color
                if self.previous_track_button.isEnabled()
                else disabled_color,
            ),
            (
                self.sound_play_pause_button,
                play_action,
                palette.accent
                if self.sound_play_pause_button.isEnabled()
                else disabled_color,
            ),
            (
                self.next_track_button,
                "next",
                navigation_color
                if self.next_track_button.isEnabled()
                else disabled_color,
            ),
            (
                self.sound_playback_mode_button,
                mode_action,
                palette.accent
                if mode != SOUND_PLAYBACK_MODE_OFF
                else navigation_color,
            ),
        )
        for button, action, color in button_icons:
            button.setIcon(make_transport_icon(action, color, icon_size))
            button.set_base_icon_size(QSize(icon_size, icon_size))
        self._update_transport_side_widths(
            state.ui_scale_percent / 100
        )

    def _render_player_position(self, state: AppState) -> None:
        duration = max(0.0, state.duration)
        slider_value = round(1000 * state.position / duration) if duration else 0
        with QSignalBlocker(self.position_slider):
            if not self.position_slider.is_user_drag_active():
                self.position_slider.setValue(slider_value)
        self.time_label.setText(
            f"{self.controller.format_time(state.position)} / {self.controller.format_time(duration)}"
        )

    def _render_midi_rows(self, state: AppState) -> None:
        had_focus = (
            self.midi_table.hasFocus()
            or self.midi_table.viewport().hasFocus()
        )
        with QSignalBlocker(self.midi_table):
            if self.midi_table.rowCount() != len(state.midi_rows):
                self.midi_table.setRowCount(len(state.midi_rows))
            for row_index, row in enumerate(state.midi_rows):
                for column, value in enumerate(
                    (row.name, row.folder, row.duration, row.note_range)
                ):
                    item = self.midi_table.item(row_index, column)
                    if item is None:
                        item = QTableWidgetItem()
                        self.midi_table.setItem(row_index, column, item)
                    if item.text() != value:
                        item.setText(value)
                    tooltip = value if column == 1 else ""
                    if item.toolTip() != tooltip:
                        item.setToolTip(tooltip)
                    path_text = str(row.path)
                    if item.data(Qt.ItemDataRole.UserRole) != path_text:
                        item.setData(Qt.ItemDataRole.UserRole, path_text)
                self.midi_table.setRowHeight(
                    row_index,
                    max(1, round(22 * state.ui_scale_percent / 100)),
                )
        if had_focus:
            self.midi_table.setFocus(Qt.FocusReason.OtherFocusReason)

    def _render_midi_selection(self, state: AppState) -> None:
        if 0 <= state.selected_midi_index < self.midi_table.rowCount():
            with QSignalBlocker(self.midi_table):
                if self.midi_table.currentRow() != state.selected_midi_index:
                    self.midi_table.setCurrentCell(
                        state.selected_midi_index,
                        0,
                    )
                self.midi_table.selectRow(state.selected_midi_index)
        else:
            self.midi_table.clearSelection()

    def _render_track_channels(self, state: AppState) -> None:
        self.track_channels.set_items(state.track_channels)

    def _build_menus(self, state: AppState) -> None:
        text = TEXT[state.language]
        self.menuBar().clear()
        file_menu = self.menuBar().addMenu(text["menu_midi"])
        load_action = file_menu.addAction(text["load_midi"])
        load_action.triggered.connect(self._choose_midi_folder)
        file_menu.addSeparator()
        file_menu.addAction(
            text["save_settings"],
            self.controller.save_settings_now,
        )
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
            ("input_conversion", "basic_screen_panel"),
            ("common_settings", "advanced_settings_panel"),
            ("piano_roll", "rhythm_game_panel"),
            ("keyboard", "keyboard_panel"),
            ("player", "player_panel"),
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
        other_menu.addAction(
            text["check_for_updates"],
            self.check_for_updates_manually,
        )
        other_menu.addSeparator()
        other_menu.addAction(text["release_notes"], self._open_release_notes)
        other_menu.addSeparator()
        other_menu.addAction(text["about_app"], self._open_about)

    def _set_option(self, name: str, value: object) -> None:
        if not self._rendering:
            self.controller.set_option(name, value)

    def eventFilter(self, watched, event) -> bool:  # type: ignore[no-untyped-def]
        if event.type() == QEvent.Type.MouseButtonPress:
            self._clear_input_focus_for_external_click(watched)
        return super().eventFilter(watched, event)

    def _clear_input_focus_for_external_click(self, watched: object) -> None:
        focused_widget = QApplication.focusWidget()
        focused_control = self._containing_focus_clear_control(focused_widget)
        if focused_control is None:
            return
        if self._containing_focus_clear_control(watched) is focused_control:
            return
        if focused_widget is not None:
            focused_widget.clearFocus()
        focused_control.clearFocus()

    def _containing_focus_clear_control(self, widget: object) -> QWidget | None:
        current = widget if isinstance(widget, QWidget) else None
        while current is not None:
            for control in self._focus_clear_controls:
                if current is control:
                    return control
                if isinstance(control, QComboBox) and (
                    current is control.view()
                    or current is control.view().viewport()
                ):
                    return control
            current = current.parentWidget()
        return None

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

    def _select_midi_row(self, row: int) -> None:
        if (
            self._rendering
            or row < 0
            or row == self.state.selected_midi_index
        ):
            return
        self.controller.select_midi(row)
        self.midi_table.setFocus(Qt.FocusReason.MouseFocusReason)

    def _seek_from_slider(self, slider_value: int) -> None:
        if self.state.duration:
            self.controller.seek(self.state.duration * slider_value / 1000)

    def _sound_source_changed(self, index: int) -> None:
        if self._rendering or index < 0:
            return
        sound_source = self.sound_source_combo.itemData(index)
        if sound_source:
            self.controller.set_option("sound_source", sound_source)

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

    def run_startup_tasks(self) -> None:
        self.show_pending_update_error()
        self.show_startup_release_notes()
        self.start_update_check()

    def start_update_check(
        self,
        manual: bool = False,
        current_time: int | None = None,
    ) -> bool:
        checked_at = int(time.time()) if current_time is None else int(current_time)
        if (
            not manual
            and not automatic_update_check_due(
                self.controller.last_update_check_at,
                checked_at,
            )
        ):
            return False
        if not self.update_service.check_for_updates(APP_VERSION):
            return False
        self._manual_update_check = manual
        self.controller.record_update_check(checked_at)
        return True

    def check_for_updates_manually(self) -> None:
        self.start_update_check(manual=True)

    def _update_check_completed(self, update: object) -> None:
        manual = self._manual_update_check
        self._manual_update_check = False
        if isinstance(update, AvailableUpdate):
            self._show_available_update(update)
            self._confirm_update()
            return
        if manual:
            self._show_no_updates_dialog()

    def _show_no_updates_dialog(self) -> None:
        text = TEXT[self.state.language]
        scale = self.state.ui_scale_percent / 100.0
        dialog = QDialog(self)
        dialog.setObjectName("UpdateStatusDialog")
        dialog.setWindowTitle(text["update_title"])
        dialog.setWindowIcon(self.windowIcon())
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setFixedWidth(round(300 * scale))

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(
            round(22 * scale),
            round(20 * scale),
            round(22 * scale),
            round(16 * scale),
        )
        layout.setSpacing(round(16 * scale))

        result = QHBoxLayout()
        result.setSpacing(round(10 * scale))
        result.addStretch(1)

        badge = QLabel("\u2713")
        badge.setObjectName("UpdateStatusBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge_size = round(28 * scale)
        badge.setFixedSize(badge_size, badge_size)
        result.addWidget(badge)

        message = QLabel(text["no_updates"])
        message.setObjectName("UpdateStatusMessage")
        message.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        result.addWidget(message)
        result.addStretch(1)
        layout.addLayout(result)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton(text["close"])
        close.setObjectName("UpdateStatusCloseButton")
        close.setDefault(True)
        close.setMinimumWidth(round(88 * scale))
        close.clicked.connect(dialog.accept)
        buttons.addWidget(close)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        dialog.exec()

    def _update_check_failed(self, error: str) -> None:
        manual = self._manual_update_check
        self._manual_update_check = False
        if not manual:
            return
        text = TEXT[self.state.language]
        QMessageBox.warning(
            self,
            text["update_error_title"],
            text["update_check_failed"].format(error=error),
        )

    def show_pending_update_error(self) -> None:
        message = read_pending_update_error()
        if not message:
            return
        text = TEXT[self.state.language]
        QMessageBox.warning(
            self,
            text["update_error_title"],
            message,
        )

    def _show_available_update(self, update: object) -> None:
        if not isinstance(update, AvailableUpdate):
            return
        self._available_update = update

    def _confirm_update(self) -> None:
        update = self._available_update
        if update is None:
            return
        text = TEXT[self.state.language]
        if not automatic_update_supported():
            QMessageBox.information(
                self,
                text["update_title"],
                text["update_not_supported"],
            )
            return
        answer = QMessageBox.question(
            self,
            text["update_title"],
            text["update_confirm"].format(
                current=APP_VERSION,
                version=update.version,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            self.controller.save_settings_now()
            started = launch_update_installer(
                update,
                process_id=os.getpid(),
                language=self.state.language,
            )
            if not started:
                raise RuntimeError("PowerShell updater did not start.")
        except Exception as exc:
            QMessageBox.critical(
                self,
                text["update_error_title"],
                f'{text["update_install_failed"]}\n{exc}',
            )
            return
        self.exit_application()

    def show_startup_release_notes(self) -> None:
        if not self.state.hide_release_notes_on_startup:
            self._open_release_notes()

    def _open_release_notes(self) -> None:
        text = TEXT[self.state.language]
        scale = self.state.ui_scale_percent / 100.0
        dialog = QDialog(self)
        dialog.setObjectName("ReleaseNotesDialog")
        dialog.setWindowTitle(text["release_notes"])
        dialog.resize(round(520 * scale), round(300 * scale))
        layout = QVBoxLayout(dialog)

        content = QPlainTextEdit()
        content.setObjectName("ReleaseNotesContent")
        content.setReadOnly(True)
        content.setPlainText(text["release_notes_content"])
        content.setMinimumHeight(round(190 * scale))
        layout.addWidget(content, 1)

        dont_show = QCheckBox(text["dont_show_again"])
        dont_show.setObjectName("ReleaseNotesDontShowAgain")
        dont_show.setChecked(self.state.hide_release_notes_on_startup)
        dont_show.toggled.connect(self._set_release_notes_hidden)
        layout.addWidget(dont_show)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton(text["close"])
        close.clicked.connect(dialog.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        dialog.exec()

    def _set_release_notes_hidden(self, hidden: bool) -> None:
        hidden = bool(hidden)
        if hidden == self.state.hide_release_notes_on_startup:
            return
        self.controller.set_option(
            "hide_release_notes_on_startup",
            hidden,
        )
        if hidden:
            self.controller.save_settings_now()

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

    def schedule_output_note_release(self, delay_ms: int) -> None:
        self._output_note_release_timer.start(max(1, int(delay_ms)))

    def schedule_rhythm_score_update(self, delay_ms: int | None) -> None:
        if delay_ms is None:
            self._rhythm_score_timer.stop()
            return
        self._rhythm_score_timer.start(max(1, int(delay_ms)))

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._closing_for_exit and self.state.tray_resident and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()
            self.hide()
            event.ignore()
            return
        self._closing_for_exit = True
        self.controller.set_event_notifier(None)
        self._output_note_release_timer.stop()
        if self._focus_filter_installed:
            application = QApplication.instance()
            if application is not None:
                application.removeEventFilter(self)
            self._focus_filter_installed = False
        event.accept()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        if not self._rendering and self.isVisible() and not self.isMaximized():
            self._sync_full_visibility_height()
            self.controller.set_window_geometry(self.width(), self.height())

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(event)
        self._update_transport_side_widths(
            self.state.ui_scale_percent / 100
        )
        if not self.isMaximized():
            self._sync_full_visibility_height()
            self.controller.set_window_geometry(self.width(), self.height())

    @staticmethod
    def _set_check(check: QCheckBox, checked: bool) -> None:
        with QSignalBlocker(check):
            check.setChecked(checked)

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
        self.special_edits: dict[str, BindingCaptureEdit] = {}
        text = TEXT[language]
        self.setWindowTitle(text["key_bindings"])
        self.resize(400, 480)
        root = QVBoxLayout(self)
        special_row = QGridLayout()
        special_row.setContentsMargins(0, 0, 0, 0)
        special_row.setHorizontalSpacing(6)
        special_row.setVerticalSpacing(2)
        special_bindings = controller.current_special_key_bindings()
        special_fields = (
            ("sustain", text["key_binding_sustain"]),
            ("octave_up", text["key_binding_octave_up"]),
            ("octave_down", text["key_binding_octave_down"]),
        )
        for name, caption in special_fields:
            label = QLabel(caption)
            edit = BindingCaptureEdit()
            edit.setFixedWidth(56)
            edit.setText(special_bindings[name])
            edit.shortcutCaptured.connect(
                lambda key, binding_name=name: self._special_binding_changed(binding_name, key)
            )
            row = len(self.special_edits)
            special_row.addWidget(label, row, 0)
            special_row.addWidget(edit, row, 1)
            self.special_edits[name] = edit
        root.addLayout(special_row)
        bindings_row = QHBoxLayout()
        bindings_row.setContentsMargins(0, 0, 0, 0)
        bindings_row.setSpacing(6)
        bindings_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
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
        for edit in self.special_edits.values():
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

    def _special_binding_changed(self, name: str, key: str) -> None:
        self.controller.set_special_key_binding(name, key)
        self._refresh_duplicates()

    def _restore_defaults(self) -> None:
        self.controller.reset_key_bindings()
        self.controller.reset_special_key_bindings()
        for note, key in self.controller.current_key_bindings().items():
            self.edits[note].setText(key)
        for name, key in self.controller.current_special_key_bindings().items():
            self.special_edits[name].setText(key)
        self._refresh_duplicates()

    def _refresh_duplicates(self) -> None:
        counts: dict[str, int] = {}
        all_edits = (*self.edits.values(), *self.special_edits.values())
        for edit in all_edits:
            counts[edit.text()] = counts.get(edit.text(), 0) + 1
        for edit in all_edits:
            edit.setStyleSheet("color: #c62828; font-weight: 600;" if counts.get(edit.text(), 0) > 1 else "")
