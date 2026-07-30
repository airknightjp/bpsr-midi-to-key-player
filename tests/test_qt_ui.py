from __future__ import annotations

import inspect
import os
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QStyleOptionSlider,
)

import main as app_main
import qt_main_window
from app_controller import AppController
from app_state import MidiListRow, TrackChannelItem
from config import (
    SOUND_PLAYBACK_MODE_CONTINUOUS,
    SOUND_PLAYBACK_MODE_OFF,
    SOUND_PLAYBACK_MODE_REPEAT_ONE,
)
from i18n import TEXT
from midi_parser import MidiEvent, MidiSummary, MidiTrackSummary
from note_visualization import PianoRollNote
from playlist_store import Playlist, PlaylistTrack
from qt_main_window import KeyBindingsDialog, MidiMainWindow
from qt_components import (
    ColumnSeparatorHeaderView,
    ContentPanel,
    FallingNotesWidget,
    InteractiveIconButton,
    PianoKeyboardWidget,
    ThemedBackground,
    TrackChannelButton,
    make_feature_icon,
)
from qt_styles import (
    THEMES,
    TOOLTIP_WAKE_UP_DELAY_MS,
    FastTooltipStyle,
    build_stylesheet,
    opaque_rgba,
)
from settings import AppSettings
from source_colors import track_channel_color
from update_service import AvailableUpdate, ReleaseAsset


class QtUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.save_settings_patch = patch("app_controller.save_settings")
        self.save_settings_mock = self.save_settings_patch.start()
        self.controller = AppController(AppSettings())
        self.window = MidiMainWindow(self.controller)

    def tearDown(self) -> None:
        self.window._closing_for_exit = True
        self.window.close()
        self.controller.shutdown()
        self.save_settings_patch.stop()

    def test_view_calls_controller_instead_of_playback_backends(self) -> None:
        source = inspect.getsource(qt_main_window)
        self.assertNotIn("MidiKeyboardPlayer", source)
        self.assertNotIn("MidiSoundPlayer", source)
        self.assertNotIn("MidiInputKeyboardBridge", source)
        self.assertNotIn("from settings import", source)

    def test_tooltips_open_after_the_short_application_delay(self) -> None:
        style = FastTooltipStyle("Fusion")
        self.assertEqual(
            style.styleHint(QStyle.StyleHint.SH_ToolTip_WakeUpDelay),
            TOOLTIP_WAKE_UP_DELAY_MS,
        )

    def test_position_change_updates_only_the_player_position_widgets(self) -> None:
        self.controller.state.duration = 120.0
        self.controller._notify()

        with (
            patch.object(
                self.window,
                "_render_player_position",
                wraps=self.window._render_player_position,
            ) as position_render,
            patch.object(
                self.window,
                "_render_realtime",
                wraps=self.window._render_realtime,
            ) as realtime_render,
            patch.object(
                self.window,
                "_render_key_section",
                wraps=self.window._render_key_section,
            ) as key_render,
            patch.object(
                self.window,
                "_render_settings",
                wraps=self.window._render_settings,
            ) as settings_render,
            patch.object(
                self.window,
                "_render_player_controls",
                wraps=self.window._render_player_controls,
            ) as controls_render,
            patch.object(
                self.window,
                "_render_midi_rows",
                wraps=self.window._render_midi_rows,
            ) as rows_render,
            patch.object(
                self.window,
                "_render_track_channels",
                wraps=self.window._render_track_channels,
            ) as sources_render,
        ):
            self.controller.state.position = 45.0
            self.controller._notify()

        position_render.assert_called_once()
        realtime_render.assert_not_called()
        key_render.assert_not_called()
        settings_render.assert_not_called()
        controls_render.assert_not_called()
        rows_render.assert_not_called()
        sources_render.assert_not_called()

    def test_position_time_text_changes_only_when_displayed_second_changes(self) -> None:
        self.controller.state.duration = 120.0
        self.controller.state.position = 0.0
        self.controller._notify()

        with patch.object(
            self.window.time_label,
            "setText",
            wraps=self.window.time_label.setText,
        ) as set_text:
            self.window.render_position(0.2, 120.0)
            set_text.assert_not_called()

            self.window.render_position(1.0, 120.0)
            set_text.assert_called_once_with("00:01 / 02:00")

    def test_player_has_midi_and_playlist_tabs(self) -> None:
        self.assertEqual(self.window.tab_bar.count(), 2)
        self.assertEqual(self.window.player_content_stack.count(), 2)
        self.assertFalse(self.window.tab_bar.usesScrollButtons())
        self.assertTrue(self.window.playlist_list.alternatingRowColors())
        self.assertTrue(
            self.window.playlist_track_table.alternatingRowColors()
        )
        self.assertIsInstance(
            self.window.playlist_list.horizontalHeader(),
            ColumnSeparatorHeaderView,
        )
        self.assertIsInstance(
            self.window.playlist_track_table.horizontalHeader(),
            ColumnSeparatorHeaderView,
        )
        self.assertEqual(self.window.playlist_list.columnCount(), 1)
        self.assertTrue(self.window.playlist_list.horizontalHeader().isHidden())
        self.window.show()
        self.window.tab_bar.setCurrentIndex(1)
        self.application.processEvents()
        self.assertGreaterEqual(
            self.window.tab_bar.width(),
            sum(
                self.window.tab_bar.tabRect(index).width()
                for index in range(self.window.tab_bar.count())
            ),
        )
        self.assertEqual(
            self.window.playlist_track_table.x(),
            self.window.playlist_list.x()
            + self.window.playlist_list.width()
            + 5,
        )
        initial_playlist_width = self.window.playlist_list.width()
        self.window.playlist_splitter.moveSplitter(
            initial_playlist_width + 20,
            1,
        )
        self.application.processEvents()
        self.assertGreater(
            self.window.playlist_list.width(),
            initial_playlist_width,
        )
        self.assertEqual(
            self.controller.current_settings().playlist_name_width,
            self.controller.state.playlist_name_width,
        )
        self.assertGreater(
            self.controller.state.playlist_name_width,
            240,
        )
        for language in ("en", "ja", "zh"):
            with self.subTest(language=language):
                self.controller.set_option("language", language)
                self.application.processEvents()
                self.assertFalse(self.window.tab_bar.usesScrollButtons())
                self.assertGreaterEqual(
                    self.window.tab_bar.width(),
                    sum(
                        self.window.tab_bar.tabRect(index).width()
                        for index in range(self.window.tab_bar.count())
                    ),
                )

    def test_playlist_tab_renders_playing_waiting_and_played_states(self) -> None:
        self.controller.state.playlists = [
            Playlist(
                "set",
                "Set",
                (
                    PlaylistTrack(Path("one.mid"), "one.mid", "01:00"),
                    PlaylistTrack(Path("two.mid"), "two.mid", "02:00"),
                    PlaylistTrack(Path("three.mid"), "three.mid", "03:00"),
                ),
            )
        ]
        self.controller.state.selected_playlist_index = 0
        self.controller.state.active_playlist_id = "set"
        self.controller.state.playlist_playback_active = True
        self.controller.state.playlist_current_track_index = 1
        self.controller._notify()

        self.assertEqual(self.window.playlist_list.item(0, 0).text(), "Set")
        self.assertEqual(
            self.window.playlist_track_table.horizontalHeaderItem(0).text(),
            "Name",
        )
        self.assertEqual(
            self.window.playlist_track_table.item(0, 0).text(),
            "one",
        )
        self.assertEqual(
            self.window.playlist_track_table.item(0, 2).text(),
            "Played",
        )
        self.assertEqual(
            self.window.playlist_track_table.item(1, 2).text(),
            "Playing",
        )
        self.assertEqual(
            self.window.playlist_track_table.item(2, 2).text(),
            "Waiting",
        )
        self.assertEqual(
            self.window.playlist_track_table.item(0, 2)
            .foreground()
            .color()
            .name(),
            "#188a45",
        )
        self.assertEqual(
            self.window.playlist_track_table.item(1, 2)
            .foreground()
            .color()
            .name(),
            "#0077cc",
        )
        self.assertEqual(
            self.window.playlist_track_table.item(2, 2)
            .foreground()
            .color()
            .name(),
            "#d6a400",
        )
        for row in range(3):
            for column in (0, 1):
                self.assertEqual(
                    self.window.playlist_track_table.item(row, column)
                    .foreground()
                    .style(),
                    Qt.BrushStyle.NoBrush,
                )
        self.controller.set_option("color_theme", "dark")
        self.application.processEvents()
        self.assertEqual(
            self.window.playlist_track_table.item(0, 2)
            .foreground()
            .color()
            .name(),
            "#66bb6a",
        )
        self.assertEqual(
            self.window.playlist_track_table.item(1, 2)
            .foreground()
            .color()
            .name(),
            "#64b5f6",
        )
        self.assertEqual(
            self.window.playlist_track_table.item(2, 2)
            .foreground()
            .color()
            .name(),
            "#ffd54f",
        )
        for row in range(3):
            for column in (0, 1):
                self.assertEqual(
                    self.window.playlist_track_table.item(row, column)
                    .foreground()
                    .style(),
                    Qt.BrushStyle.NoBrush,
                )
        self.controller.set_option("language", "ja")
        self.application.processEvents()
        self.assertEqual(
            self.window.playlist_track_table.item(0, 2).text(),
            "\u5b8c\u4e86",
        )
        self.assertEqual(
            self.window.playlist_track_table.item(1, 2).text(),
            "\u5b9f\u884c\u4e2d",
        )
        self.assertEqual(
            self.window.playlist_track_table.item(2, 2).text(),
            "\u30ad\u30e5\u30fc\u30a4\u30f3\u30b0",
        )

    def test_play_button_starts_selected_playlist_on_playlist_tab(self) -> None:
        self.controller.state.playlists = [
            Playlist(
                "set",
                "Set",
                (PlaylistTrack(Path("one.mid"), "one.mid", "01:00"),),
            )
        ]
        self.controller.state.selected_playlist_index = 0
        self.controller._notify()
        self.window.tab_bar.setCurrentIndex(1)

        with patch.object(
            self.controller,
            "toggle_playlist_playback",
        ) as toggle_playlist:
            self.window.sound_play_pause_button.click()

        toggle_playlist.assert_called_once_with()

    def test_playlist_tab_can_stop_regular_midi_without_a_playlist(self) -> None:
        self.controller.state.playlists = []
        self.controller.state.selected_playlist_index = -1
        self.controller.state.current_mode = "sound"
        self.controller._notify()
        self.window.tab_bar.setCurrentIndex(1)
        self.application.processEvents()

        self.assertTrue(self.window.sound_play_pause_button.isEnabled())
        with patch.object(
            self.controller,
            "toggle_playlist_playback",
        ) as toggle_playlist:
            self.window.sound_play_pause_button.click()

        toggle_playlist.assert_called_once_with()

    def test_piano_arrangement_controls_offer_beta_analysis(self) -> None:
        self.assertTrue(
            self.window.settings_panel.isAncestorOf(
                self.window.arrangement_controls
            )
        )
        self.assertFalse(
            self.window.player_panel.isAncestorOf(
                self.window.arrangement_controls
            )
        )
        self.assertTrue(self.window.use_arrangement_check.isChecked())
        self.assertFalse(self.window.use_arrangement_check.isEnabled())
        self.assertEqual(
            [
                self.window.arrangement_quality_combo.itemData(index)
                for index in range(
                    self.window.arrangement_quality_combo.count()
                )
            ],
            ["beta"],
        )
        self.controller.state.selected_midi_index = 0
        self.controller.state.midi_rows = [
            MidiListRow(Path("song.mid"), "song.mid")
        ]
        self.controller._notify()
        self.assertFalse(self.window.arrangement_analyze_button.isEnabled())

        self.controller.state.arrangement_status = "analyzing"
        self.controller.state.arrangement_progress = 42
        self.controller._notify()
        self.assertIn("42", self.window.arrangement_analyze_button.text())
        self.assertFalse(self.window.arrangement_quality_combo.isEnabled())
        self.assertFalse(self.window.use_arrangement_check.isEnabled())

    def test_arrangement_quality_is_beta(self) -> None:
        self.assertEqual(self.controller.state.arrangement_quality, "beta")
        self.assertEqual(
            self.window.arrangement_quality_combo.currentData(),
            "beta",
        )

    def test_arrangement_quality_popup_opens_below_combo(self) -> None:
        combo = self.window.arrangement_quality_combo
        combo.showPopup()
        QApplication.processEvents()
        expected_top = combo.mapToGlobal(QPoint(0, combo.height())).y()
        self.assertGreaterEqual(combo.view().window().y(), expected_top)
        combo.hidePopup()

    def test_use_arrangement_checkbox_updates_controller_state(self) -> None:
        self.window.use_arrangement_check.setChecked(False)

        self.assertFalse(
            self.controller.state.use_piano_arrangement
        )
        self.assertFalse(
            self.controller.current_settings().use_piano_arrangement
        )

    def test_arrangement_controls_remain_available_in_every_playback_state(
        self,
    ) -> None:
        self.controller.state.selected_midi_index = 0
        self.controller.state.midi_rows = [
            MidiListRow(Path("song.mid"), "song.mid")
        ]
        for current_mode, midi_input_running in (
            (None, False),
            ("sound", False),
            ("sound_paused", False),
            ("keys", False),
            ("keys_paused", False),
            (None, True),
            ("sound", True),
        ):
            with self.subTest(
                current_mode=current_mode,
                midi_input_running=midi_input_running,
            ):
                self.controller.state.current_mode = current_mode
                self.controller.state.midi_input_running = midi_input_running
                self.controller.state.arrangement_status = "idle"
                self.controller._notify()

                self.assertFalse(
                    self.window.arrangement_analyze_button.isEnabled()
                )
                self.assertFalse(
                    self.window.arrangement_quality_combo.isEnabled()
                )
                self.assertFalse(
                    self.window.use_arrangement_check.isEnabled()
                )

    def test_position_change_does_not_recalculate_output_note_range(self) -> None:
        self.controller.events = [
            MidiEvent(
                0.0,
                "note_on",
                channel=0,
                note=60,
                velocity=90,
                track=0,
            ),
            MidiEvent(
                1.0,
                "note_on",
                channel=0,
                note=72,
                velocity=90,
                track=0,
            ),
        ]
        self.controller.state.track_channels = (
            TrackChannelItem(track=0, channel=0, enabled=True),
        )

        with patch(
            "qt_main_window.build_output_note_range",
            wraps=qt_main_window.build_output_note_range,
        ) as range_builder:
            self.controller._notify()
            self.controller.state.position = 0.5
            self.controller._notify()

        range_builder.assert_called_once()

    def test_disabled_source_recalculates_output_note_range(self) -> None:
        self.controller.events = [
            MidiEvent(
                0.0,
                "note_on",
                channel=0,
                note=60,
                velocity=90,
                track=0,
            ),
            MidiEvent(
                1.0,
                "note_on",
                channel=1,
                note=84,
                velocity=90,
                track=1,
            ),
        ]
        self.controller._set_enabled_sources(((0, 0), (1, 1)))
        self.controller.state.track_channels = [
            TrackChannelItem(track=0, channel=0, enabled=True),
            TrackChannelItem(track=1, channel=1, enabled=True),
        ]
        self.controller._notify()

        self.assertEqual(self.window.output_keyboard.used_note_range, (60, 84))

        self.controller.toggle_track_channel(1, 1)

        self.assertEqual(self.window.output_keyboard.used_note_range, (60, 60))

    def test_worker_events_are_dispatched_without_a_poll_timer(self) -> None:
        self.assertFalse(hasattr(self.window, "_poll_timer"))
        worker = threading.Thread(
            target=lambda: self.controller._queue_worker_message(
                ("sound_output_note", self.controller.playback_id, 60, True)
            )
        )

        worker.start()
        worker.join()
        QTest.qWait(20)

        self.assertEqual(self.window.output_keyboard.active_notes, frozenset((60,)))

    def test_short_output_note_releases_without_polling(self) -> None:
        def emit_short_note() -> None:
            playback_id = self.controller.playback_id
            self.controller._queue_worker_message(
                ("sound_output_note", playback_id, 60, True)
            )
            self.controller._queue_worker_message(
                ("sound_output_note", playback_id, 60, False)
            )

        worker = threading.Thread(target=emit_short_note)
        worker.start()
        worker.join()
        QTest.qWait(20)
        self.assertEqual(self.window.output_keyboard.active_notes, frozenset((60,)))

        QTest.qWait(90)
        self.assertEqual(self.window.output_keyboard.active_notes, frozenset())

    def test_app_version_matches_documented_release_version(self) -> None:
        self.assertEqual(qt_main_window.APP_VERSION, "1.7.2")
        expected = f"v{qt_main_window.APP_VERSION}"
        project_root = Path(__file__).resolve().parents[1]
        for relative_path in (
            "README.md",
            "README.ja.md",
            "README.en.md",
            "README.zh-CN.md",
            "readme.txt",
        ):
            with self.subTest(path=relative_path):
                text = (project_root / relative_path).read_text(encoding="utf-8")
                self.assertIn(expected, text)
                self.assertNotIn("v1.1.2", text)
        for language in ("en", "ja", "zh"):
            with self.subTest(release_notes_language=language):
                self.assertTrue(
                    TEXT[language]["release_notes_content"].startswith(expected)
                )

    def test_all_languages_keep_countdown_and_shortcuts_on_one_row(self) -> None:
        self.window.show()
        for language in ("en", "ja", "zh"):
            with self.subTest(language=language):
                self.controller.set_option("language", language)
                self.application.processEvents()
                self.assertEqual(
                    self.window.countdown_group.geometry().center().y(),
                    self.window.shortcut_group.geometry().center().y(),
                )
                self.assertGreater(
                    self.window.shortcut_group.geometry().left(),
                    self.window.countdown_group.geometry().right(),
                )
                self.assertEqual(
                    self.window.shortcut_icon_frame.geometry().left()
                    - self.window.countdown_group.geometry().right()
                    - 1,
                    10,
                )
                self.assertEqual(self.window.countdown_control.knob.minimum(), 0)
                self.assertEqual(self.window.countdown_control.knob.maximum(), 10)
                self.assertFalse(self.window.countdown_control.label.isVisible())
                device_margins = self.window.device_controls_layout.contentsMargins()
                key_margins = self.window.key_controls_layout.contentsMargins()
                self.assertEqual(
                    (
                        device_margins.left(),
                        device_margins.top(),
                        device_margins.right(),
                        device_margins.bottom(),
                    ),
                    (12, 8, 12, 8),
                )
                self.assertEqual(
                    (
                        key_margins.left(),
                        key_margins.top(),
                        key_margins.right(),
                        key_margins.bottom(),
                    ),
                    (12, 8, 12, 8),
                )

    def test_input_device_countdown_and_shortcut_captions_use_circular_icons(self) -> None:
        expected_tooltips = {
            "en": ("Countdown", "Shortcut"),
            "ja": ("カウントダウン", "ショートカット"),
            "zh": ("倒计时", "快捷键"),
        }
        for language, tooltips in expected_tooltips.items():
            with self.subTest(language=language):
                self.controller.set_option("language", language)
                self.assertEqual(self.window.device_label.text(), "")
                self.assertEqual(self.window.countdown_label.text(), "")
                self.assertEqual(self.window.shortcut_caption.text(), "")
                self.assertEqual(
                    self.window.device_label.toolTip(),
                    TEXT[language]["midi_input_device"],
                )
                self.assertEqual(self.window.countdown_label.toolTip(), tooltips[0])
                self.assertEqual(self.window.shortcut_caption.toolTip(), tooltips[1])
                self.assertFalse(self.window.device_label.pixmap().isNull())
                self.assertFalse(self.window.countdown_label.pixmap().isNull())
                self.assertFalse(self.window.shortcut_caption.pixmap().isNull())
                self.assertEqual(
                    self.window.device_icon_frame.property("subgroup"),
                    True,
                )
                self.assertEqual(
                    self.window.countdown_icon_frame.property("subgroup"),
                    True,
                )
                self.assertEqual(
                    self.window.shortcut_icon_frame.property("subgroup"),
                    True,
                )

    def test_feature_icon_frames_match_their_setting_groups(self) -> None:
        self.window.show()
        self.controller.set_option("input_conversion_mode", "midi_file")
        for percent in (100, 110, 125, 150, 175, 200):
            with self.subTest(percent=percent):
                self.controller.set_option("ui_scale_percent", percent)
                self.application.processEvents()
                self.assertEqual(
                    self.window.device_icon_frame.height(),
                    self.window.device_group.height(),
                )
                self.assertEqual(
                    self.window.countdown_icon_frame.height(),
                    self.window.countdown_group.height(),
                )
                self.assertEqual(
                    self.window.shortcut_icon_frame.height(),
                    self.window.countdown_group.height(),
                )

    def test_feature_setting_groups_are_frameless(self) -> None:
        self.assertTrue(self.window.device_group.property("frameless"))
        self.assertTrue(self.window.countdown_group.property("frameless"))
        self.assertTrue(self.window.shortcut_group.property("frameless"))
        self.assertTrue(self.window.device_controls_frame.property("subgroup"))
        self.assertTrue(self.window.key_controls_frame.property("subgroup"))
        self.assertFalse(bool(self.window.device_controls_frame.property("frameless")))
        self.assertFalse(bool(self.window.key_controls_frame.property("frameless")))
        self.assertFalse(bool(self.window.device_icon_frame.property("frameless")))
        self.assertFalse(bool(self.window.countdown_icon_frame.property("frameless")))
        self.assertFalse(bool(self.window.shortcut_icon_frame.property("frameless")))
        self.assertIn(
            'QFrame[subgroup="true"][frameless="true"] {\n'
            "        border: none;",
            build_stylesheet("sky_blue", 100),
        )

    def test_feature_icons_follow_ui_scale(self) -> None:
        for percent in (100, 110, 125, 150, 175, 200):
            with self.subTest(percent=percent):
                self.controller.set_option("ui_scale_percent", percent)
                expected = round(24 * percent / 100)
                self.assertEqual(self.window.device_label.pixmap().width(), expected)
                self.assertEqual(self.window.countdown_label.pixmap().width(), expected)
                self.assertEqual(self.window.shortcut_caption.pixmap().width(), expected)

    def test_feature_icons_are_drawn(self) -> None:
        for feature in ("countdown", "input_device", "shortcut"):
            with self.subTest(feature=feature):
                icon = make_feature_icon(feature, "#12323b", 24)
                self.assertFalse(icon.isNull())

    def test_countdown_uses_a_knob_and_updates_the_setting(self) -> None:
        self.assertEqual(self.window.countdown_control.knob.minimum(), 0)
        self.assertEqual(self.window.countdown_control.knob.maximum(), 10)
        self.assertEqual(self.window.countdown_control.knob.value(), 0)

        self.window.countdown_control.knob.setValue(7)
        self.assertEqual(self.controller.state.countdown_seconds, 7)

        self.controller.set_option("countdown_seconds", 4)
        self.assertEqual(self.window.countdown_control.knob.value(), 4)

    def test_input_device_and_shortcut_icons_are_visually_distinct(self) -> None:
        input_device = make_feature_icon("input_device", "#12323b", 24).pixmap(24, 24)
        shortcut = make_feature_icon("shortcut", "#12323b", 24).pixmap(24, 24)

        self.assertNotEqual(
            input_device.toImage().convertToFormat(QImage.Format.Format_ARGB32).bits().tobytes(),
            shortcut.toImage().convertToFormat(QImage.Format.Format_ARGB32).bits().tobytes(),
        )

    def test_conversion_detail_panels_share_height_and_center_their_contents(self) -> None:
        self.window.show()
        self.controller.set_option("input_conversion_mode", "realtime")
        self.application.processEvents()

        self.assertEqual(self.window.realtime_panel.height(), self.window.key_panel.height())
        self.assertEqual(self.window.realtime_panel.height(), 77)
        self.assertEqual(self.window.conversion_control_panel.height(), 85)
        realtime_center = self.window.realtime_panel.rect().center().y()
        device_center = self.window.device_combo.mapTo(
            self.window.realtime_panel,
            self.window.device_combo.rect().center(),
        ).y()
        self.assertAlmostEqual(device_center, realtime_center, delta=1)

        self.controller.set_option("input_conversion_mode", "midi_file")
        self.application.processEvents()
        key_center = self.window.key_panel.rect().center().y()
        for control in (self.window.countdown_group, self.window.shortcut_group):
            with self.subTest(control=control.objectName() or type(control).__name__):
                control_center = control.mapTo(
                    self.window.key_panel,
                    control.rect().center(),
                ).y()
                self.assertAlmostEqual(control_center, key_center, delta=1)

    def test_conversion_container_matches_keyboard_panel_and_details_are_unframed(self) -> None:
        self.assertEqual(
            self.window.conversion_control_panel.objectName(),
            self.window.settings_lower_panel.objectName(),
        )
        self.assertFalse(bool(self.window.conversion_control_panel.property("subgroup")))
        for panel in (self.window.realtime_panel, self.window.key_panel):
            with self.subTest(panel=panel):
                self.assertIsInstance(panel, ContentPanel)
                self.assertIsNone(panel.property("section"))
        self.assertEqual(
            self.window.conversion_settings_stack.frameShape(),
            QFrame.Shape.NoFrame,
        )

    def test_each_main_panel_has_a_drag_handle(self) -> None:
        self.assertEqual(
            set(self.window._panel_drag_handles),
            {
                "input_conversion",
                "common_settings",
                "piano_roll",
                "keyboard",
                "player",
            },
        )
        for panel_id, handle in self.window._panel_drag_handles.items():
            with self.subTest(panel=panel_id):
                self.assertIs(handle.parentWidget(), self.window._panel_widgets[panel_id])
                self.assertEqual(handle.cursor().shape(), Qt.CursorShape.OpenHandCursor)

    def test_panel_drag_feedback_dims_source_and_tracks_insertion_line(self) -> None:
        self.window.show()
        self.application.processEvents()
        panel = self.window._panel_widgets["common_settings"]
        handle = self.window._panel_drag_handles["common_settings"]
        first_panel = self.window._panel_widgets["input_conversion"]
        original_geometry = panel.geometry()

        preview, hot_spot = handle._make_drag_preview(QPoint(2, 2))
        self.assertFalse(preview.isNull())
        self.assertGreater(preview.width(), 0)
        self.assertGreater(preview.height(), 0)
        self.assertEqual(preview.toImage().pixelColor(0, 0).alpha(), 0)
        center_color = preview.toImage().pixelColor(
            preview.width() // 2,
            preview.height() // 2,
        )
        self.assertGreater(center_color.alpha(), 0)
        self.assertLess(center_color.alpha(), 255)
        self.assertGreaterEqual(hot_spot.x(), 0)
        self.assertGreaterEqual(hot_spot.y(), 0)

        self.window._panel_drag_started("common_settings")
        self.application.processEvents()

        self.assertEqual(self.window._dragging_panel_id, "common_settings")
        self.assertIsNotNone(panel.graphicsEffect())
        self.assertAlmostEqual(panel.graphicsEffect().opacity(), 0.40)
        self.assertTrue(panel.isVisible())
        self.assertEqual(panel.geometry(), original_geometry)

        self.window._panel_drag_moved(
            "common_settings",
            first_panel.geometry().top(),
        )
        self.application.processEvents()
        indicator = self.window._panel_insertion_indicator
        self.assertTrue(indicator.isVisible())
        self.assertEqual(indicator.geometry().left(), first_panel.geometry().left())
        self.assertEqual(indicator.width(), first_panel.width())
        self.assertAlmostEqual(
            indicator.geometry().center().y(),
            first_panel.geometry().top(),
            delta=1,
        )

        self.window._panel_drag_finished("common_settings")
        self.application.processEvents()
        self.assertIsNone(self.window._dragging_panel_id)
        self.assertIsNone(panel.graphicsEffect())
        self.assertFalse(indicator.isVisible())

    def test_panel_drop_reorders_layout_and_persists_the_order(self) -> None:
        self.window.show()
        self.application.processEvents()
        first_panel = self.window._panel_widgets["input_conversion"]

        self.window._panel_dropped("player", first_panel.geometry().top())
        self.application.processEvents()

        self.assertEqual(self.controller.state.panel_order[0], "player")
        layout_order = tuple(
            panel_id
            for index in range(self.window.root_layout.count())
            for panel_id, panel in self.window._panel_widgets.items()
            if self.window.root_layout.itemAt(index).widget() is panel
        )
        self.assertEqual(layout_order, self.controller.state.panel_order)
        self.assertEqual(
            self.controller.current_settings().panel_order,
            self.controller.state.panel_order,
        )

    def test_reordered_hidden_panels_leave_only_required_gaps(self) -> None:
        self.window.show()
        self.controller.set_panel_order(
            (
                "player",
                "common_settings",
                "piano_roll",
                "keyboard",
                "input_conversion",
            )
        )
        self.controller.set_section_visible("common_settings", False)
        self.application.processEvents()

        self.assertEqual(
            sum(gap.isVisible() for gap in self.window._panel_gaps),
            3,
        )

    def test_conversion_start_button_uses_the_same_label_for_both_modes(self) -> None:
        self.controller.set_option("language", "ja")
        for mode in ("realtime", "midi_file"):
            with self.subTest(mode=mode):
                self.controller.set_option("input_conversion_mode", mode)
                self.assertEqual(self.window.conversion_start_button.text(), "開始")

    def test_conversion_start_button_uses_a_large_icon_only(self) -> None:
        self.assertEqual(
            self.window.conversion_start_button.toolButtonStyle(),
            Qt.ToolButtonStyle.ToolButtonIconOnly,
        )
        self.assertFalse(self.window.conversion_start_button.icon().isNull())
        self.assertEqual(self.window.conversion_start_button.iconSize(), QSize(40, 40))
        self.assertEqual(
            self.window.conversion_start_button.toolTip(),
            self.window.conversion_start_button.text(),
        )
        self.assertEqual(
            self.window.conversion_start_button.cursor().shape(),
            Qt.CursorShape.PointingHandCursor,
        )
        stylesheet = build_stylesheet("sky_blue", 100)
        self.assertIn("QToolButton#ConversionStartButton", stylesheet)
        start_rule = stylesheet.split(
            "QToolButton#ConversionStartButton {", 1
        )[1].split("}", 1)[0]
        self.assertIn("background: qlineargradient(", start_rule)
        self.assertIn("border: 1px solid", start_rule)
        self.assertIn("border-bottom: 2px solid", start_rule)
        self.assertIn("QToolButton#ConversionStartButton:focus", stylesheet)
        self.assertEqual(
            self.window.conversion_start_button.background_color.name(),
            THEMES["sky_blue"].canvas,
        )
        self.assertIsInstance(
            self.window.conversion_start_button,
            InteractiveIconButton,
        )

    def test_conversion_start_icon_reacts_inside_its_outer_frame(self) -> None:
        self.window.show()
        self.application.processEvents()
        button = self.window.conversion_start_button
        button.clearFocus()
        QApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
        self.assertEqual(button.iconSize(), QSize(40, 40))

        QApplication.sendEvent(button, QEvent(QEvent.Type.Enter))
        self.assertEqual(button.iconSize(), QSize(43, 43))

        QApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
        button.setFocus()
        self.application.processEvents()
        self.assertEqual(button.iconSize(), QSize(43, 43))

    def test_conversion_start_button_changes_icon_while_active(self) -> None:
        idle_icon = self.window.conversion_start_button.icon().cacheKey()

        self.controller.state.midi_input_running = True
        self.controller._notify()

        self.assertNotEqual(
            self.window.conversion_start_button.icon().cacheKey(),
            idle_icon,
        )
        self.assertTrue(self.window.conversion_start_button.property("active"))

    def test_conversion_start_button_shows_pause_icon_while_interrupted(
        self,
    ) -> None:
        self.controller.state.current_mode = "keys"
        self.controller._notify()
        active_icon = self.window.conversion_start_button.icon().cacheKey()
        self.assertEqual(
            self.window._render_signatures["conversion_button_icon"][0],
            "stop",
        )

        self.controller.state.current_mode = "keys_paused"
        self.controller._notify()

        self.assertEqual(
            self.window._render_signatures["conversion_button_icon"][0],
            "pause",
        )
        self.assertNotEqual(
            self.window.conversion_start_button.icon().cacheKey(),
            active_icon,
        )
        self.assertTrue(self.window.conversion_start_button.property("active"))

    def test_conversion_start_button_keeps_raised_feedback_in_dark_mode(self) -> None:
        stylesheet = build_stylesheet("dark", 100)
        self.assertIn(
            'QToolButton#ConversionStartButton[active="true"] {\n'
            "        background: qlineargradient(",
            stylesheet,
        )
        start_rule = stylesheet.split(
            "QToolButton#ConversionStartButton {", 1
        )[1].split("}", 1)[0]
        self.assertIn("border: 1px solid", start_rule)
        self.assertIn("border-bottom: 2px solid", start_rule)
        pressed_rule = stylesheet.split(
            "QToolButton#ConversionStartButton:pressed {", 1
        )[1].split("}", 1)[0]
        self.assertIn("padding-top: 2px;", pressed_rule)

        self.controller.set_option("color_theme", "dark")

        self.assertEqual(
            self.window._render_signatures["conversion_button_icon"][1],
            THEMES["dark"].accent,
        )

    def test_conversion_start_button_paints_a_distinct_raised_surface(self) -> None:
        button = self.window.conversion_start_button
        self.window.show()
        for theme_name in ("green", "sky_blue"):
            with self.subTest(theme=theme_name):
                self.controller.set_option("color_theme", theme_name)
                self.application.processEvents()
                image = button.grab().toImage()
                sample = button.rect().center()
                sample.setX(5)
                actual = image.pixelColor(sample)
                if theme_name == "sky_blue":
                    origin = button.mapTo(self.window.root_background, sample)
                    backdrop = self.window.root_background._ocean_pixmap.toImage().pixelColor(
                        origin
                    )
                else:
                    backdrop = QColor(THEMES[theme_name].canvas)
                self.assertNotEqual(actual, backdrop)

    def test_conversion_start_icon_size_follows_every_ui_scale(self) -> None:
        for percent in (100, 110, 125, 150, 175, 200):
            with self.subTest(percent=percent):
                self.controller.set_option("ui_scale_percent", percent)
                expected = round(40 * percent / 100)
                self.assertEqual(
                    self.window.conversion_start_button.iconSize(),
                    QSize(expected, expected),
                )

    def test_conversion_active_button_uses_end_in_every_language_and_mode(self) -> None:
        expected = {
            "en": "End",
            "ja": "\u7d42\u4e86",
            "zh": "\u7ed3\u675f",
        }
        for language, label in expected.items():
            with self.subTest(language=language, mode="midi_file"):
                self.controller.set_option("language", language)
                self.controller.state.current_mode = "keys"
                self.controller.state.midi_input_running = False
                self.controller._notify()
                self.assertEqual(self.window.conversion_start_button.text(), label)

            with self.subTest(language=language, mode="realtime"):
                self.controller.state.current_mode = None
                self.controller.state.midi_input_running = True
                self.controller._notify()
                self.assertEqual(self.window.conversion_start_button.text(), label)

        self.controller.state.current_mode = None
        self.controller.state.midi_input_running = False
        self.controller._notify()

    def test_pause_resume_shortcut_is_between_start_and_end(self) -> None:
        self.controller.set_option("shortcut_locked", False)
        self.window.show()
        self.application.processEvents()

        self.assertLess(
            self.window.shortcut_start_edit.geometry().right(),
            self.window.shortcut_pause_label.geometry().left(),
        )
        self.assertLess(
            self.window.shortcut_pause_edit.geometry().right(),
            self.window.shortcut_end_label.geometry().left(),
        )
        self.assertEqual(self.window.shortcut_start_edit.text(), "F9")
        self.assertEqual(self.window.shortcut_pause_edit.text(), "F10")
        self.assertEqual(self.window.shortcut_end_edit.text(), "F11")
        self.assertTrue(self.window.shortcut_pause_edit.isEnabled())

        self.controller.set_option("language", "ja")
        self.application.processEvents()
        self.assertEqual(self.window.shortcut_pause_label.text(), "\u4e2d\u65ad")

        self.controller.set_option("shortcut_locked", True)
        self.assertFalse(self.window.shortcut_pause_edit.isEnabled())

    def test_selectors_and_shortcut_inputs_lose_focus_when_clicking_elsewhere(self) -> None:
        self.controller.set_option("shortcut_locked", False)
        self.window.show()
        self.application.processEvents()
        controls = (
            self.window.sound_source_combo,
            self.window.audio_qt_combo,
            self.window.audio_buffer_combo,
            self.window.shortcut_start_edit,
            self.window.shortcut_pause_edit,
            self.window.shortcut_end_edit,
        )

        for control in controls:
            with self.subTest(control=control.objectName() or type(control).__name__):
                line_edit = control.lineEdit() if hasattr(control, "lineEdit") else None
                focus_target = line_edit or control
                focus_target.setFocus()
                self.application.processEvents()
                self.assertTrue(control.hasFocus() or focus_target.hasFocus())

                QTest.mouseClick(
                    self.window.settings_panel,
                    Qt.MouseButton.LeftButton,
                    pos=QPoint(self.window.settings_panel.width() - 4, 4),
                )
                self.application.processEvents()

                self.assertFalse(control.hasFocus())
                self.assertFalse(focus_target.hasFocus())
                self.assertTrue(self.window.settings_panel.hasFocus())

    def test_clicking_inside_the_same_selector_keeps_focus(self) -> None:
        self.window.show()
        self.application.processEvents()
        selector = self.window.sound_source_combo
        selector.setFocus()

        QTest.mouseClick(selector, Qt.MouseButton.LeftButton)
        self.application.processEvents()

        self.assertIn(
            QApplication.focusWidget(),
            (
                selector,
                selector.view(),
                selector.view().viewport(),
            ),
        )

    def test_common_button_stays_enabled_to_stop_key_playback(self) -> None:
        self.controller.set_option("input_conversion_mode", "realtime")
        self.controller.state.current_mode = "keys"
        self.controller._notify()

        self.assertTrue(self.window.conversion_start_button.isEnabled())
        self.assertFalse(self.window.realtime_mode_radio.isEnabled())
        self.assertFalse(self.window.midi_file_mode_radio.isEnabled())

        self.controller.state.current_mode = None
        self.controller.state.midi_input_running = True
        self.controller._notify()

        self.assertTrue(self.window.conversion_start_button.isEnabled())

    def test_common_start_button_stays_enabled_for_realtime_during_sound_playback(self) -> None:
        self.controller.set_option("input_conversion_mode", "realtime")
        self.controller.state.current_mode = "sound"
        self.controller._notify()

        self.assertTrue(self.window.conversion_start_button.isEnabled())

    def test_midi_file_start_button_is_enabled_while_sound_is_paused(self) -> None:
        self.controller.set_option("input_conversion_mode", "midi_file")
        self.controller.state.current_mode = "sound_paused"
        self.controller.state.position = 12.0
        self.controller._notify()

        self.assertTrue(self.window.conversion_start_button.isEnabled())

    def test_midi_file_start_button_is_enabled_during_sound_playback(self) -> None:
        self.controller.set_option("input_conversion_mode", "midi_file")
        self.controller.state.current_mode = "sound"
        self.controller._notify()

        self.assertTrue(self.window.conversion_start_button.isEnabled())
        self.assertFalse(
            self.window.conversion_start_button.property("active")
        )

    def test_common_start_button_uses_the_selected_conversion_mode(self) -> None:
        self.assertFalse(hasattr(self.window, "realtime_button"))
        self.assertFalse(hasattr(self.window, "keyboard_play_button"))

        with patch.object(self.controller, "start_midi_input") as start_realtime:
            self.window.realtime_mode_radio.click()
            self.window.conversion_start_button.click()
        start_realtime.assert_called_once_with()

        with patch.object(self.controller, "play_keyboard") as start_midi_file:
            self.window.midi_file_mode_radio.click()
            self.window.conversion_start_button.click()
        start_midi_file.assert_called_once_with()

    def test_conversion_selector_shows_only_the_selected_input_settings(self) -> None:
        self.window.show()
        self.controller.set_option("input_conversion_mode", "realtime")
        self.application.processEvents()

        self.assertTrue(self.window.realtime_panel.isVisibleTo(self.window))
        self.assertTrue(self.window.key_panel.isHidden())
        self.assertIs(
            self.window.conversion_settings_stack.currentWidget(),
            self.window.realtime_panel,
        )

        self.controller.set_option("input_conversion_mode", "midi_file")
        self.application.processEvents()

        self.assertTrue(self.window.realtime_panel.isHidden())
        self.assertTrue(self.window.key_panel.isVisibleTo(self.window))
        self.assertIs(
            self.window.conversion_settings_stack.currentWidget(),
            self.window.key_panel,
        )

    def test_conversion_detail_panels_have_no_duplicate_title_and_align_left(self) -> None:
        self.window.show()
        self.controller.set_option("input_conversion_mode", "realtime")
        self.application.processEvents()

        self.assertEqual(self.window.device_controls_frame.geometry().left(), 0)

        self.controller.set_option("input_conversion_mode", "midi_file")
        self.application.processEvents()

        self.assertEqual(self.window.key_controls_frame.geometry().left(), 0)
        self.assertLess(
            self.window.key_controls_frame.geometry().right(),
            self.window.key_panel.body.width(),
        )

    def test_conversion_selector_fits_at_every_language_and_scale(self) -> None:
        self.window.show()
        for language in ("en", "ja", "zh"):
            for scale in (100, 125, 150, 200):
                with self.subTest(language=language, scale=scale):
                    self.controller.set_option("language", language)
                    self.controller.set_option("ui_scale_percent", scale)
                    self.application.processEvents()

                    self.assertLess(
                        self.window.conversion_start_button.geometry().right(),
                        self.window.conversion_mode_panel.geometry().left(),
                    )
                    self.assertEqual(
                        self.window.realtime_mode_radio.geometry().left(),
                        self.window.midi_file_mode_radio.geometry().left(),
                    )
                    self.assertLess(
                        self.window.realtime_mode_radio.geometry().bottom(),
                        self.window.midi_file_mode_radio.geometry().top(),
                    )
                    self.assertLess(
                        self.window.conversion_mode_panel.geometry().right(),
                        self.window.conversion_settings_stack.geometry().left(),
                    )
                    self.assertLessEqual(
                        self.window.conversion_settings_stack.geometry().right(),
                        self.window.conversion_control_panel.contentsRect().right(),
                    )
                    self.assertAlmostEqual(
                        self.window.conversion_start_button.geometry().center().y(),
                        self.window.conversion_settings_stack.geometry().center().y(),
                        delta=2,
                    )
                    self.assertEqual(
                        self.window.conversion_start_button.width(),
                        round(55 * scale / 100),
                    )
                    self.assertEqual(
                        self.window.conversion_start_button.height(),
                        round(55 * scale / 100),
                    )

    def test_midi_sound_list_stays_enabled_during_realtime_input(self) -> None:
        self.controller.state.midi_input_running = True
        self.controller._notify()

        self.assertTrue(self.window.midi_table.isEnabled())

    def test_clicking_a_midi_row_selects_it_once(self) -> None:
        midi_paths = (Path("first.mid"), Path("second.mid"))
        self.controller.midi_files = list(midi_paths)
        self.controller.state.midi_rows = [
            MidiListRow(path, path.name)
            for path in midi_paths
        ]
        self.controller.state.selected_midi_index = 0
        self.controller._notify()
        self.window.show()
        self.application.processEvents()
        self.window.conversion_start_button.setFocus()
        self.assertFalse(self.window.midi_table.hasFocus())
        second_item = self.window.midi_table.item(1, 0)
        second_rect = self.window.midi_table.visualItemRect(second_item)

        def parse_selected(path: Path):
            return (
                [MidiEvent(0.0, "note_on", 0, 60, 80, track=0)],
                MidiSummary(
                    path=path,
                    duration=1.0,
                    channels=(0,),
                    event_count=1,
                    tracks=(MidiTrackSummary(index=0, channels=(0,)),),
                    note_range=(60, 60),
                ),
            )

        with patch.object(
            self.controller.midi_parser_process,
            "parse",
            side_effect=parse_selected,
        ):
            QTest.mouseClick(
                self.window.midi_table.viewport(),
                Qt.MouseButton.LeftButton,
                pos=second_rect.center(),
            )
        self.application.processEvents()

        self.assertEqual(self.controller.state.selected_midi_index, 1)
        self.assertEqual(self.window.midi_table.currentRow(), 1)
        self.assertEqual(
            [index.row() for index in self.window.midi_table.selectionModel().selectedRows()],
            [1],
        )
        self.assertTrue(self.window.midi_table.hasFocus())
        self.assertIs(self.window.midi_table.item(1, 0), second_item)

    def test_key_binding_places_octave_up_above_octave_down(self) -> None:
        dialog = KeyBindingsDialog(self.controller, "ja", self.window)
        dialog.show()
        self.application.processEvents()

        self.assertLess(
            dialog.special_edits["octave_up"].geometry().top(),
            dialog.special_edits["octave_down"].geometry().top(),
        )
        dialog.close()

    def test_default_window_width_resolves_to_minimum_at_100_percent(self) -> None:
        self.controller.set_option("ui_scale_percent", 100)
        self.window.resize(900, 560)
        self.window.show()
        self.application.processEvents()

        expected_width = max(900, self.window.minimumSizeHint().width())
        self.assertEqual(self.window.width(), expected_width)

    def test_key_binding_dialog_uses_compact_horizontal_spacing(self) -> None:
        for scale in (100, 110, 125, 150, 175, 200):
            with self.subTest(scale=scale):
                self.controller.set_option("ui_scale_percent", scale)
                self.application.processEvents()
                dialog = qt_main_window.KeyBindingsDialog(self.controller, "ja", self.window)
                dialog.show()
                self.application.processEvents()

                for note in (48, 60, 72):
                    label = dialog.note_labels[note]
                    edit = dialog.edits[note]
                    self.assertEqual(edit.geometry().left() - label.geometry().right() - 1, 6)
                    self.assertGreaterEqual(edit.width(), 56)
                    self.assertLessEqual(
                        edit.fontMetrics().horizontalAdvance("space") + round(16 * scale / 100),
                        edit.width(),
                    )
                    self.assertEqual(edit.visibleRegion().boundingRect().width(), edit.width())

                first_edit = dialog.edits[48]
                second_label = dialog.note_labels[60]
                first_right = first_edit.mapTo(dialog, QPoint(0, 0)).x() + first_edit.width()
                second_left = second_label.mapTo(dialog, QPoint(0, 0)).x()
                self.assertLessEqual(second_left - first_right, 6)
                last_edit = dialog.edits[72]
                last_right = last_edit.mapTo(dialog, QPoint(0, 0)).x() + last_edit.width()
                self.assertLessEqual(dialog.width() - last_right, 12)
                dialog.close()

    def test_track_channel_header_is_hidden_and_rows_keep_combined_values(self) -> None:
        self.controller.state.track_channels = [TrackChannelItem(0, 0), TrackChannelItem(1, 2)]
        self.controller._notify()

        self.assertEqual(self.window.track_channels.columnCount(), 1)
        self.assertTrue(self.window.track_channels.horizontalHeader().isHidden())
        self.assertEqual(self.window.track_channels.item(0, 0).text(), "")
        self.assertEqual(self.window.track_channels.item(1, 0).text(), "")
        button = self.window.track_channels.cellWidget(0, 0)
        self.assertIsInstance(button, TrackChannelButton)
        self.assertEqual(button.text(), "11")
        self.assertEqual(button.font().pixelSize(), 9)
        self.assertEqual(self.window.track_channels.rowHeight(0), 22)
        self.assertGreaterEqual(
            self.window.track_channels.rowHeight(0) - button._diameter,
            4,
        )
        header = self.window.track_channels.horizontalHeader()
        self.assertEqual(header.sectionSize(0), 20)
        self.window.show()
        self.application.processEvents()
        QTest.mouseMove(button, button.rect().center())
        self.application.processEvents()
        self.assertEqual(self.window.track_channels.item(0, 0).text(), "")
        self.assertEqual(button.text(), "11")
        button.setText("1216")
        self.assertFalse(button.grab().isNull())
        self.assertEqual(self.window.track_channels.font().pixelSize(), 11)

    def test_track_channel_table_has_no_rectangular_background_or_border(self) -> None:
        table_rule = self.window.styleSheet().split(
            "QTableWidget#TrackChannelTable {",
            1,
        )[1].split("}", 1)[0]

        self.assertIn("background: transparent", table_rule)
        self.assertIn("border: none", table_rule)
        self.assertNotIn("border-radius", table_rule)

    def test_track_channel_round_button_toggles_its_source(self) -> None:
        self.controller.state.track_channels = [TrackChannelItem(0, 0, True)]
        self.controller._set_enabled_sources(((0, 0),))
        self.controller._notify()
        self.window.show()
        self.application.processEvents()
        button = self.window.track_channels.cellWidget(0, 0)

        self.assertIsInstance(button, TrackChannelButton)
        self.assertTrue(button.isChecked())
        QTest.mouseClick(
            button,
            Qt.MouseButton.LeftButton,
            pos=button.rect().center(),
        )

        self.assertFalse(self.controller.state.track_channels[0].enabled)
        self.assertFalse(button.isChecked())

    def test_combined_track_channel_button_toggles_only_its_source(self) -> None:
        self.controller.state.track_channels = [
            TrackChannelItem(0, 0, True),
            TrackChannelItem(0, 1, True),
            TrackChannelItem(1, 0, True),
        ]
        self.controller._set_enabled_sources(((0, 0), (0, 1), (1, 0)))
        self.controller._notify()
        self.window.show()
        self.application.processEvents()
        first_button = self.window.track_channels.cellWidget(0, 0)
        second_button = self.window.track_channels.cellWidget(1, 0)

        self.assertTrue(first_button.isChecked())
        self.assertTrue(second_button.isChecked())
        QTest.mouseClick(
            first_button,
            Qt.MouseButton.LeftButton,
            pos=first_button.rect().center(),
        )

        self.assertFalse(self.controller.state.track_channels[0].enabled)
        self.assertTrue(self.controller.state.track_channels[1].enabled)
        self.assertTrue(self.controller.state.track_channels[2].enabled)
        self.assertFalse(first_button.isChecked())
        self.assertTrue(second_button.isChecked())

    def test_scale_changes_stylesheet_and_keeps_sections_visible(self) -> None:
        self.controller.set_option("input_conversion_mode", "realtime")
        self.window.resize(self.window.minimumSizeHint().expandedTo(self.window.size()))
        self.window.show()
        self.application.processEvents()
        original = self.window.styleSheet()
        original_width = self.window.width()
        original_margin = self.window.root_layout.contentsMargins().left()
        original_track_width = self.window.track_channels.width()
        original_sections = {
            "realtime": self.window.realtime_panel.size(),
            "settings": self.window.settings_panel.size(),
            "player": self.window.player_panel.size(),
        }

        self.controller.set_option("ui_scale_percent", 150)
        self.application.processEvents()

        self.assertNotEqual(self.window.styleSheet(), original)
        self.assertAlmostEqual(self.window.width() / original_width, 1.5, delta=0.03)
        self.assertEqual(self.window.root_layout.contentsMargins().left(), round(original_margin * 1.5))
        self.assertEqual(self.window.track_channels.width(), round(original_track_width * 1.5))
        self.assertEqual(self.controller.state.window_width, self.window.width())
        self.assertEqual(self.controller.state.window_height, self.window.height())
        for name, original_size in original_sections.items():
            scaled_size = getattr(self.window, f"{name}_panel").size()
            self.assertAlmostEqual(
                scaled_size.width() / original_size.width(),
                1.5,
                delta=0.02,
            )
            self.assertAlmostEqual(
                scaled_size.height() / original_size.height(),
                1.5,
                delta=0.02,
            )
        self.assertTrue(self.window.realtime_panel.isVisibleTo(self.window))
        self.assertTrue(self.window.key_panel.isHidden())
        self.assertTrue(self.window.player_panel.isVisibleTo(self.window))

    def test_player_layout_places_transport_below_the_full_width_seek_bar(self) -> None:
        self.window.show()
        self.application.processEvents()

        self.assertEqual(
            self.window.conversion_control_gap.height(),
            self.window.piano_roll_gap.height(),
        )
        self.assertEqual(self.window.conversion_control_gap.height(), 6)
        self.assertEqual(self.window.player_panel.objectName(), "SettingsPanel")
        self.assertEqual(self.window.player_layout.contentsMargins().left(), 8)
        self.assertFalse(hasattr(self.window, "status_label"))
        self.assertFalse(hasattr(self.window, "position_label"))
        self.assertLess(
            self.window.position_slider.mapTo(
                self.window,
                self.window.position_slider.rect().center(),
            ).y(),
            self.window.sound_play_pause_button.mapTo(
                self.window,
                self.window.sound_play_pause_button.rect().center(),
            ).y(),
        )
        self.assertEqual(self.window.player_body_gap.height(), 0)
        self.assertEqual(self.window.player_detail_gap.width(), 2)
        self.assertEqual(self.window.track_channels.width(), 22)
        self.assertFalse(self.window.volume_control.mute_button.icon().isNull())
        self.assertTrue(self.window.speed_control.label.isHidden())

    def test_section_visibility_hides_complete_panel(self) -> None:
        self.controller.set_option("input_conversion_mode", "realtime")
        self.window.resize(self.window.width(), 700)
        self.window.show()
        self.application.processEvents()
        initial_height = self.window.height()
        initial_player_top = self.window.player_panel.geometry().top()

        self.controller.set_section_visible("common_settings", False)
        self.application.processEvents()

        self.assertTrue(self.window.settings_panel.isHidden())
        self.assertTrue(self.window.piano_roll_panel.isVisibleTo(self.window))
        self.assertTrue(self.window.settings_lower_panel.isVisibleTo(self.window))
        self.assertTrue(self.window.realtime_panel.isVisibleTo(self.window))
        self.assertLess(self.window.player_panel.geometry().top(), initial_player_top)
        self.assertLess(self.window.height(), initial_height)

        self.controller.set_section_visible("common_settings", True)
        self.application.processEvents()
        self.assertEqual(self.window.height(), initial_height)

    def test_each_hidden_section_reduces_window_height(self) -> None:
        self.window.resize(self.window.width(), 700)
        self.window.show()
        self.application.processEvents()

        section_panels = {
            "input_conversion": self.window.conversion_control_panel,
            "common_settings": self.window.settings_panel,
            "piano_roll": self.window.piano_roll_panel,
            "keyboard": self.window.settings_lower_panel,
            "player": self.window.player_panel,
        }
        for section, panel in section_panels.items():
            with self.subTest(section=section):
                visible_height = self.window.height()
                self.controller.set_section_visible(section, False)
                self.application.processEvents()
                self.assertTrue(panel.isHidden())
                self.assertLess(self.window.height(), visible_height)

                self.controller.set_section_visible(section, True)
                self.application.processEvents()
                self.assertTrue(panel.isVisibleTo(self.window))
                self.assertEqual(self.window.height(), visible_height)

    def test_hidden_keyboard_stops_visual_work_and_resyncs_when_shown(self) -> None:
        self.window.show()
        self.application.processEvents()
        keyboard = self.window.output_keyboard
        keyboard.set_active_notes((60,))
        keyboard.set_retrigger_events(((60, 1),))
        self.assertTrue(keyboard._retrigger_timer.isActive())

        self.controller.set_section_visible("keyboard", False)
        self.application.processEvents()

        self.assertFalse(keyboard.rendering_enabled)
        self.assertFalse(keyboard._retrigger_timer.isActive())
        self.controller.state.active_output_notes = frozenset((64,))
        self.controller.state.output_note_retrigger_events = ((64, 2),)
        self.controller._notify()
        self.application.processEvents()
        self.assertEqual(keyboard.active_notes, frozenset((60,)))
        self.assertFalse(keyboard._retrigger_timer.isActive())

        self.controller.set_section_visible("keyboard", True)
        self.application.processEvents()

        self.assertTrue(keyboard.rendering_enabled)
        self.assertEqual(keyboard.active_notes, frozenset((64,)))
        self.assertFalse(keyboard._retrigger_timer.isActive())
        self.assertEqual(keyboard._last_retrigger_serials[64], 2)

        self.controller.state.output_note_retrigger_events = ((64, 3),)
        self.controller._notify()
        self.application.processEvents()
        self.assertTrue(keyboard._retrigger_timer.isActive())
        keyboard._retrigger_timer.stop()

    def test_hiding_player_section_compacts_to_current_minimum_height(self) -> None:
        self.window.resize(self.window.width(), 700)
        self.window.show()
        self.application.processEvents()

        self.controller.set_section_visible("player", False)
        self.application.processEvents()

        self.assertTrue(self.window.player_panel.isHidden())
        self.assertEqual(self.window.minimumSize().height(), self.window.minimumSizeHint().height())
        self.assertEqual(self.window.height(), self.window.minimumSizeHint().height())

    def test_speed_knob_double_click_resets_to_100(self) -> None:
        self.controller.set_option("playback_speed_percent", 170)
        QTest.mouseDClick(
            self.window.speed_control.knob,
            Qt.MouseButton.LeftButton,
        )

        self.assertEqual(self.controller.state.playback_speed_percent, 100)

    def test_volume_icon_toggles_mute_and_restores_previous_volume(self) -> None:
        self.controller.set_option("midi_sound_volume", 40)
        self.window.volume_control.mute_button.click()
        self.assertEqual(self.controller.state.midi_sound_volume, 0)
        self.assertEqual(
            self.window.volume_control.mute_button.toolTip(),
            "Unmute",
        )

        self.window.volume_control.mute_button.click()
        self.assertEqual(self.controller.state.midi_sound_volume, 40)
        self.assertEqual(
            self.window.volume_control.mute_button.toolTip(),
            "Mute",
        )

    def test_repeated_double_clicking_speed_knob_stays_at_100(self) -> None:
        self.controller.set_option("playback_speed_percent", 170)
        knob = self.window.speed_control.knob

        for _ in range(4):
            QTest.mouseDClick(
                knob,
                Qt.MouseButton.LeftButton,
                pos=QPoint(knob.width() // 2, 1),
            )
            self.application.processEvents()
            self.assertEqual(
                self.controller.state.playback_speed_percent,
                100,
            )
            self.assertEqual(knob.value(), 100)

    def test_double_clicking_midi_list_tab_reloads_folder(self) -> None:
        calls = []
        self.controller.reload_midi_folder = lambda: calls.append(True)
        self.window.show()
        self.application.processEvents()

        self.window.tab_bar.tabBarDoubleClicked.emit(0)
        self.application.processEvents()
        self.assertIs(
            self.window.tab_bar.property("reloadFeedback"),
            True,
        )
        palette = THEMES[self.controller.state.color_theme]
        self.assertIn(palette.accent, self.window.tab_bar.styleSheet())
        self.assertIn(palette.accent_text, self.window.tab_bar.styleSheet())
        self.window.tab_bar.tabBarDoubleClicked.emit(1)

        self.assertEqual(calls, [True])
        self.assertTrue(self.window._midi_reload_feedback_timer.isActive())
        QTest.qWait(300)
        self.assertIs(
            self.window.tab_bar.property("reloadFeedback"),
            False,
        )
        self.assertEqual(self.window.tab_bar.styleSheet(), "")

    def test_midi_list_tab_has_reload_icon_and_track_header_stays_hidden(self) -> None:
        self.window.show()
        self.application.processEvents()

        self.assertFalse(self.window.tab_bar.tabIcon(0).isNull())
        tab_top = self.window.tab_bar.mapTo(self.window, QPoint(0, 0)).y()
        track_top = self.window.track_channels.mapTo(
            self.window,
            QPoint(0, 0),
        ).y()
        tab_left = self.window.tab_bar_container.mapTo(
            self.window,
            QPoint(0, 0),
        ).x()
        table_left = self.window.midi_table.mapTo(
            self.window,
            QPoint(0, 0),
        ).x()
        self.assertEqual(
            track_top - tab_top,
            self.window.tab_bar.height(),
        )
        self.assertEqual(tab_left, table_left)
        self.assertTrue(
            self.window.track_channels.horizontalHeader().isHidden()
        )

    def test_three_knobs_share_the_transport_row_and_volume_follows_playlist(self) -> None:
        for scale in (100, 125, 150, 175, 200):
            with self.subTest(scale=scale):
                self.controller.set_option("ui_scale_percent", scale)
                self.window.show()
                self.application.processEvents()

                controls = (
                    self.window.speed_control,
                    self.window.transpose_control,
                    self.window.octave_control,
                )
                control_center_y = controls[0].mapTo(
                    self.window,
                    controls[0].rect().center(),
                ).y()
                for control in controls:
                    self.assertTrue(control.label.isHidden())
                    self.assertEqual(
                        control.mapTo(
                            self.window,
                            control.rect().center(),
                        ).y(),
                        control_center_y,
                    )
                control_gaps = [
                    controls[index].mapTo(
                        self.window,
                        QPoint(0, 0),
                    ).x()
                    - controls[index - 1].mapTo(
                        self.window,
                        QPoint(controls[index - 1].width(), 0),
                    ).x()
                    for index in range(1, len(controls))
                ]
                self.assertEqual(
                    control_gaps,
                    [0] * (len(controls) - 1),
                )
                self.assertEqual(
                    self.window.octave_control.geometry().left()
                    - self.window.transpose_control.geometry().right()
                    - 1,
                    0,
                )
                self.assertGreaterEqual(
                    self.window.previous_track_button.mapTo(
                        self.window,
                        QPoint(0, 0),
                    ).x()
                    - self.window.slider_pane.mapTo(
                        self.window,
                        QPoint(self.window.slider_pane.width(), 0),
                    ).x(),
                    max(1, round(scale / 100)),
                )
                control_centers = [
                    control.knob.mapTo(
                        self.window,
                        control.knob.rect().center(),
                    ).x()
                    for control in controls
                ]
                self.assertEqual(control_centers, sorted(control_centers))
                play_button_left = self.window.sound_play_pause_button.mapTo(
                    self.window,
                    QPoint(0, 0),
                ).x()
                self.assertLess(
                    self.window.octave_control.mapTo(
                        self.window,
                        QPoint(self.window.octave_control.width(), 0),
                    ).x(),
                    play_button_left,
                )
                seek_center_y = self.window.position_slider.mapTo(
                    self.window,
                    self.window.position_slider.rect().center(),
                ).y()
                midi_table_top = self.window.midi_table.mapTo(
                    self.window,
                    QPoint(0, 0),
                ).y()
                expected_control_center_y = (
                    seek_center_y + midi_table_top
                ) / 2
                for control in controls:
                    self.assertAlmostEqual(
                        control.mapTo(
                            self.window,
                            control.rect().center(),
                        ).y(),
                        expected_control_center_y,
                        delta=max(1, round(scale / 100)),
                    )
                repeat_left = self.window.sound_playback_mode_button.mapTo(
                    self.window,
                    QPoint(0, 0),
                ).x()
                octave_right = self.window.octave_control.mapTo(
                    self.window,
                    QPoint(self.window.octave_control.width(), 0),
                ).x()
                self.assertAlmostEqual(
                    repeat_left - octave_right,
                    round(8 * scale / 100),
                    delta=1,
                )
                playlist_right = self.window.playlist_button.mapTo(
                    self.window,
                    QPoint(self.window.playlist_button.width(), 0),
                ).x()
                volume_left = self.window.volume_control.mapTo(
                    self.window,
                    QPoint(0, 0),
                ).x()
                self.assertGreaterEqual(
                    volume_left - playlist_right,
                    round(12 * scale / 100),
                )
                self.assertEqual(
                    self.window.volume_control.slider.orientation(),
                    Qt.Orientation.Horizontal,
                )
                self.assertLessEqual(
                    self.window.transform_controls.mapTo(
                        self.window,
                        QPoint(self.window.transform_controls.width(), 0),
                    ).x(),
                    self.window.sound_source_controls.mapTo(
                        self.window,
                        QPoint(0, 0),
                    ).x(),
                )

    def test_transport_icons_stay_after_knobs_on_the_lower_row_at_every_scale(self) -> None:
        for scale in (100, 110, 125, 150, 175, 200):
            with self.subTest(scale=scale):
                self.controller.set_option("ui_scale_percent", scale)
                self.window.show()
                self.application.processEvents()

                transport_buttons = (
                    self.window.sound_playback_mode_button,
                    self.window.previous_track_button,
                    self.window.sound_play_pause_button,
                    self.window.next_track_button,
                    self.window.playlist_button,
                )
                button_centers = [
                    button.mapTo(
                        self.window,
                        button.rect().center(),
                    ).x()
                    for button in transport_buttons
                ]
                self.assertEqual(button_centers, sorted(button_centers))
                volume_center_y = self.window.volume_control.mapTo(
                    self.window,
                    self.window.volume_control.rect().center(),
                ).y()
                transport_center = self.window.transport_right.mapTo(
                    self.window,
                    self.window.transport_right.rect().center(),
                ).x()
                self.assertAlmostEqual(
                    transport_center,
                    self.window.rect().center().x(),
                    delta=1,
                )
                seek_center_y = self.window.position_slider.mapTo(
                    self.window,
                    self.window.position_slider.rect().center(),
                ).y()
                midi_frame_top = self.window.midi_table.mapTo(
                    self.window,
                    QPoint(0, 0),
                ).y()
                expected_button_center_y = (
                    seek_center_y + midi_frame_top
                ) / 2
                for button in transport_buttons:
                    self.assertAlmostEqual(
                        button.mapTo(
                            self.window,
                            button.rect().center(),
                        ).y(),
                        expected_button_center_y,
                        delta=max(1, round(scale / 100)),
                    )
                self.assertAlmostEqual(
                    volume_center_y,
                    expected_button_center_y,
                    delta=max(1, round(scale / 100)),
                )
                marquee_top = self.window.current_track_marquee.mapTo(
                    self.window,
                    QPoint(0, 0),
                ).y()
                seek_top = self.window.position_slider.mapTo(
                    self.window,
                    QPoint(0, 0),
                ).y()
                seek_bottom = self.window.position_slider.mapTo(
                    self.window,
                    QPoint(0, self.window.position_slider.height()),
                ).y()
                marquee_bottom = (
                    marquee_top
                    + self.window.current_track_marquee.height()
                )
                player_header_top = self.window.player_header.mapTo(
                    self.window,
                    QPoint(0, 0),
                ).y()
                self.assertEqual(
                    marquee_top,
                    player_header_top - round(11 * scale / 100),
                )
                self.assertLessEqual(marquee_top, seek_top)
                self.assertGreater(marquee_bottom, seek_top)
                self.assertLessEqual(marquee_bottom, seek_bottom)
                self.assertAlmostEqual(
                    self.window.current_track_marquee.height(),
                    round(18 * scale / 100),
                    delta=1,
                )
                self.assertEqual(
                    self.window.current_track_marquee.font().pixelSize(),
                    round(10 * scale / 100),
                )
                self.assertTrue(
                    self.window.current_track_marquee.testAttribute(
                        Qt.WidgetAttribute.WA_TransparentForMouseEvents
                    )
                )
                marquee_right = self.window.current_track_marquee.mapTo(
                    self.window,
                    QPoint(self.window.current_track_marquee.width(), 0),
                ).x()
                player_header_right = self.window.player_header.mapTo(
                    self.window,
                    QPoint(self.window.player_header.width(), 0),
                ).x()
                self.assertEqual(marquee_right, player_header_right)
                player_header_left = self.window.player_header.mapTo(
                    self.window,
                    QPoint(0, 0),
                ).x()
                marquee_left = self.window.current_track_marquee.mapTo(
                    self.window,
                    QPoint(0, 0),
                ).x()
                self.assertEqual(marquee_left, player_header_left)
                speed_left = self.window.speed_control.mapTo(
                    self.window,
                    QPoint(0, 0),
                ).x()
                panel_left = self.window.transport_controls_panel.mapTo(
                    self.window,
                    QPoint(0, 0),
                ).x()
                panel_right = self.window.transport_controls_panel.mapTo(
                    self.window,
                    QPoint(
                        self.window.transport_controls_panel.width(),
                        0,
                    ),
                ).x()
                volume_right = self.window.volume_control.mapTo(
                    self.window,
                    QPoint(self.window.volume_control.width(), 0),
                ).x()
                self.assertLessEqual(panel_left, speed_left)
                self.assertGreaterEqual(panel_right, volume_right)
                self.assertEqual(
                    self.window.transport_controls_panel.height(),
                    round(40 * scale / 100),
                )
                panel_top = self.window.transport_controls_panel.mapTo(
                    self.window,
                    QPoint(0, 0),
                ).y()
                panel_bottom = panel_top + self.window.transport_controls_panel.height()
                controls = (
                    self.window.speed_control,
                    self.window.transpose_control,
                    self.window.octave_control,
                    self.window.sound_playback_mode_button,
                    self.window.previous_track_button,
                    self.window.sound_play_pause_button,
                    self.window.next_track_button,
                    self.window.playlist_button,
                    self.window.volume_title_stack,
                )
                controls_top = min(
                    control.mapTo(self.window, QPoint(0, 0)).y()
                    for control in controls
                )
                controls_bottom = max(
                    control.mapTo(
                        self.window,
                        QPoint(0, control.height()),
                    ).y()
                    for control in controls
                )
                self.assertLess(panel_top, controls_top)
                self.assertGreater(panel_bottom, controls_bottom)
                self.assertLessEqual(
                    abs(
                        (controls_top - panel_top)
                        - (panel_bottom - controls_bottom)
                    ),
                    1,
                )
                self.assertLess(
                    self.window.transform_controls.mapTo(
                        self.window,
                        QPoint(self.window.transform_controls.width(), 0),
                    ).x(),
                    self.window.previous_track_button.mapTo(
                        self.window,
                        QPoint(0, 0),
                    ).x(),
                )

    def test_localized_knob_tooltips_fit_without_growing_player_header(self) -> None:
        expected = {
            "en": ("Speed", "Transpose", "Octave shift"),
            "ja": (
                "\u901f\u5ea6",
                "\u30c8\u30e9\u30f3\u30b9\u30dd\u30fc\u30ba",
                "\u30aa\u30af\u30bf\u30fc\u30d6\u30b7\u30d5\u30c8",
            ),
            "zh": ("\u901f\u5ea6", "\u79fb\u8c03", "\u516b\u5ea6\u79fb\u4f4d"),
        }
        expected_mute = {
            "en": "Mute",
            "ja": "\u30df\u30e5\u30fc\u30c8",
            "zh": "\u9759\u97f3",
        }
        for language in ("en", "ja", "zh"):
            for scale in (100, 150, 200):
                with self.subTest(language=language, scale=scale):
                    self.controller.set_option("language", language)
                    self.controller.set_option("ui_scale_percent", scale)
                    self.window.show()
                    self.application.processEvents()
                    controls = (
                        self.window.speed_control,
                        self.window.transpose_control,
                        self.window.octave_control,
                    )

                    self.assertEqual(
                        tuple(control.knob.toolTip() for control in controls),
                        expected[language],
                    )
                    self.assertEqual(
                        self.window.volume_control.mute_button.toolTip(),
                        expected_mute[language],
                    )
                    volume_right = self.window.volume_control.mapTo(
                        self.window,
                        QPoint(self.window.volume_control.width(), 0),
                    ).x()
                    sound_source_left = self.window.sound_source_controls.mapTo(
                        self.window,
                        QPoint(0, 0),
                    ).x()
                    self.assertGreaterEqual(
                        sound_source_left - volume_right,
                        round(8 * scale / 100),
                    )
                    self.assertEqual(
                        self.window.player_header.height(),
                        round(70 * scale / 100),
                    )
                    self.assertEqual(
                        self.window.time_label.width(),
                        round(72 * scale / 100),
                    )
                    self.assertGreaterEqual(
                        self.window.time_label.width(),
                        self.window.time_label.fontMetrics().horizontalAdvance(
                            self.window.time_label.text()
                        ),
                    )
                    for control in controls:
                        self.assertTrue(control.label.isHidden())
                        self.assertGreaterEqual(
                            control.knob.geometry().left(),
                            0,
                        )
                        self.assertLessEqual(
                            control.knob.geometry().right(),
                            control.width() - 1,
                        )

    def test_current_track_name_remains_static_during_playback(self) -> None:
        self.controller.state.midi_rows = [
            MidiListRow(
                Path("current-song.mix.midi"),
                "current-song.mix.midi",
            )
        ]
        self.window.show()
        self.controller.state.selected_midi_index = 0
        self.controller.state.current_mode = "sound"
        self.window.render(self.controller.state)
        self.application.processEvents()

        expected_name = "current-song.mix"
        self.assertEqual(self.window.current_track_marquee.text, expected_name)
        self.assertNotIn(".midi", self.window.current_track_marquee.text)
        self.assertFalse(
            self.window.current_track_marquee.scrolling_enabled
        )
        initial_offset = self.window.current_track_marquee.scroll_offset
        self.assertEqual(initial_offset, 0.0)
        self.window.current_track_marquee._advance()
        self.assertEqual(
            self.window.current_track_marquee.scroll_offset,
            initial_offset,
        )
        self.assertFalse(self.window.current_track_marquee._timer.isActive())

        self.controller.state.current_mode = None
        self.window.render(self.controller.state)
        self.assertEqual(self.window.current_track_marquee.text, "")

    def test_transpose_and_octave_knobs_reset_values_on_double_click(self) -> None:
        self.controller.set_option("transpose_semitones", 5)
        self.controller.set_option("octave_shift", -2)
        self.window.show()
        self.application.processEvents()

        for _ in range(4):
            QTest.mouseDClick(
                self.window.transpose_control.knob,
                Qt.MouseButton.LeftButton,
            )
            QTest.mouseDClick(
                self.window.octave_control.knob,
                Qt.MouseButton.LeftButton,
            )
            self.application.processEvents()
            self.assertEqual(self.controller.state.transpose_semitones, 0)
            self.assertEqual(self.controller.state.octave_shift, 0)
            self.assertEqual(self.window.transpose_control.knob.value(), 0)
            self.assertEqual(self.window.octave_control.knob.value(), 0)

    def test_transform_knobs_scale_as_circles_with_the_ui(self) -> None:
        self.controller.set_option("ui_scale_percent", 100)
        self.window.show()
        self.application.processEvents()
        transpose_width = self.window.transpose_control.width()
        octave_width = self.window.octave_control.width()

        self.controller.set_option("ui_scale_percent", 200)
        self.application.processEvents()

        self.assertEqual(self.window.transpose_control.knob.size(), QSize(66, 66))
        self.assertEqual(self.window.octave_control.knob.size(), QSize(66, 66))
        self.assertGreater(
            self.window.transpose_control.width(),
            transpose_width * 1.75,
        )
        self.assertGreater(
            self.window.octave_control.width(),
            octave_width * 1.60,
        )
        for control in (
            self.window.transpose_control,
            self.window.octave_control,
        ):
            self.assertGreaterEqual(
                control.width(),
                max(
                    control.label.fontMetrics().horizontalAdvance(
                        control.label.text()
                    ),
                    control.knob.width(),
                ),
            )

    def test_midi_header_and_rows_have_more_vertical_room(self) -> None:
        self.window.show()
        self.application.processEvents()

        self.assertEqual(self.window.midi_table.horizontalHeader().height(), 24)
        self.assertEqual(self.window.player_body_gap.height(), 0)

    def test_midi_list_renders_folder_and_duration_columns(self) -> None:
        path = Path("Library") / "Album" / "song.mid"
        self.controller.midi_files = [path]
        self.controller.state.midi_rows = [
            MidiListRow(
                path=path,
                name="song.mid",
                folder="Library > Album",
                duration="01:23",
            )
        ]
        self.controller._notify()
        self.application.processEvents()

        self.assertEqual(self.window.midi_table.columnCount(), 3)
        self.assertEqual(
            [
                self.window.midi_table.horizontalHeaderItem(column).text()
                for column in range(3)
            ],
            ["Name", "Folder", "Duration"],
        )
        self.assertEqual(
            [
                self.window.midi_table.item(0, column).text()
                for column in range(3)
            ],
            ["song", "Library > Album", "01:23"],
        )
        self.assertEqual(
            self.window.midi_table.item(0, 1).toolTip(),
            "Library > Album",
        )

    def test_midi_list_updates_only_the_changed_row(self) -> None:
        first = MidiListRow(Path("first.mid"), "first.mid", duration="00:10")
        second = MidiListRow(Path("second.mid"), "second.mid", duration="00:20")
        self.controller.state.midi_rows = [first, second]
        self.controller._notify()
        first_item = self.window.midi_table.item(0, 0)
        updated_second = MidiListRow(
            Path("second.mid"),
            "second.mid",
            duration="00:21",
        )

        with patch.object(
            self.window,
            "_update_midi_table_row",
            wraps=self.window._update_midi_table_row,
        ) as update_row:
            self.controller.state.midi_rows = [first, updated_second]
            self.controller._notify()

        update_row.assert_called_once_with(1, updated_second)
        self.assertIs(self.window.midi_table.item(0, 0), first_item)
        self.assertEqual(self.window.midi_table.item(1, 2).text(), "00:21")

    def test_midi_list_inserts_and_removes_rows_without_rebuilding_others(self) -> None:
        second = MidiListRow(Path("second.mid"), "second.mid", duration="00:20")
        third = MidiListRow(Path("third.mid"), "third.mid", duration="00:30")
        self.controller.state.midi_rows = [second, third]
        self.controller._notify()
        second_item = self.window.midi_table.item(0, 0)
        third_item = self.window.midi_table.item(1, 0)
        first = MidiListRow(Path("first.mid"), "first.mid", duration="00:10")

        self.controller.state.midi_rows = [first, second, third]
        self.controller._notify()

        self.assertIs(self.window.midi_table.item(1, 0), second_item)
        self.assertIs(self.window.midi_table.item(2, 0), third_item)

        self.controller.state.midi_rows = [first, third]
        self.controller._notify()

        self.assertIs(self.window.midi_table.item(1, 0), third_item)

    def test_midi_header_separators_align_with_column_edges(self) -> None:
        self.window.resize(1400, self.window.height())
        self.window.show()
        self.application.processEvents()
        header = self.window.midi_header
        self.assertEqual(header.frameShape(), QFrame.Shape.NoFrame)

        for theme_name, palette in THEMES.items():
            with self.subTest(theme=theme_name):
                self.controller.set_option("color_theme", theme_name)
                self.application.processEvents()
                image = self.window.midi_table.grab().toImage()
                header_origin = header.viewport().mapTo(
                    self.window.midi_table,
                    QPoint(0, 0),
                )
                body_origin = self.window.midi_table.viewport().mapTo(
                    self.window.midi_table,
                    QPoint(0, 0),
                )
                y = header_origin.y() + max(0, header.viewport().height() // 2)
                for visual_index in range(header.count() - 1):
                    logical_index = header.logicalIndex(visual_index)
                    x = (
                        body_origin.x()
                        + header.sectionViewportPosition(logical_index)
                        + header.sectionSize(logical_index)
                        - 1
                    )
                    self.assertEqual(
                        image.pixelColor(x, y),
                        QColor(palette.border),
                    )
                last_logical_index = header.logicalIndex(header.count() - 1)
                sections_end = (
                    body_origin.x()
                    + header.sectionViewportPosition(last_logical_index)
                    + header.sectionSize(last_logical_index)
                )
                self.assertLessEqual(
                    abs(
                        sections_end
                        - (body_origin.x() + header.viewport().width())
                    ),
                    1,
                )

    def test_midi_name_width_is_saved_and_duration_width_is_fixed(self) -> None:
        self.window.show()
        self.application.processEvents()
        header = self.window.midi_table.horizontalHeader()

        self.assertEqual(
            header.sectionResizeMode(0),
            QHeaderView.ResizeMode.Interactive,
        )
        self.assertEqual(
            header.sectionResizeMode(1),
            QHeaderView.ResizeMode.Stretch,
        )
        self.assertEqual(
            header.sectionResizeMode(2),
            QHeaderView.ResizeMode.Fixed,
        )
        self.assertEqual(
            header.sectionViewportPosition(2) + header.sectionSize(2),
            header.viewport().width(),
        )

        duration_left = header.sectionViewportPosition(2)
        duration_width = header.sectionSize(2)
        self.assertLess(duration_width, 80)
        self.assertGreaterEqual(duration_width, 64)
        self.assertGreater(
            duration_width,
            header.fontMetrics().horizontalAdvance(
                self.window.midi_table.horizontalHeaderItem(2).text()
            ),
        )
        self.assertEqual(
            self.window.midi_table.fontMetrics().elidedText(
                "00:00",
                Qt.TextElideMode.ElideRight,
                duration_width - 20,
            ),
            "00:00",
        )
        folder_left = header.sectionViewportPosition(1)
        header.resizeSection(0, 560)
        self.application.processEvents()
        self.assertEqual(
            self.controller.state.midi_column_widths,
            (560, 180, 80),
        )
        self.assertEqual(
            self.controller.current_settings().midi_column_widths,
            (560, 180, 80),
        )
        self.assertNotEqual(header.sectionViewportPosition(1), folder_left)
        self.assertEqual(header.sectionViewportPosition(2), duration_left)
        duration_right = (
            header.sectionViewportPosition(2) + duration_width
        )
        duration_boundary = header.sectionViewportPosition(2)
        header_y = header.height() // 2
        QTest.mouseMove(
            header.viewport(),
            QPoint(duration_boundary, header_y),
        )
        QTest.mousePress(
            header.viewport(),
            Qt.MouseButton.LeftButton,
            pos=QPoint(duration_boundary, header_y),
        )
        QTest.mouseMove(
            header.viewport(),
            QPoint(duration_boundary - 20, header_y),
        )
        QTest.mouseRelease(
            header.viewport(),
            Qt.MouseButton.LeftButton,
            pos=QPoint(duration_boundary - 20, header_y),
        )
        self.application.processEvents()
        self.assertEqual(header.sectionSize(2), duration_width)
        self.assertEqual(
            header.sectionViewportPosition(2) + header.sectionSize(2),
            duration_right,
        )
        self.assertEqual(
            self.controller.state.midi_column_widths,
            (560, 180, 80),
        )

        self.controller.set_option("ui_scale_percent", 200)
        self.application.processEvents()
        self.assertEqual(
            self.window.midi_table.columnWidth(0),
            1120,
        )
        self.assertGreater(
            self.window.midi_table.columnWidth(2),
            duration_width,
        )
        self.assertEqual(
            header.sectionViewportPosition(2) + header.sectionSize(2),
            header.viewport().width(),
        )

    def test_clicking_playback_position_seeks_to_clicked_value(self) -> None:
        self.controller.state.duration = 120.0
        self.controller._notify()
        self.window.show()
        self.application.processEvents()

        slider = self.window.position_slider
        QTest.mouseClick(
            slider,
            Qt.MouseButton.LeftButton,
            pos=QPoint(slider.width() * 3 // 4, slider.height() // 2),
        )

        self.assertAlmostEqual(self.controller.state.position, 90.0, delta=1.0)

    def test_dragging_playback_position_defers_seek_until_release(self) -> None:
        self.controller.state.duration = 120.0
        self.controller.state.position = 12.0
        self.controller._notify()
        self.window.show()
        self.application.processEvents()
        slider = self.window.position_slider
        drag_position = QPoint(slider.width() * 3 // 4, slider.height() // 2)

        with patch.object(self.controller, "seek", wraps=self.controller.seek) as seek:
            QTest.mousePress(
                slider,
                Qt.MouseButton.LeftButton,
                pos=QPoint(slider.width() // 4, slider.height() // 2),
            )
            QTest.mouseMove(slider, drag_position)

            self.assertTrue(slider.is_user_drag_active())
            self.assertEqual(seek.call_count, 0)
            self.assertEqual(self.controller.state.position, 12.0)

            dragged_value = slider.value()
            option = QStyleOptionSlider()
            slider.initStyleOption(option)
            handle = slider.style().subControlRect(
                QStyle.ComplexControl.CC_Slider,
                option,
                QStyle.SubControl.SC_SliderHandle,
                slider,
            )
            self.assertAlmostEqual(
                handle.center().x(),
                drag_position.x(),
                delta=1,
            )
            self.controller.state.position = 24.0
            self.controller._notify()
            self.application.processEvents()
            self.assertEqual(slider.value(), dragged_value)

            QTest.mouseRelease(
                slider,
                Qt.MouseButton.LeftButton,
                pos=drag_position,
            )

        self.assertFalse(slider.is_user_drag_active())
        self.assertEqual(seek.call_count, 1)
        self.assertAlmostEqual(self.controller.state.position, 90.0, delta=1.0)

    def test_playback_position_uses_compact_time_label(self) -> None:
        self.window.show()
        self.application.processEvents()

        self.assertEqual(self.window.time_label.width(), 80)
        self.assertEqual(self.window.position_row_layout.spacing(), 1)
        self.assertEqual(
            self.window.position_slider.width(),
            self.window.player_header.width()
            - self.window.time_label.width()
            - self.window.position_row_layout.spacing(),
        )
        self.assertGreater(self.window.position_slider.width(), 760)
        self.assertLessEqual(
            self.window.time_label.fontMetrics().horizontalAdvance("00:00 / 00:00"),
            self.window.time_label.width(),
        )

    def test_player_transport_buttons_use_icons_and_cycle_playback_mode(self) -> None:
        self.controller.midi_files = [
            Path("first.mid"),
            Path("second.mid"),
            Path("third.mid"),
        ]
        self.controller.state.midi_rows = [
            MidiListRow(path, path.name)
            for path in self.controller.midi_files
        ]
        self.controller.state.selected_midi_index = 1
        self.controller._notify()
        self.window.show()
        self.application.processEvents()

        for button in (
            self.window.sound_playback_mode_button,
            self.window.previous_track_button,
            self.window.sound_play_pause_button,
            self.window.next_track_button,
            self.window.playlist_button,
        ):
            with self.subTest(button=button.accessibleName()):
                self.assertEqual(button.text(), "")
                self.assertFalse(button.icon().isNull())

        with patch.object(self.controller, "select_midi") as select_midi:
            self.window.previous_track_button.click()
            select_midi.assert_called_once_with(0)
            select_midi.reset_mock()
            self.window.next_track_button.click()
            select_midi.assert_called_once_with(2)

        self.assertEqual(
            self.controller.state.sound_playback_mode,
            SOUND_PLAYBACK_MODE_OFF,
        )
        self.window.sound_playback_mode_button.click()
        self.assertEqual(
            self.controller.state.sound_playback_mode,
            SOUND_PLAYBACK_MODE_CONTINUOUS,
        )
        self.window.sound_playback_mode_button.click()
        self.assertEqual(
            self.controller.state.sound_playback_mode,
            SOUND_PLAYBACK_MODE_REPEAT_ONE,
        )
        self.window.sound_playback_mode_button.click()
        self.assertEqual(
            self.controller.state.sound_playback_mode,
            SOUND_PLAYBACK_MODE_OFF,
        )
        self.assertFalse(
            self.window.playlist_button.testAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents
            )
        )

    def test_play_button_changes_to_pause_while_sound_is_playing(self) -> None:
        self.controller.state.midi_rows = [
            MidiListRow(Path("song.mid"), "song.mid")
        ]
        self.controller.state.selected_midi_index = 0
        self.controller.state.current_mode = None
        self.controller._notify()
        play_icon = self.window.sound_play_pause_button.icon().pixmap(20, 20).toImage()
        self.assertEqual(self.window.sound_play_pause_button.toolTip(), "Play")

        self.controller.state.current_mode = "sound"
        self.controller._notify()
        pause_icon = self.window.sound_play_pause_button.icon().pixmap(20, 20).toImage()

        self.assertEqual(self.window.sound_play_pause_button.toolTip(), "Pause")
        self.assertNotEqual(
            play_icon.bits().tobytes(),
            pause_icon.bits().tobytes(),
        )

    def test_player_transport_hover_background_stays_round_on_first_render(
        self,
    ) -> None:
        self.controller.state.midi_rows = [
            MidiListRow(Path("first.mid"), "first.mid"),
            MidiListRow(Path("second.mid"), "second.mid"),
            MidiListRow(Path("third.mid"), "third.mid"),
        ]
        self.controller.state.selected_midi_index = 1
        self.controller._notify()
        self.window.show()
        buttons = (
            self.window.previous_track_button,
            self.window.sound_play_pause_button,
            self.window.next_track_button,
            self.window.sound_playback_mode_button,
        )
        for theme_name in THEMES:
            self.controller.set_option("color_theme", theme_name)
            self.application.processEvents()
            for button in buttons:
                with self.subTest(
                    theme=theme_name,
                    button=button.accessibleName(),
                ):
                    self.assertTrue(button.isEnabled())
                    QApplication.sendEvent(button, QEvent(QEvent.Type.Enter))
                    self.application.processEvents()
                    image = button.grab().toImage()

                    self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
                    self.assertGreater(
                        image.pixelColor(
                            button.width() // 2,
                            button.height() // 2,
                        ).alpha(),
                        0,
                    )
                    QApplication.sendEvent(button, QEvent(QEvent.Type.Leave))

    def test_player_transport_buttons_keep_initial_size_without_hover_scaling(
        self,
    ) -> None:
        self.window.show()
        self.application.processEvents()
        buttons = (
            self.window.previous_track_button,
            self.window.sound_play_pause_button,
            self.window.next_track_button,
            self.window.sound_playback_mode_button,
        )

        for button in buttons:
            with self.subTest(button=button.accessibleName()):
                self.assertEqual(button.width(), 36)
                self.assertGreaterEqual(button.height(), 35)
                self.assertEqual(button.iconSize(), QSize(34, 34))
                initial_size = button.size()
                icon_size = button.iconSize()
                QApplication.sendEvent(button, QEvent(QEvent.Type.Enter))
                self.application.processEvents()
                self.assertEqual(button.size(), initial_size)
                self.assertEqual(button.iconSize(), icon_size)
                QApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
                self.assertEqual(button.size(), initial_size)
                self.assertEqual(button.iconSize(), icon_size)

    def test_volume_bar_selects_value_and_speed_knob_drag_changes_value(self) -> None:
        self.window.show()
        self.application.processEvents()
        volume_bar = self.window.volume_control.slider
        speed_knob = self.window.speed_control.knob
        speed_start = speed_knob.rect().center()
        self.assertEqual(volume_bar.width(), 100)

        QTest.mouseClick(
            volume_bar,
            Qt.MouseButton.LeftButton,
            pos=QPoint(
                round(volume_bar.width() * 0.95),
                volume_bar.height() // 2,
            ),
        )
        QTest.mousePress(speed_knob, Qt.MouseButton.LeftButton, pos=speed_start)
        QTest.mouseMove(
            speed_knob,
            QPoint(speed_start.x(), speed_start.y() + 20),
        )
        QTest.mouseRelease(
            speed_knob,
            Qt.MouseButton.LeftButton,
            pos=QPoint(speed_start.x(), speed_start.y() + 20),
        )

        self.assertGreater(self.controller.state.midi_sound_volume, 90)
        self.assertLess(self.controller.state.playback_speed_percent, 100)

    def test_volume_bar_click_centers_handle_without_jumping_when_grabbed(self) -> None:
        self.controller.set_option("midi_sound_volume", 80)
        self.window.show()
        self.application.processEvents()
        volume_bar = self.window.volume_control.slider
        option = QStyleOptionSlider()
        volume_bar.initStyleOption(option)
        handle = volume_bar.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderHandle,
            volume_bar,
        )
        grab_position = QPoint(handle.left() + 1, handle.center().y())

        QTest.mousePress(
            volume_bar,
            Qt.MouseButton.LeftButton,
            pos=grab_position,
        )
        QTest.mouseRelease(
            volume_bar,
            Qt.MouseButton.LeftButton,
            pos=grab_position,
        )

        self.assertEqual(self.controller.state.midi_sound_volume, 80)

        target_x = volume_bar.width() // 4
        QTest.mouseClick(
            volume_bar,
            Qt.MouseButton.LeftButton,
            pos=QPoint(target_x, volume_bar.height() // 2),
        )
        option = QStyleOptionSlider()
        volume_bar.initStyleOption(option)
        handle = volume_bar.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderHandle,
            volume_bar,
        )

        self.assertAlmostEqual(handle.center().x(), target_x, delta=1)

    def test_volume_bar_track_remains_visible_at_zero(self) -> None:
        self.controller.set_option("midi_sound_volume", 0)
        self.window.show()
        self.application.processEvents()

        self.assertEqual(
            self.window.volume_control.slider.objectName(),
            "VolumeSlider",
        )
        self.assertEqual(self.window.volume_control.slider.value(), 0)
        for theme_name, palette in THEMES.items():
            with self.subTest(theme=theme_name):
                volume_rule = build_stylesheet(
                    theme_name,
                    100,
                ).split(
                    "QSlider#VolumeSlider::groove:horizontal {",
                    1,
                )[1].split("}", 1)[0]
                self.assertIn(
                    f"background: {palette.surface_hover}",
                    volume_rule,
                )
                self.assertIn(
                    f"border: 1px solid {palette.border}",
                    volume_rule,
                )

    def test_clicking_speed_knob_without_drag_does_not_change_value(self) -> None:
        self.window.show()
        self.application.processEvents()
        knob = self.window.speed_control.knob

        QTest.mouseClick(
            knob,
            Qt.MouseButton.LeftButton,
            pos=QPoint(knob.width() // 2, 1),
        )

        self.assertEqual(self.controller.state.playback_speed_percent, 100)

    def test_track_channel_colors_reflect_enabled_state_on_first_render(self) -> None:
        self.controller.state.track_channels = [
            TrackChannelItem(0, 0, True),
            TrackChannelItem(0, 1, False),
        ]
        self.controller._notify()
        self.window.show()
        self.application.processEvents()
        enabled = self.window.track_channels.cellWidget(0, 0)
        disabled = self.window.track_channels.cellWidget(1, 0)

        self.assertIsInstance(enabled, TrackChannelButton)
        self.assertIsInstance(disabled, TrackChannelButton)
        self.assertTrue(enabled.isChecked())
        self.assertFalse(disabled.isChecked())
        QTest.mouseMove(
            self.window,
            QPoint(self.window.width() - 1, self.window.height() - 1),
        )
        self.application.processEvents()
        enabled_image = enabled.grab().toImage()
        disabled_image = disabled.grab().toImage()
        enabled_sample = enabled_image.pixelColor(enabled.width() // 2, enabled.height() // 4)
        disabled_sample = disabled_image.pixelColor(disabled.width() // 2, disabled.height() // 4)

        enabled_source_color = QColor(track_channel_color(0, 0))
        self.assertEqual(
            enabled._source_background.name(),
            enabled_source_color.name(),
        )
        self.assertIn(
            enabled_sample.name(),
            {
                enabled_source_color.name(),
                enabled_source_color.lighter(106).name(),
            },
        )
        self.assertNotEqual(disabled_sample.name(), enabled_sample.name())
        self.assertEqual(
            disabled._source_background.name(),
            track_channel_color(0, 1).lower(),
        )

    def test_track_channel_buttons_use_the_same_font_weight(self) -> None:
        self.controller.state.track_channels = [
            TrackChannelItem(0, 0, True),
            TrackChannelItem(1, 1, True),
        ]
        self.controller._notify()
        self.application.processEvents()
        accompaniment = self.window.track_channels.cellWidget(0, 0)
        second_source = self.window.track_channels.cellWidget(1, 0)

        self.assertIsInstance(accompaniment, TrackChannelButton)
        self.assertIsInstance(second_source, TrackChannelButton)
        self.assertFalse(accompaniment.font().bold())
        self.assertFalse(second_source.font().bold())

    def test_view_section_actions_are_direct_menu_items(self) -> None:
        view_action = next(
            action for action in self.window.menuBar().actions() if action.text() == "View"
        )
        view_menu = view_action.menu()
        direct_actions = {action.text(): action for action in view_menu.actions()}

        expected_labels = (
            "Basic Screen",
            "Advanced Settings",
            "Rhythm Game",
            "Keyboard",
            "Player",
        )
        for label in expected_labels:
            self.assertIn(label, direct_actions)
            self.assertIsNone(direct_actions[label].menu())
        actions = view_menu.actions()
        last_separator = max(
            index
            for index, action in enumerate(actions)
            if action.isSeparator()
        )
        self.assertEqual(
            tuple(action.text() for action in actions[last_separator + 1 :]),
            expected_labels,
        )

    def test_file_menu_starts_with_midi_folder_then_settings_save(self) -> None:
        file_action = next(
            action
            for action in self.window.menuBar().actions()
            if action.text() == "File"
        )
        commands = [
            action
            for action in file_action.menu().actions()
            if not action.isSeparator()
        ]
        self.assertEqual(
            [action.text() for action in commands],
            ["Select MIDI Folder", "Save Settings", "Exit"],
        )

        self.save_settings_mock.reset_mock()
        commands[1].trigger()

        self.save_settings_mock.assert_called_once()

    def test_other_menu_starts_with_update_check_then_release_notes(self) -> None:
        other_action = next(
            action
            for action in self.window.menuBar().actions()
            if action.text() == "Other"
        )
        commands = [
            action
            for action in other_action.menu().actions()
            if not action.isSeparator()
        ]
        self.assertEqual(
            [action.text() for action in commands[:2]],
            ["Check for Updates", "Release Notes"],
        )
        with patch.object(
            self.window.update_service,
            "check_for_updates",
            return_value=True,
        ) as check:
            commands[0].trigger()

        check.assert_called_once_with(qt_main_window.APP_VERSION)
        self.assertTrue(self.window._manual_update_check)

    def test_startup_update_check_is_skipped_within_one_hour(self) -> None:
        checked_at = 1_789_123_456
        self.controller.last_update_check_at = checked_at
        self.save_settings_mock.reset_mock()

        with patch.object(
            self.window.update_service,
            "check_for_updates",
            return_value=True,
        ) as check:
            started = self.window.start_update_check(
                current_time=checked_at + 3_599
            )

        self.assertFalse(started)
        check.assert_not_called()
        self.save_settings_mock.assert_not_called()

    def test_startup_update_check_after_one_hour_saves_timestamp(self) -> None:
        checked_at = 1_789_123_456
        self.controller.last_update_check_at = checked_at
        self.save_settings_mock.reset_mock()

        with patch.object(
            self.window.update_service,
            "check_for_updates",
            return_value=True,
        ) as check:
            started = self.window.start_update_check(
                current_time=checked_at + 3_600
            )

        self.assertTrue(started)
        check.assert_called_once_with(qt_main_window.APP_VERSION)
        self.assertEqual(
            self.controller.last_update_check_at,
            checked_at + 3_600,
        )
        self.assertEqual(
            self.controller.current_settings().last_update_check_at,
            checked_at + 3_600,
        )
        self.save_settings_mock.assert_called_once()

    def test_manual_update_check_bypasses_interval_and_saves_timestamp(
        self,
    ) -> None:
        checked_at = 1_789_123_456
        self.controller.last_update_check_at = checked_at
        self.save_settings_mock.reset_mock()

        with patch.object(
            self.window.update_service,
            "check_for_updates",
            return_value=True,
        ) as check:
            started = self.window.start_update_check(
                manual=True,
                current_time=checked_at + 60,
            )

        self.assertTrue(started)
        check.assert_called_once_with(qt_main_window.APP_VERSION)
        self.assertTrue(self.window._manual_update_check)
        self.assertEqual(
            self.controller.last_update_check_at,
            checked_at + 60,
        )
        self.save_settings_mock.assert_called_once()

    def test_release_notes_checkbox_saves_immediately_when_checked(self) -> None:
        dialogs: list[QDialog] = []
        self.save_settings_mock.reset_mock()

        def execute(dialog: QDialog) -> int:
            dialogs.append(dialog)
            content = dialog.findChild(QPlainTextEdit, "ReleaseNotesContent")
            dont_show = dialog.findChild(
                QCheckBox,
                "ReleaseNotesDontShowAgain",
            )
            self.assertIsNotNone(content)
            self.assertEqual(
                content.toPlainText(),
                TEXT["en"]["release_notes_content"],
            )
            self.assertTrue(content.isReadOnly())
            self.assertIsNotNone(dont_show)
            dont_show.setChecked(True)
            return 0

        with patch.object(QDialog, "exec", new=execute):
            self.window._open_release_notes()

        self.assertEqual(len(dialogs), 1)
        self.assertTrue(
            self.controller.state.hide_release_notes_on_startup
        )
        self.assertTrue(
            self.controller.current_settings().hide_release_notes_on_startup
        )
        self.save_settings_mock.assert_called_once()

    def test_startup_release_notes_respect_hidden_setting(self) -> None:
        with patch.object(self.window, "_open_release_notes") as open_notes:
            self.window.show_startup_release_notes()
            open_notes.assert_called_once()

            self.controller.state.hide_release_notes_on_startup = True
            self.window.show_startup_release_notes()
            open_notes.assert_called_once()

    def test_main_schedules_startup_tasks(self) -> None:
        source = inspect.getsource(app_main.main)

        self.assertIn("window.run_startup_tasks", source)

    def test_main_activates_window_after_update_restart(self) -> None:
        source = inspect.getsource(app_main.main)

        self.assertIn("consume_update_restart_request()", source)
        self.assertIn("window._restore_from_tray", source)
        with patch.dict(
            os.environ,
            {app_main.UPDATE_RESTART_ENV: "1"},
            clear=False,
        ):
            self.assertTrue(app_main.consume_update_restart_request())
            self.assertNotIn(app_main.UPDATE_RESTART_ENV, os.environ)

    def test_startup_tasks_check_for_updates_and_show_release_notes(self) -> None:
        events: list[str] = []
        with (
            patch.object(
                self.window,
                "start_update_check",
                side_effect=lambda: events.append("check"),
            ) as check,
            patch.object(
                self.window,
                "show_pending_update_error",
                side_effect=lambda: events.append("error"),
            ) as error,
            patch.object(
                self.window,
                "show_startup_release_notes",
                side_effect=lambda: events.append("notes"),
            ) as notes,
        ):
            self.window.run_startup_tasks()

        check.assert_called_once_with()
        error.assert_called_once_with()
        notes.assert_called_once_with()
        self.assertEqual(events, ["error", "notes", "check"])

    def test_manual_update_check_reports_when_no_update_exists(self) -> None:
        self.window._manual_update_check = True
        dialogs: list[QDialog] = []

        with (
            patch.object(
                QDialog,
                "exec",
                new=lambda dialog: dialogs.append(dialog) or 0,
            ),
            patch("qt_main_window.QMessageBox.information") as information,
        ):
            self.window._update_check_completed(None)

        information.assert_not_called()
        self.assertEqual(len(dialogs), 1)
        dialog = dialogs[0]
        self.assertEqual(dialog.objectName(), "UpdateStatusDialog")
        self.assertEqual(dialog.windowTitle(), TEXT["en"]["update_title"])
        self.assertEqual(
            dialog.findChild(QLabel, "UpdateStatusMessage").text(),
            TEXT["en"]["no_updates"],
        )
        self.assertEqual(
            dialog.findChild(QPushButton, "UpdateStatusCloseButton").text(),
            TEXT["en"]["close"],
        )
        self.assertFalse(self.window._manual_update_check)

    def test_startup_update_check_opens_update_confirmation(self) -> None:
        update = AvailableUpdate(
            version="1.3.2",
            tag_name="v1.3.2",
            release_url=(
                "https://github.com/airknightjp/"
                "bpsr-midi-to-key-player/releases/tag/v1.3.2"
            ),
            asset=ReleaseAsset(
                name="BPSR_MIDI_to_KEY_Player_v1.3.2.zip",
                download_url=(
                    "https://github.com/airknightjp/"
                    "bpsr-midi-to-key-player/releases/download/"
                    "v1.3.2/BPSR_MIDI_to_KEY_Player_v1.3.2.zip"
                ),
                size=1024,
                sha256="a" * 64,
            ),
        )

        with patch.object(self.window, "_confirm_update") as confirm:
            self.window._update_check_completed(update)

        confirm.assert_called_once_with()
        self.assertIs(self.window._available_update, update)

    def test_manual_update_check_reports_network_failure(self) -> None:
        self.window._manual_update_check = True

        with patch("qt_main_window.QMessageBox.warning") as warning:
            self.window._update_check_failed("offline")

        warning.assert_called_once_with(
            self.window,
            TEXT["en"]["update_error_title"],
            TEXT["en"]["update_check_failed"].format(error="offline"),
        )
        self.assertFalse(self.window._manual_update_check)

    def test_startup_update_check_failure_is_silent(self) -> None:
        with patch("qt_main_window.QMessageBox.warning") as warning:
            self.window._update_check_failed("offline")

        warning.assert_not_called()

    def test_update_uses_one_external_progress_window(self) -> None:
        update = AvailableUpdate(
            version="1.3.2",
            tag_name="v1.3.2",
            release_url=(
                "https://github.com/airknightjp/"
                "bpsr-midi-to-key-player/releases/tag/v1.3.2"
            ),
            asset=ReleaseAsset(
                name="BPSR_MIDI_to_KEY_Player_v1.3.2.zip",
                download_url=(
                    "https://github.com/airknightjp/"
                    "bpsr-midi-to-key-player/releases/download/"
                    "v1.3.2/BPSR_MIDI_to_KEY_Player_v1.3.2.zip"
                ),
                size=10 * 1024 * 1024,
                sha256="a" * 64,
            ),
        )
        self.window._show_available_update(update)

        self.assertIs(self.window._available_update, update)
        self.assertFalse(hasattr(self.window, "update_notification_button"))
        with (
            patch(
                "qt_main_window.automatic_update_supported",
                return_value=True,
            ),
            patch(
                "qt_main_window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            patch(
                "qt_main_window.launch_update_installer",
                return_value=True,
            ) as launch,
            patch.object(self.window, "exit_application") as exit_app,
        ):
            self.window._confirm_update()

        launch.assert_called_once_with(
            update,
            process_id=os.getpid(),
            language="en",
        )
        exit_app.assert_called_once_with()
        self.assertNotIn(
            "QProgressDialog",
            inspect.getsource(qt_main_window),
        )

    def test_opacity_menu_is_ordered_from_100_percent_down(self) -> None:
        view_action = next(
            action for action in self.window.menuBar().actions() if action.text() == "View"
        )
        opacity_action = next(
            action for action in view_action.menu().actions() if action.text() == "Opacity"
        )

        self.assertEqual(
            [action.text() for action in opacity_action.menu().actions()],
            ["100%", "90%", "80%", "70%", "60%", "50%", "40%"],
        )

    def test_ocean_background_is_exclusive_to_sky_blue_theme(self) -> None:
        self.assertTrue(self.window.root_background.ocean_enabled)
        self.assertNotIn('QGroupBox[section="true"] {\n            background: rgba', self.window.styleSheet())
        self.assertIn(
            f'QGroupBox[section="true"] {{ background: {THEMES["sky_blue"].canvas}; }}',
            self.window.styleSheet(),
        )

        self.controller.set_option("color_theme", "green")
        self.assertFalse(self.window.root_background.ocean_enabled)

        self.controller.set_option("color_theme", "sky_blue")
        self.assertTrue(self.window.root_background.ocean_enabled)

    def test_settings_panels_use_each_theme_panel_background(self) -> None:
        for theme_name, palette in THEMES.items():
            with self.subTest(theme=theme_name):
                stylesheet = build_stylesheet(theme_name, 100)
                panel_rule = stylesheet.split(
                    "QWidget#SettingsPanel {",
                    1,
                )[1].split("}", 1)[0]
                self.assertIn(f"background: {palette.panel}", panel_rule)
                self.assertIn("border-radius: 4px", panel_rule)

        self.assertIn(
            "background: rgba(239, 251, 255, 116)",
            build_stylesheet("sky_blue", 100),
        )

    def test_player_controls_panel_uses_theme_background(self) -> None:
        for theme_name, palette in THEMES.items():
            with self.subTest(theme=theme_name):
                stylesheet = build_stylesheet(theme_name, 100)
                panel_rule = stylesheet.split(
                    "QFrame#PlayerControlsPanel {",
                    1,
                )[1].split("}", 1)[0]
                self.assertIn(
                    f"background: {opaque_rgba(palette.panel_alt)}",
                    panel_rule,
                )
                self.assertIn(
                    f"border: 1px solid {opaque_rgba(palette.border)}",
                    panel_rule,
                )
                self.assertIn(", 255)", panel_rule)

        self.assertTrue(
            self.window.transport_controls_panel.testAttribute(
                Qt.WidgetAttribute.WA_StyledBackground
            )
        )

    def test_ocean_background_has_visible_depth_and_surface_detail(self) -> None:
        background = ThemedBackground()
        background.resize(900, 600)
        background.set_ocean_enabled(True)
        background.show()
        self.application.processEvents()
        image = background.grab().toImage()

        top = image.pixelColor(450, 12)
        bottom = image.pixelColor(450, 587)
        sampled_colors = {
            image.pixelColor(x, y).rgba()
            for x in range(20, 900, 40)
            for y in range(20, 600, 40)
        }

        self.assertGreater(top.lightness(), bottom.lightness())
        self.assertGreater(len(sampled_colors), 80)
        background.close()

    def test_ocean_background_reuses_cached_pixmap_until_resized(self) -> None:
        background = ThemedBackground()
        background.resize(900, 600)
        background.set_ocean_enabled(True)
        background.show()
        self.application.processEvents()

        initial_cache_key = background._ocean_pixmap.cacheKey()
        background.update()
        self.application.processEvents()

        self.assertEqual(background._ocean_pixmap.cacheKey(), initial_cache_key)

        background.resize(901, 600)
        self.application.processEvents()

        self.assertNotEqual(background._ocean_pixmap.cacheKey(), initial_cache_key)
        self.assertEqual(background._ocean_pixmap.size(), background.size())
        background.close()

    def test_falling_notes_background_is_black_in_every_theme(self) -> None:
        for theme_name in THEMES:
            with self.subTest(theme=theme_name):
                self.controller.set_option("color_theme", theme_name)
                self.application.processEvents()
                self.assertEqual(
                    self.window.piano_roll._surface.name(),
                    "#000000",
                )

    def test_settings_items_use_two_left_aligned_rows(self) -> None:
        self.window.show()
        self.application.processEvents()
        common_items = (
            self.window.play_sound_check,
            self.window.auto_fit_check,
            self.window.repeat_check,
            self.window.auto_sustain_check,
        )
        performance_items = (
            self.window.humanize_check,
            self.window.strum_check,
            self.window.optimization_check,
        )

        self.assertTrue(all(item.property("settingsItem") for item in common_items + performance_items))
        self.assertIn('margin-left: 6px', self.window.styleSheet())
        self.assertEqual(len({item.geometry().top() for item in common_items}), 1)
        self.assertEqual(len({item.geometry().top() for item in performance_items}), 1)
        for previous, current in zip(common_items, common_items[1:]):
            self.assertLess(
                previous.geometry().right(),
                current.geometry().left(),
            )
        self.assertLess(common_items[-1].geometry().right(), self.window.settings_panel.width())
        self.assertLess(performance_items[-1].geometry().right(), self.window.settings_panel.width())

    def test_performance_settings_fit_in_every_language_and_scale(self) -> None:
        common_items = (
            self.window.play_sound_check,
            self.window.auto_fit_check,
            self.window.repeat_check,
            self.window.auto_sustain_check,
        )
        performance_items = (
            self.window.humanize_check,
            self.window.strum_check,
            self.window.optimization_check,
        )
        self.window.show()
        for language in ("en", "ja", "zh"):
            for scale in (100, 200):
                with self.subTest(language=language, scale=scale):
                    self.controller.set_option("language", language)
                    self.controller.set_option("ui_scale_percent", scale)
                    self.application.processEvents()

                    for items in (common_items, performance_items):
                        for previous, current in zip(items, items[1:]):
                            self.assertLess(
                                previous.geometry().right(),
                                current.geometry().left(),
                            )
                        self.assertLess(
                            items[-1].geometry().right(),
                            self.window.settings_panel.width(),
                        )

    def test_settings_checkbox_rows_have_vertical_clearance(self) -> None:
        self.window.show()
        self.application.processEvents()
        first_row_bottom = max(
            item.geometry().bottom()
            for item in (
                self.window.play_sound_check,
                self.window.auto_fit_check,
                self.window.repeat_check,
                self.window.auto_sustain_check,
            )
        )
        second_row_top = min(
            item.geometry().top()
            for item in (
                self.window.humanize_check,
                self.window.strum_check,
                self.window.optimization_check,
            )
        )
        self.assertGreater(second_row_top - first_row_bottom - 1, 0)

    def test_mode_switch_keeps_all_detailed_settings_enabled(self) -> None:
        for option in (
            "play_sound",
            "auto_fit_note_range",
            "repeat_prevention",
            "humanize_timing",
            "chord_strum",
            "chord_optimization",
            "auto_sustain",
        ):
            self.controller.set_option(option, True)
        self.controller.set_option("input_conversion_mode", "realtime")
        self.application.processEvents()

        detailed_settings = (
            self.window.play_sound_check,
            self.window.auto_fit_check,
            self.window.repeat_check,
            self.window.humanize_check,
            self.window.strum_check,
            self.window.optimization_check,
            self.window.auto_sustain_check,
        )
        self.assertTrue(all(check.isEnabled() for check in detailed_settings))
        self.assertTrue(all(check.isChecked() for check in detailed_settings))
        unsupported = (
            self.window.humanize_check,
            self.window.strum_check,
            self.window.optimization_check,
        )
        self.assertTrue(all(check.property("unsupported") for check in unsupported))

        self.controller.set_option("input_conversion_mode", "midi_file")
        self.application.processEvents()

        self.assertTrue(all(check.isEnabled() for check in detailed_settings))
        self.assertTrue(all(check.isChecked() for check in detailed_settings))
        self.assertTrue(all(not check.property("unsupported") for check in unsupported))

    def test_unsupported_realtime_settings_use_muted_theme_colors(self) -> None:
        for theme_name, palette in THEMES.items():
            with self.subTest(theme=theme_name):
                stylesheet = build_stylesheet(theme_name, 100)
                unsupported_rule = stylesheet.split(
                    'QCheckBox[unsupported="true"] {', 1
                )[1].split("}", 1)[0]
                self.assertIn(f"color: {palette.disabled};", unsupported_rule)

    def test_disabled_checkbox_text_uses_each_theme_disabled_color(self) -> None:
        for theme_name, palette in THEMES.items():
            with self.subTest(theme=theme_name):
                stylesheet = build_stylesheet(theme_name, 100)
                self.assertIn(
                    f"QCheckBox:disabled {{ color: {palette.disabled}; }}",
                    stylesheet,
                )

    def test_all_themes_use_the_compact_radio_selection_indicator(self) -> None:
        for theme_name, palette in THEMES.items():
            with self.subTest(theme=theme_name):
                stylesheet = build_stylesheet(theme_name, 100)
                base_rule = stylesheet.split(
                    "QRadioButton::indicator {",
                    1,
                )[1].split("}", 1)[0]
                checked_rule = stylesheet.split(
                    "QRadioButton::indicator:checked {",
                    1,
                )[1].split("}", 1)[0]
                color = "#ffffff" if theme_name == "dark" else palette.text

                self.assertIn("background: transparent;", base_rule)
                self.assertIn(f"solid {color};", base_rule)
                self.assertIn("background: qradialgradient(", checked_rule)
                self.assertIn(f"stop: 0 {color}", checked_rule)
                self.assertIn(f"border-color: {color};", checked_rule)
                self.assertIn("image: none;", checked_rule)

    def test_combo_popup_items_are_readable_in_every_theme(self) -> None:
        for theme_name, palette in THEMES.items():
            with self.subTest(theme=theme_name):
                stylesheet = build_stylesheet(theme_name, 100)
                popup_rule = stylesheet.split(
                    "QAbstractItemView {",
                    1,
                )[1].split("}", 1)[0]
                self.assertIn(f"background: {palette.surface};", popup_rule)
                self.assertIn(f"color: {palette.text};", popup_rule)
                self.assertIn(
                    f"selection-background-color: {palette.accent};",
                    popup_rule,
                )
                self.assertIn(
                    f"selection-color: {palette.accent_text};",
                    popup_rule,
                )

    def test_selected_table_cell_keeps_selection_color_while_hovered(self) -> None:
        for theme_name, palette in THEMES.items():
            with self.subTest(theme=theme_name):
                stylesheet = build_stylesheet(theme_name, 100)
                hover_position = stylesheet.index("QAbstractItemView::item:hover {")
                selected_hover_position = stylesheet.index(
                    "QAbstractItemView::item:selected:hover"
                )
                selected_hover_rule = stylesheet[
                    selected_hover_position:
                ].split("}", 1)[0]

                self.assertGreater(selected_hover_position, hover_position)
                self.assertIn(f"background: {palette.accent};", selected_hover_rule)
                self.assertIn(f"color: {palette.accent_text};", selected_hover_rule)

    def test_stylesheet_uses_the_original_windows_font_stack(self) -> None:
        self.assertIn(
            'font-family: "Yu Gothic UI", "Segoe UI", sans-serif;',
            build_stylesheet("sky_blue", 100),
        )

    def test_full_keyboard_uses_the_lower_settings_panel(self) -> None:
        self.window.show()
        self.application.processEvents()

        self.assertEqual(
            self.window.output_keyboard.parent(),
            self.window.settings_lower_panel,
        )
        self.assertEqual(self.window.output_keyboard.NOTE_MIN, 21)
        self.assertEqual(self.window.output_keyboard.NOTE_MAX, 108)
        self.assertEqual(
            len(
                [
                    note
                    for note in range(21, 109)
                    if note % 12 in self.window.output_keyboard.WHITE_PITCH_CLASSES
                ]
            ),
            52,
        )
        self.assertEqual(self.window.output_keyboard.height(), 57)
        self.assertEqual(
            self.window.output_keyboard.width(),
            self.window.settings_lower_panel.width() - 14,
        )

        self.controller.set_option("ui_scale_percent", 200)
        self.application.processEvents()
        self.assertEqual(self.window.output_keyboard.height(), 114)
        self.assertEqual(
            self.window.output_keyboard.width(),
            self.window.settings_lower_panel.width() - 28,
        )

    def test_piano_roll_panel_matches_the_keyboard_panel(self) -> None:
        self.window.show()
        self.application.processEvents()

        self.assertEqual(
            self.window.piano_roll_panel.size(),
            self.window.settings_lower_panel.size(),
        )
        self.assertEqual(self.window.piano_roll.height(), 57)
        self.assertEqual(
            self.window.piano_roll.width(),
            self.window.output_keyboard.width(),
        )
        self.assertLess(
            self.window.piano_roll_panel.geometry().bottom(),
            self.window.settings_lower_panel.geometry().top(),
        )

        self.controller.set_option("ui_scale_percent", 200)
        self.application.processEvents()
        self.assertEqual(
            self.window.piano_roll_panel.size(),
            self.window.settings_lower_panel.size(),
        )
        self.assertEqual(self.window.piano_roll.height(), 114)
        self.assertEqual(
            self.window.piano_roll.width(),
            self.window.output_keyboard.width(),
        )

    def test_animated_visuals_are_marked_as_opaque(self) -> None:
        self.assertTrue(
            self.window.piano_roll.testAttribute(
                Qt.WidgetAttribute.WA_OpaquePaintEvent
            )
        )
        self.assertTrue(
            self.window.output_keyboard.testAttribute(
                Qt.WidgetAttribute.WA_OpaquePaintEvent
            )
        )

    def test_loaded_midi_populates_the_falling_note_sequence(self) -> None:
        self.controller.events = [
            MidiEvent(1.0, "note_on", channel=0, note=60, velocity=90, track=0),
            MidiEvent(2.0, "note_off", channel=0, note=60, velocity=0, track=0),
        ]
        self.controller.state.track_channels = [TrackChannelItem(0, 0, True)]
        self.controller._set_enabled_sources(((0, 0),))
        self.controller._notify()

        self.assertEqual(
            self.window.piano_roll.sequence_notes,
            (PianoRollNote(1.0, 2.0, 60, source=(0, 0)),),
        )

    def test_live_checkbox_change_rebuilds_the_falling_note_sequence(self) -> None:
        self.controller.events = [
            MidiEvent(1.0, "note_on", channel=0, note=24, velocity=90, track=0),
            MidiEvent(2.0, "note_off", channel=0, note=24, velocity=0, track=0),
        ]
        self.controller.state.track_channels = [TrackChannelItem(0, 0, True)]
        self.controller.state.current_mode = "sound"
        self.controller._set_enabled_sources(((0, 0),))
        self.controller._notify()
        self.assertEqual(self.window.piano_roll.sequence_notes[0].note, 24)

        self.controller.set_option("auto_fit_note_range", True)
        self.application.processEvents()

        self.assertEqual(self.window.piano_roll.sequence_notes[0].note, 48)

    def test_auto_sustain_does_not_extend_the_falling_note_sequence(self) -> None:
        self.controller.events = [
            MidiEvent(0.0, "note_on", channel=0, note=60, velocity=90, track=0),
            MidiEvent(0.5, "note_off", channel=0, note=60, velocity=0, track=0),
            MidiEvent(2.0, "end"),
        ]
        self.controller.state.track_channels = [TrackChannelItem(0, 0, True)]
        self.controller._set_enabled_sources(((0, 0),))
        self.controller._notify()
        plain = self.window.piano_roll.sequence_notes

        with patch.object(
            self.window.piano_roll,
            "set_sequence_notes",
            wraps=self.window.piano_roll.set_sequence_notes,
        ) as set_sequence_notes:
            self.controller.set_option("auto_sustain", True)
            self.application.processEvents()

        self.assertTrue(self.controller.state.auto_sustain)
        self.assertEqual(
            plain,
            (PianoRollNote(0.0, 0.5, 60, source=(0, 0)),),
        )
        self.assertEqual(self.window.piano_roll.sequence_notes, plain)
        set_sequence_notes.assert_not_called()

    def test_realtime_output_event_does_not_create_a_live_trail(self) -> None:
        self.controller.midi_input_id = 8
        self.controller.worker_queue.put(("midi_output_note", 8, 64, True))

        self.controller.process_pending_events()

        self.assertEqual(self.window.piano_roll.live_trail_count, 0)
        self.assertEqual(self.controller.state.realtime_output_notes, frozenset((64,)))

    def test_simultaneous_sound_and_realtime_shows_only_realtime_on_keyboard(self) -> None:
        self.controller.playback_id = 3
        self.controller.midi_input_id = 4
        self.controller.state.current_mode = "sound"
        self.controller.state.midi_input_running = True
        self.controller.worker_queue.put(("sound_output_note", 3, 60, True, 10.0))
        self.controller.worker_queue.put(("midi_output_note", 4, 64, True, 10.0))

        with patch("app_controller.time.monotonic", return_value=10.0):
            self.controller.process_pending_events()

        self.assertEqual(
            self.controller.state.active_output_notes,
            frozenset((60, 64)),
        )
        self.assertEqual(
            self.window.output_keyboard.active_notes,
            frozenset((64,)),
        )

    def test_falling_note_body_uses_the_note_on_to_note_off_length(self) -> None:
        roll = FallingNotesWidget()
        roll.resize(1080, 57)
        roll.set_sequence_notes((PianoRollNote(0.25, 0.75, 60),))
        with patch("qt_components.time.monotonic", return_value=10.0):
            roll.set_playback_state(0.0, 100, False)
        roll.show()
        self.application.processEvents()
        with patch.object(
            roll,
            "_draw_note_span",
            wraps=roll._draw_note_span,
        ) as draw_span:
            roll.grab()

        draw_span.assert_called_once()
        top = draw_span.call_args.args[3]
        bottom = draw_span.call_args.args[4]
        self.assertAlmostEqual(
            bottom - top,
            (0.75 - 0.25) / roll.PREVIEW_SECONDS * (roll.height() - 1),
        )
        roll.close()

    def test_falling_notes_queries_only_the_visible_time_window(self) -> None:
        roll = FallingNotesWidget()
        notes = tuple(
            PianoRollNote(float(index), float(index) + 0.5, 60)
            for index in range(1000)
        )
        roll.set_sequence_notes(notes)

        visible = roll._visible_sequence_notes(500.0, roll.PREVIEW_SECONDS)

        self.assertEqual(
            visible,
            (notes[500], notes[501]),
        )

    def test_active_note_cache_stays_correct_across_forward_and_reverse_seeks(self) -> None:
        roll = FallingNotesWidget()
        notes = (
            PianoRollNote(0.0, 100.0, 48),
            PianoRollNote(1.0, 2.0, 60),
            PianoRollNote(10.0, 12.0, 64),
            PianoRollNote(50.0, 51.0, 67),
        )
        roll.set_sequence_notes(notes)

        for position in (0.0, 1.5, 11.0, 50.5, 10.5, 1.0, 99.0):
            with self.subTest(position=position):
                self.assertEqual(
                    roll._active_sequence_notes(position),
                    tuple(
                        note
                        for note in notes
                        if note.start <= position < note.end
                    ),
                )

    def test_falling_note_stays_visible_until_note_off(self) -> None:
        roll = FallingNotesWidget()
        note = PianoRollNote(0.25, 8.0, 60)
        roll.set_sequence_notes((note,))

        self.assertEqual(roll._visible_sequence_notes(0.26, 1.0), (note,))
        self.assertEqual(roll._visible_sequence_notes(8.0, 1.0), ())

    def test_falling_note_renders_three_distinct_judgment_effects(self) -> None:
        roll = FallingNotesWidget()
        source = (2, 3)

        perfect = roll._impact_style("PERFECT", source)
        great = roll._impact_style("GREAT", source)
        good = roll._impact_style("GOOD", source)

        self.assertEqual(
            (perfect[2:], great[2:], good[2:]),
            ((2,), (1,), (0,)),
        )
        self.assertEqual(
            {effect[0].name() for effect in (perfect, great, good)},
            {QColor(track_channel_color(*source)).name()},
        )
        self.assertGreater(perfect[1], great[1])
        self.assertGreater(great[1], good[1])
        self.assertGreater(
            roll._impact_duration("PERFECT"),
            roll._impact_duration("GREAT"),
        )
        self.assertGreater(
            roll._impact_duration("GREAT"),
            roll._impact_duration("GOOD"),
        )
        judgment_source = (
            inspect.getsource(roll._draw_impact_core)
            + inspect.getsource(roll._draw_impact_burst_direct)
        )
        self.assertNotIn("drawLine", judgment_source)
        self.assertNotIn("ray_count", judgment_source)
        self.assertNotIn("mote", judgment_source)

    def test_falling_note_hit_events_keep_state_while_lane_glow_is_hidden(self) -> None:
        roll = FallingNotesWidget()

        with patch("qt_components.time.monotonic", return_value=10.0):
            roll.set_hit_events(
                (
                    (1, 60, "PERFECT", False),
                    (2, 62, "GREAT", False),
                    (3, 64, "GOOD", False),
                )
            )

        self.assertEqual(roll.hit_impact_count, 3)
        self.assertEqual(
            roll.held_lane_notes,
            frozenset((60, 62, 64)),
        )
        with patch("qt_components.time.monotonic", return_value=11.0):
            roll.set_hit_events(((4, 60, "PERFECT", True),))
        self.assertNotIn(60, roll.held_lane_notes)
        self.assertEqual(roll.lane_fade_count, 1)
        self.assertFalse(hasattr(roll, "set_score"))
        self.assertFalse(roll.LANE_GLOW_ENABLED)
        roll.resize(1080, 57)
        roll.show()
        self.application.processEvents()
        with patch.object(roll, "_draw_lane_glow") as draw_lane_glow:
            roll.grab()
        draw_lane_glow.assert_not_called()

    def test_perfect_hit_draws_the_assigned_track_channel_color(self) -> None:
        roll = FallingNotesWidget()
        roll.resize(1080, 57)
        source = (2, 3)
        roll.set_sequence_notes(
            (PianoRollNote(0.0, 1.0, 60, source=source),)
        )
        roll.show()
        self.application.processEvents()
        with patch("qt_components.time.monotonic", return_value=10.0):
            roll.set_hit_events(((1, 60, "PERFECT", False),))
        roll._animation_timer.stop()

        with patch(
            "qt_components.time.monotonic",
            return_value=10.05,
        ), patch.object(
            roll,
            "_draw_impact_burst",
            wraps=roll._draw_impact_burst,
        ) as draw_burst:
            roll.grab()

        draw_burst.assert_called_once()
        self.assertFalse(draw_burst.call_args.kwargs["rainbow"])
        self.assertEqual(
            draw_burst.call_args.args[3].name(),
            QColor(track_channel_color(*source)).name(),
        )
        self.assertEqual(draw_burst.call_args.args[5:], (1.5, 2))
        roll.close()

    def test_falling_note_ignores_removed_miss_effect(self) -> None:
        roll = FallingNotesWidget()

        roll.set_hit_events(((1, 60, "MISS", False),))

        self.assertEqual(roll.hit_impact_count, 0)
        self.assertEqual(roll.lane_fade_count, 0)

    def test_hit_effect_source_uses_start_and_end_positions(self) -> None:
        roll = FallingNotesWidget()
        first = PianoRollNote(1.0, 2.0, 60, source=(0, 0))
        second = PianoRollNote(4.0, 6.0, 60, source=(3, 2))
        roll.set_sequence_notes((first, second))

        self.assertEqual(
            roll._impact_source(60, 4.05, released=False),
            second.source,
        )
        self.assertEqual(
            roll._impact_source(60, 5.95, released=True),
            second.source,
        )

    def test_falling_note_head_disappears_after_reaching_the_hit_line(self) -> None:
        roll = FallingNotesWidget()
        roll.resize(1080, 57)
        roll.set_sequence_notes((PianoRollNote(0.25, 2.0, 60),))
        roll.show()
        self.application.processEvents()

        with patch("qt_components.time.monotonic", return_value=10.0):
            roll.set_playback_state(0.0, 100, False)
        with patch.object(
            roll,
            "_draw_light_bar",
            wraps=roll._draw_light_bar,
        ) as approaching_head:
            roll.grab()
        self.assertEqual(approaching_head.call_count, 1)

        with patch("qt_components.time.monotonic", return_value=10.0):
            roll.set_playback_state(0.5, 100, False)
        with patch.object(
            roll,
            "_draw_light_bar",
            wraps=roll._draw_light_bar,
        ) as held_head, patch.object(
            roll,
            "_minimum_note_body_height",
            wraps=roll._minimum_note_body_height,
        ) as held_minimum:
            roll.grab()
        held_head.assert_not_called()
        held_minimum.assert_not_called()
        roll.close()

    def test_falling_note_assets_are_cached_and_reused(self) -> None:
        roll = FallingNotesWidget()
        roll.resize(1080, 57)
        roll.set_sequence_notes((PianoRollNote(0.25, 0.75, 60),))
        with patch("qt_components.time.monotonic", return_value=10.0):
            roll.set_playback_state(0.0, 100, False)
        roll.show()
        self.application.processEvents()

        with patch("qt_components.time.monotonic", return_value=10.0):
            roll.grab()
        first_body_ids = tuple(
            sorted(pixmap.cacheKey() for pixmap in roll._note_body_cache.values())
        )
        first_bar_ids = tuple(
            sorted(pixmap.cacheKey() for pixmap in roll._light_bar_cache.values())
        )
        with patch("qt_components.time.monotonic", return_value=10.0):
            roll.grab()

        self.assertTrue(first_body_ids)
        self.assertTrue(first_bar_ids)
        self.assertEqual(
            first_body_ids,
            tuple(
                sorted(
                    pixmap.cacheKey()
                    for pixmap in roll._note_body_cache.values()
                )
            ),
        )
        self.assertEqual(
            first_bar_ids,
            tuple(
                sorted(
                    pixmap.cacheKey()
                    for pixmap in roll._light_bar_cache.values()
                )
            ),
        )
        roll.close()

    def test_falling_note_assets_preserve_subpixel_vertical_motion(self) -> None:
        roll = FallingNotesWidget()
        roll.resize(1080, 57)
        roll.set_sequence_notes((PianoRollNote(0.44, 0.70, 60),))
        roll.show()
        self.application.processEvents()

        with patch("qt_components.time.monotonic", return_value=10.0):
            roll.set_playback_state(0.0, 100, False)
            first = roll.grab().toImage()
            roll.set_playback_state(0.005, 100, False)
            second = roll.grab().toImage()

        self.assertTrue(
            any(
                first.pixelColor(x, y) != second.pixelColor(x, y)
                for x in range(first.width())
                for y in range(first.height())
            )
        )
        roll.close()

    def test_running_position_sync_does_not_request_a_duplicate_full_repaint(self) -> None:
        roll = FallingNotesWidget()
        roll.resize(1080, 57)
        roll.set_sequence_notes((PianoRollNote(0.25, 0.75, 60),))
        with patch("qt_components.time.monotonic", return_value=10.0):
            roll.set_playback_state(0.0, 100, True)
        roll._animation_timer.stop()

        with patch.object(roll, "update") as update, patch(
            "qt_components.time.monotonic",
            return_value=10.01,
        ):
            roll.set_playback_state(0.01, 100, True)

        update.assert_not_called()

    def test_falling_note_trail_uses_the_strengthened_opacity(self) -> None:
        self.assertEqual(
            FallingNotesWidget.APPROACHING_TRAIL_GLOW_STOPS,
            ((0.0, 0), (0.55, 31), (1.0, 120)),
        )
        self.assertEqual(
            FallingNotesWidget.APPROACHING_TRAIL_CORE_STOPS,
            ((0.0, 16), (0.62, 189), (1.0, 255)),
        )
        self.assertEqual(
            FallingNotesWidget.HELD_TRAIL_GLOW_STOPS,
            ((0.0, 0), (0.60, 31), (0.88, 57), (1.0, 0)),
        )
        self.assertEqual(
            FallingNotesWidget.HELD_TRAIL_CORE_STOPS,
            ((0.0, 16), (0.58, 189), (0.88, 150), (1.0, 0)),
        )

    def test_short_notes_receive_only_a_visual_minimum_pixel_length(self) -> None:
        roll = FallingNotesWidget()
        for scale in (1.0, 2.0):
            roll.apply_scale(scale)
            minimum = roll._minimum_note_body_height(12.0 * scale)

            self.assertGreaterEqual(minimum, 4.0 * scale)
            self.assertLessEqual(minimum, 6.0 * scale)

    def test_falling_note_lane_lines_align_with_white_key_boundaries(self) -> None:
        roll = FallingNotesWidget()
        roll.resize(1080, 57)
        roll.show()
        self.application.processEvents()

        image = roll.grab().toImage()
        white_note_count = sum(
            1
            for note in range(roll.NOTE_MIN, roll.NOTE_MAX + 1)
            if note % 12 in roll.WHITE_PITCH_CLASSES
        )
        white_width = (roll.width() - 1) / white_note_count
        boundary_x = round(white_width * 10 + 0.5)
        lane_center_x = round(boundary_x + white_width / 2)

        self.assertNotEqual(
            image.pixelColor(boundary_x, 20),
            image.pixelColor(lane_center_x, 20),
        )
        roll.close()

    def test_falling_note_heads_use_the_matching_piano_key_width(self) -> None:
        roll = FallingNotesWidget()
        width = 1079.0
        white_note_count = sum(
            1
            for note in range(roll.NOTE_MIN, roll.NOTE_MAX + 1)
            if note % 12 in roll.WHITE_PITCH_CLASSES
        )
        white_key_width = width / white_note_count

        _white_x, white_head_width = roll._note_rect(60, width)
        _black_x, black_head_width = roll._note_rect(61, width)

        self.assertAlmostEqual(white_head_width, white_key_width)
        self.assertAlmostEqual(black_head_width, white_key_width * 0.62)

    def test_falling_note_head_reaches_bottom_at_each_scale(self) -> None:
        roll = FallingNotesWidget()
        for scale in (1.0, 2.0):
            roll.apply_scale(scale)
            roll.resize(round(1080 * scale), round(57 * scale))
            _x, note_width = roll._note_rect(60, roll.width() - 1)
            bar_height, outline_width = roll._light_bar_metrics(note_width)

            center_y = roll._clamp_light_bar_center(
                float(roll.height() - 1),
                note_width,
            )

            self.assertAlmostEqual(
                center_y + (bar_height + outline_width) / 2.0,
                float(roll.height() - 1),
            )

    def test_keyboard_panel_uses_reduced_height_and_full_settings_width(self) -> None:
        self.window.show()
        self.application.processEvents()

        self.assertEqual(self.window.settings_lower_panel.height(), 71)
        self.assertEqual(
            self.window.settings_lower_panel.width(),
            self.window.settings_panel.width(),
        )
        self.assertGreater(
            self.window.settings_lower_panel.geometry().top(),
            self.window.settings_panel.geometry().bottom(),
        )
        self.assertEqual(self.window.settings_lower_gap.height(), 6)

        self.controller.set_option("ui_scale_percent", 200)
        self.application.processEvents()
        self.assertEqual(self.window.settings_lower_panel.height(), 142)
        self.assertEqual(
            self.window.settings_lower_panel.width(),
            self.window.settings_panel.width(),
        )
        self.assertEqual(self.window.settings_lower_gap.height(), 12)

    def test_full_keyboard_renders_final_output_note_state(self) -> None:
        self.controller.state.active_output_notes = frozenset((21, 61, 108))
        self.controller.state.output_note_sources = ((61, 2, 3),)
        self.controller._notify()

        self.assertEqual(
            self.window.output_keyboard.active_notes,
            frozenset((21, 61, 108)),
        )
        self.assertEqual(
            self.window.output_keyboard._note_sources,
            {61: ((2, 3),)},
        )

    def test_full_keyboard_temporarily_uses_one_pressed_key_color(self) -> None:
        keyboard = PianoKeyboardWidget()
        keyboard.set_colors(
            "#ffffff",
            "#808080",
            "#202020",
            "#1458D4",
            "#0B3D9A",
            "#ffffff",
        )
        keyboard.set_note_sources(((60, 0, 0), (64, 3, 7)))

        first_brush = keyboard._active_note_brush(
            60,
            QRectF(0.0, 0.0, 10.0, 20.0),
        )
        second_brush = keyboard._active_note_brush(
            64,
            QRectF(10.0, 0.0, 10.0, 20.0),
        )

        self.assertEqual(first_brush.color().name(), "#1458d4")
        self.assertEqual(second_brush.color().name(), "#1458d4")
        self.assertEqual(keyboard._active_note_border(60).name(), "#0b3d9a")
        self.assertEqual(keyboard._active_note_border(64).name(), "#0b3d9a")

    def test_final_output_range_updates_keyboard_and_falling_notes(self) -> None:
        self.controller.events = [
            MidiEvent(0.0, "note_on", channel=0, note=24, velocity=90, track=0),
            MidiEvent(1.0, "note_on", channel=0, note=84, velocity=90, track=0),
        ]
        self.controller.state.track_channels = [TrackChannelItem(0, 0, True)]
        self.controller._set_enabled_sources(((0, 0),))
        self.controller.state.auto_fit_note_range = True
        self.controller._notify()

        self.assertEqual(self.window.output_keyboard.used_note_range, (48, 72))
        self.assertEqual(self.window.piano_roll.used_note_range, (48, 72))

        self.controller.set_option("transpose_semitones", 2)
        self.application.processEvents()

        self.assertEqual(self.window.output_keyboard.used_note_range, (50, 74))
        self.assertEqual(self.window.piano_roll.used_note_range, (50, 74))

    def test_unused_final_output_range_is_visually_dimmed(self) -> None:
        keyboard = PianoKeyboardWidget()
        keyboard.resize(1080, 57)
        keyboard.show()
        roll = FallingNotesWidget()
        roll.resize(1080, 57)
        roll.show()
        self.application.processEvents()
        keyboard_plain = keyboard.grab().toImage()
        roll_plain = roll.grab().toImage()

        keyboard.set_used_note_range((48, 72))
        roll.set_used_note_range((48, 72))
        self.application.processEvents()
        keyboard_ranged = keyboard.grab().toImage()
        roll_ranged = roll.grab().toImage()

        white_notes = [
            note
            for note in range(keyboard.NOTE_MIN, keyboard.NOTE_MAX + 1)
            if note % 12 in keyboard.WHITE_PITCH_CLASSES
        ]
        white_width = (keyboard.width() - 1) / len(white_notes)
        unused_x = round((white_notes.index(21) + 0.5) * white_width)
        used_x = round((white_notes.index(60) + 0.5) * white_width)
        self.assertNotEqual(
            keyboard_plain.pixelColor(unused_x, 30),
            keyboard_ranged.pixelColor(unused_x, 30),
        )
        self.assertLessEqual(
            keyboard_ranged.pixelColor(unused_x, 30).lightness(),
            keyboard_plain.pixelColor(unused_x, 30).lightness() - 30,
        )
        self.assertEqual(
            keyboard_plain.pixelColor(used_x, 30),
            keyboard_ranged.pixelColor(used_x, 30),
        )
        self.assertEqual(
            roll.UNUSED_RANGE_OVERLAY_ALPHA,
            205,
        )
        self.assertEqual(
            keyboard._unused_surface,
            QColor("#000000"),
        )
        black_positions = dict(keyboard._black_note_positions)
        unused_black_x = round(black_positions[22] * white_width)
        used_black_x = round(black_positions[49] * white_width)
        hatch_texture = keyboard._unused_key_brush.texture().toImage()
        hatch_colors = {
            hatch_texture.pixelColor(x, y).rgba()
            for x in range(hatch_texture.width())
            for y in range(hatch_texture.height())
        }
        self.assertIn(QColor("#000000").rgba(), hatch_colors)
        self.assertGreater(len(hatch_colors), 1)
        self.assertNotEqual(
            keyboard_ranged.pixelColor(unused_black_x, 10),
            keyboard_plain.pixelColor(unused_black_x, 10),
        )
        self.assertEqual(
            keyboard_plain.pixelColor(used_black_x, 10),
            keyboard_ranged.pixelColor(used_black_x, 10),
        )
        unused_roll_rect = roll._note_rect(21, roll.width() - 1)
        used_roll_rect = roll._note_rect(60, roll.width() - 1)
        self.assertIsNotNone(unused_roll_rect)
        self.assertIsNotNone(used_roll_rect)
        unused_roll_end = round(
            unused_roll_rect[0] + unused_roll_rect[1]
        )
        used_roll_start = round(used_roll_rect[0])
        used_roll_end = round(used_roll_rect[0] + used_roll_rect[1])
        self.assertTrue(
            any(
                roll_plain.pixelColor(x, y) != roll_ranged.pixelColor(x, y)
                for x in range(0, max(1, unused_roll_end))
                for y in range(roll.height())
            )
        )
        self.assertFalse(
            any(
                roll_plain.pixelColor(x, y) != roll_ranged.pixelColor(x, y)
                for x in range(used_roll_start, max(used_roll_start + 1, used_roll_end))
                for y in range(roll.height())
            )
        )
        keyboard.close()
        roll.close()

    def test_three_octave_keyboard_visibly_changes_a_pressed_key(self) -> None:
        keyboard = PianoKeyboardWidget()
        keyboard.resize(420, 76)
        keyboard.show()
        self.application.processEvents()
        released = keyboard.grab().toImage()

        keyboard.set_active_notes((48,))
        self.application.processEvents()
        pressed = keyboard.grab().toImage()

        white_notes = [
            note
            for note in range(keyboard.NOTE_MIN, keyboard.NOTE_MAX + 1)
            if note % 12 in keyboard.WHITE_PITCH_CLASSES
        ]
        white_width = (keyboard.width() - 1) / len(white_notes)
        x = round((white_notes.index(48) + 0.5) * white_width)
        self.assertNotEqual(released.pixelColor(x, 30), pressed.pixelColor(x, 30))
        keyboard.close()

    def test_three_octave_keyboard_visibly_releases_and_represses_a_retriggered_key(self) -> None:
        keyboard = PianoKeyboardWidget()
        keyboard.show()
        self.application.processEvents()
        released = keyboard.grab().toImage()

        keyboard.set_active_notes((48,))
        self.application.processEvents()
        held = keyboard.grab().toImage()

        keyboard.set_retrigger_events(((48, 1),))
        self.application.processEvents()
        visually_released = keyboard.grab().toImage()

        self.assertEqual(
            released.pixelColor(8, 30),
            visually_released.pixelColor(8, 30),
        )
        self.assertTrue(keyboard._retrigger_timer.isActive())

        release_ms = round(keyboard.RETRIGGER_RELEASE_SECONDS * 1000)
        midpoint_ms = max(1, release_ms // 2)
        QTest.qWait(midpoint_ms)
        self.application.processEvents()
        still_released = keyboard.grab().toImage()
        self.assertEqual(
            released.pixelColor(8, 30),
            still_released.pixelColor(8, 30),
        )

        remaining_ms = release_ms - midpoint_ms
        QTest.qWait(remaining_ms + 30)
        self.application.processEvents()
        repressed = keyboard.grab().toImage()

        self.assertEqual(held.pixelColor(8, 30), repressed.pixelColor(8, 30))
        self.assertFalse(keyboard._retrigger_timer.isActive())
        keyboard.close()

    def test_three_octave_keyboard_retriggers_every_note_in_a_chord(self) -> None:
        keyboard = PianoKeyboardWidget()
        keyboard.show()
        self.application.processEvents()
        released = keyboard.grab().toImage()

        notes = (48, 52, 55)
        keyboard.set_active_notes(notes)
        self.application.processEvents()
        held = keyboard.grab().toImage()
        keyboard.set_retrigger_events(((48, 1), (52, 2), (55, 3)))
        self.application.processEvents()
        visually_released = keyboard.grab().toImage()

        white_notes = [
            note
            for note in range(keyboard.NOTE_MIN, keyboard.NOTE_MAX + 1)
            if note % 12 in keyboard.WHITE_PITCH_CLASSES
        ]
        white_width = (keyboard.width() - 1) / len(white_notes)
        for note in notes:
            x = round((white_notes.index(note) + 0.5) * white_width)
            y = keyboard.height() - 8
            self.assertNotEqual(
                released.pixelColor(x, y),
                held.pixelColor(x, y),
            )
            self.assertEqual(
                released.pixelColor(x, y),
                visually_released.pixelColor(x, y),
            )

        keyboard.close()

    def test_dark_theme_keeps_white_and_black_piano_keys_distinct(self) -> None:
        self.controller.set_option("color_theme", "dark")
        self.window.show()
        self.application.processEvents()
        image = self.window.output_keyboard.grab().toImage()
        white_notes = [
            note
            for note in range(
                self.window.output_keyboard.NOTE_MIN,
                self.window.output_keyboard.NOTE_MAX + 1,
            )
            if note % 12 in self.window.output_keyboard.WHITE_PITCH_CLASSES
        ]
        white_width = (self.window.output_keyboard.width() - 1) / len(white_notes)

        white_key = image.pixelColor(round(white_width * 0.3), 30)
        black_key = image.pixelColor(round(white_width), 20)

        self.assertGreater(white_key.lightness() - black_key.lightness(), 60)

    def test_settings_panel_has_no_group_captions_and_balanced_vertical_padding(self) -> None:
        self.window.show()
        self.application.processEvents()
        self.assertFalse(hasattr(self.window, "common_caption"))
        self.assertFalse(hasattr(self.window, "performance_caption"))
        items = (
            self.window.play_sound_check,
            self.window.auto_fit_check,
            self.window.repeat_check,
            self.window.humanize_check,
            self.window.strum_check,
            self.window.optimization_check,
            self.window.auto_sustain_check,
        )
        content_top = min(item.geometry().top() for item in items)
        content_bottom = max(item.geometry().bottom() for item in items)
        top_padding = content_top
        bottom_padding = self.window.settings_panel.height() - content_bottom - 1
        self.assertAlmostEqual(top_padding, bottom_padding, delta=2)

    def test_section_title_backgrounds_use_rounded_corners_in_every_theme(self) -> None:
        for theme in THEMES:
            with self.subTest(theme=theme):
                self.controller.set_option("color_theme", theme)
                title_rule = self.window.styleSheet().split('QGroupBox[section="true"]::title', 1)[1]
                self.assertIn("border-radius: 4px", title_rule.split("}", 1)[0])

    def test_all_themes_use_rich_high_contrast_checkbox_indicators(self) -> None:
        for theme_name, palette in THEMES.items():
            with self.subTest(theme=theme_name):
                stylesheet = build_stylesheet(theme_name, 100)
                base_rule = stylesheet.split("QCheckBox::indicator {", 1)[1].split("}", 1)[0]
                hover_rule = stylesheet.split("QCheckBox::indicator:hover", 1)[1].split("}", 1)[0]
                checked_rule = stylesheet.split("QCheckBox::indicator:checked {", 1)[1].split("}", 1)[0]
                disabled_rule = stylesheet.split(
                    "QCheckBox::indicator:checked:disabled",
                    1,
                )[1].split("}", 1)[0]

                self.assertIn("width: 16px", base_rule)
                self.assertIn("height: 16px", base_rule)
                self.assertIn("border-radius: 4px", base_rule)
                self.assertIn(f"border-color: {palette.accent}", hover_rule)
                self.assertIn(f"background: {palette.accent}", checked_rule)
                self.assertIn(f"border: 1px solid {palette.accent_hover}", checked_rule)
                self.assertIn("check_white.svg", checked_rule)
                self.assertIn("image: url", checked_rule)
                self.assertIn(f"background: {palette.disabled}", disabled_rule)

    def test_slider_handle_shape_scales_without_becoming_rectangular(self) -> None:
        compact_stylesheet = build_stylesheet("light", 100)
        compact_volume_rule = compact_stylesheet.split(
            "QSlider#VolumeSlider::handle:horizontal",
            1,
        )[1].split("}", 1)[0]
        stylesheet = build_stylesheet("light", 200)
        vertical_rule = stylesheet.split("QSlider::handle:vertical", 1)[1].split("}", 1)[0]
        horizontal_rule = stylesheet.split("QSlider::handle:horizontal", 1)[1].split("}", 1)[0]
        volume_rule = stylesheet.split(
            "QSlider#VolumeSlider::handle:horizontal",
            1,
        )[1].split("}", 1)[0]
        self.assertIn("height: 28px", vertical_rule)
        self.assertIn("margin: 0 -10px", vertical_rule)
        self.assertIn("border-radius: 14px", vertical_rule)
        self.assertIn("width: 28px", horizontal_rule)
        self.assertIn("margin: -10px 0", horizontal_rule)
        self.assertIn("border-radius: 14px", horizontal_rule)
        self.assertIn("width: 11px", compact_volume_rule)
        self.assertIn("height: 11px", compact_volume_rule)
        self.assertIn("border-radius: 7px", compact_volume_rule)
        self.assertIn("width: 22px", volume_rule)
        self.assertIn("height: 22px", volume_rule)
        self.assertIn("margin: -10px 0", volume_rule)
        self.assertIn("border-radius: 15px", volume_rule)
        self.assertNotIn(
            "QSlider#PlaybackPositionSlider::handle:horizontal",
            stylesheet,
        )

    def test_sky_blue_theme_reserves_a_larger_animated_whale_handle(self) -> None:
        sky_blue_stylesheet = build_stylesheet("sky_blue", 200)
        light_stylesheet = build_stylesheet("light", 200)
        selector = (
            'QSlider#PlaybackPositionSlider'
            '[animatedWhale="true"]::handle:horizontal'
        )
        horizontal_rule = sky_blue_stylesheet.rsplit(selector, 1)[1].split("}", 1)[0]

        self.assertIn("width: 48px", horizontal_rule)
        self.assertIn("height: 48px", horizontal_rule)
        self.assertIn("background: transparent", horizontal_rule)
        self.assertNotIn("image: url", horizontal_rule)
        self.assertNotIn(selector, light_stylesheet)

    def test_sky_blue_whale_animates_only_while_playback_is_running(self) -> None:
        self.window.show()
        self.application.processEvents()

        self.assertEqual(self.window.position_slider.whale_frame_count, 3)
        self.assertEqual(self.window.position_slider.whale_handle_size, 24)
        self.assertEqual(self.window.position_slider.whale_vertical_offset, 2.0)
        self.assertEqual(self.window.position_slider.height(), 24)
        self.assertFalse(self.window.position_slider.whale_animation_active)
        self.assertFalse(self.window.position_slider.whale_spout_active)

        self.window.position_slider.set_playback_running(True)
        self.assertTrue(self.window.position_slider.whale_animation_active)
        self.assertTrue(self.window.position_slider.whale_spout_active)
        previous = self.window.position_slider._whale_frame_position
        self.window.position_slider._advance_whale_frame()
        self.assertNotEqual(
            self.window.position_slider._whale_frame_position,
            previous,
        )

        self.window.position_slider.set_playback_running(False)
        stopped_frame = self.window.position_slider._whale_frame_position
        self.window.position_slider._advance_whale_frame()
        self.assertFalse(self.window.position_slider.whale_animation_active)
        self.assertFalse(self.window.position_slider.whale_spout_active)
        self.assertEqual(
            self.window.position_slider._whale_frame_position,
            stopped_frame,
        )

        self.controller.set_option("color_theme", "light")
        self.application.processEvents()
        self.assertEqual(self.window.position_slider.whale_frame_count, 0)
        self.assertEqual(self.window.position_slider.whale_vertical_offset, 0.0)
        self.assertFalse(self.window.position_slider.whale_animation_active)

    def test_whale_spout_runs_only_during_its_periodic_animation_phase(self) -> None:
        slider = self.window.position_slider
        slider.resize(400, 22)
        slider.show()
        slider.set_playback_running(True)
        self.application.processEvents()

        slider._whale_animation_tick = 1
        with patch.object(
            slider,
            "_draw_whale_spout",
            wraps=slider._draw_whale_spout,
        ) as active_spout:
            slider.grab()
        active_spout.assert_called_once()

        slider._whale_animation_tick = slider.WHALE_SPOUT_ACTIVE_FRAMES
        self.assertFalse(slider.whale_spout_active)

    def test_animated_whale_handle_scales_with_the_ui(self) -> None:
        self.controller.set_option("ui_scale_percent", 200)
        self.window.show()
        self.application.processEvents()

        self.assertEqual(self.window.position_slider.whale_frame_count, 3)
        self.assertEqual(self.window.position_slider.whale_handle_size, 48)
        self.assertEqual(self.window.position_slider.whale_vertical_offset, 4.0)
        self.assertEqual(self.window.position_slider.height(), 48)

    def test_sky_blue_theme_menu_item_uses_whale_icon(self) -> None:
        self.window.show()
        self.application.processEvents()

        sky_blue_action = self.window.theme_actions["sky_blue"]
        light_action = self.window.theme_actions["light"]

        self.assertEqual(sky_blue_action.text(), "Sky Blue")
        self.assertFalse(sky_blue_action.icon().isNull())
        self.assertTrue(light_action.icon().isNull())

    def test_sound_source_is_not_duplicated_in_the_settings_menu(self) -> None:
        self.assertFalse(hasattr(self.window, "sound_source_actions"))

    def test_sound_source_selector_is_on_the_right_end_of_the_midi_tab_row(self) -> None:
        self.window.show()
        self.application.processEvents()

        tab_top = self.window.tab_bar.mapTo(self.window, QPoint(0, 0)).y()
        source_top = self.window.sound_source_controls.mapTo(
            self.window,
            QPoint(0, 0),
        ).y()
        self.assertEqual(source_top, tab_top)
        self.assertGreater(
            self.window.sound_source_controls.geometry().left(),
            self.window.tab_bar_container.geometry().right(),
        )

        organ_index = self.window.sound_source_combo.findData("organ")
        self.window.sound_source_combo.setCurrentIndex(organ_index)
        self.assertEqual(self.controller.state.sound_source, "organ")

        self.controller.state.audio_qt_frames = 256
        self.controller.state.audio_buffer_frames = 1_024
        self.controller._notify()
        self.application.processEvents()
        self.assertEqual(self.window.audio_qt_combo.currentData(), 256)
        self.assertEqual(
            self.window.audio_buffer_combo.currentData(),
            1_024,
        )
        self.assertEqual(
            self.window.audio_qt_label.property("caption"),
            self.window.volume_control.value_label.property("caption"),
        )
        runtime_center = self.window.audio_runtime_widget.mapTo(
            self.window,
            self.window.audio_runtime_widget.rect().center(),
        )
        menu_center = self.window.menuBar().mapTo(
            self.window,
            self.window.menuBar().rect().center(),
        )
        self.assertAlmostEqual(
            runtime_center.y(),
            menu_center.y(),
            delta=1,
        )
        self.assertEqual(
            self.window.audio_runtime_widget.mapTo(
                self.window.menuBar(),
                QPoint(self.window.audio_runtime_widget.width(), 0),
            ).x(),
            self.window.menuBar().rect().right(),
        )

        self.controller.set_option("language", "ja")
        self.assertEqual(self.window.audio_qt_label.text(), "Qt")
        self.assertEqual(self.window.audio_buffer_label.text(), "Buffer")

    def test_audio_settings_are_selectable_at_every_language_and_scale(self) -> None:
        self.window.show()
        for language in ("en", "ja", "zh"):
            for scale in (100, 150, 200):
                with self.subTest(language=language, scale=scale):
                    self.controller.set_option("language", language)
                    self.controller.set_option("ui_scale_percent", scale)
                    self.application.processEvents()
                    self.assertEqual(
                        self.window.menuBar().cornerWidget(
                            Qt.Corner.TopRightCorner
                        ),
                        self.window.audio_runtime_widget,
                    )
                    self.assertEqual(
                        self.window.audio_runtime_layout.contentsMargins().right(),
                        round(8 * scale / 100),
                    )
                    self.assertGreater(self.window.audio_qt_combo.width(), 0)
                    self.assertGreater(
                        self.window.audio_buffer_combo.width(),
                        0,
                    )
                    expected_menu_height = round(24 * scale / 100)
                    self.assertEqual(
                        self.window.audio_runtime_widget.height(),
                        expected_menu_height,
                    )
                    self.assertEqual(
                        self.window.audio_qt_combo.height(),
                        round(20 * scale / 100),
                    )
                    self.assertEqual(
                        self.window.audio_buffer_combo.height(),
                        round(20 * scale / 100),
                    )
                    self.assertLessEqual(
                        self.window.menuBar().height(),
                        round(26 * scale / 100),
                    )

        qt_index = self.window.audio_qt_combo.findData(512)
        buffer_index = self.window.audio_buffer_combo.findData(2_048)
        self.window.audio_qt_combo.setCurrentIndex(qt_index)
        self.window.audio_buffer_combo.setCurrentIndex(buffer_index)
        self.assertEqual(self.controller.state.audio_qt_frames, 512)
        self.assertEqual(self.controller.state.audio_buffer_frames, 2_048)
    def test_three_knobs_stay_left_of_the_center_transport_button(self) -> None:
        self.window.show()
        for language in ("en", "ja", "zh"):
            for scale in (100, 150, 200):
                with self.subTest(language=language, scale=scale):
                    self.controller.set_option("language", language)
                    self.controller.set_option("ui_scale_percent", scale)
                    self.application.processEvents()
                    controls = (
                        self.window.speed_control,
                        self.window.transpose_control,
                        self.window.octave_control,
                    )
                    control_centers = [
                        control.knob.mapTo(
                            self.window,
                            control.knob.rect().center(),
                        ).x()
                        for control in controls
                    ]
                    self.assertEqual(control_centers, sorted(control_centers))
                    play_button_left = self.window.sound_play_pause_button.mapTo(
                        self.window,
                        QPoint(0, 0),
                    ).x()
                    self.assertLess(
                        max(control_centers),
                        play_button_left,
                    )

    def test_round_knobs_remain_circular_when_scaled(self) -> None:
        self.controller.set_option("ui_scale_percent", 200)
        self.window.show()
        self.application.processEvents()

        self.assertEqual(self.window.speed_control.knob.size(), QSize(66, 66))
        self.assertEqual(self.window.transpose_control.knob.size(), QSize(66, 66))
        self.assertEqual(self.window.octave_control.knob.size(), QSize(66, 66))
        self.assertEqual(self.window.countdown_control.knob.size(), QSize(72, 72))
        self.assertEqual(
            self.window.volume_control.slider.orientation(),
            Qt.Orientation.Horizontal,
        )
        self.assertLessEqual(self.window.speed_control.knob.width(), self.window.speed_control.width())

    def test_fixed_layout_dimensions_follow_ui_scale(self) -> None:
        self.controller.set_option("ui_scale_percent", 100)
        self.window.show()
        self.application.processEvents()
        base = {
            "conversion_button_width": self.window.conversion_start_button.width(),
            "countdown_width": self.window.countdown_control.width(),
            "time_width": self.window.time_label.width(),
            "slider_pane_width": self.window.slider_pane.width(),
            "track_width": self.window.track_channel_container.width(),
            "tab_height": self.window.tab_bar.height(),
            "folder_column": self.window.midi_table.columnWidth(1),
            "duration_column": self.window.midi_table.columnWidth(2),
        }

        self.controller.set_option("ui_scale_percent", 200)
        self.application.processEvents()
        scaled = {
            "conversion_button_width": self.window.conversion_start_button.width(),
            "countdown_width": self.window.countdown_control.width(),
            "time_width": self.window.time_label.width(),
            "slider_pane_width": self.window.slider_pane.width(),
            "track_width": self.window.track_channel_container.width(),
            "tab_height": self.window.tab_bar.height(),
            "folder_column": self.window.midi_table.columnWidth(1),
            "duration_column": self.window.midi_table.columnWidth(2),
        }

        font_dependent_dimensions = {"slider_pane_width"}
        for name, value in base.items():
            with self.subTest(dimension=name):
                if name in font_dependent_dimensions:
                    self.assertGreaterEqual(scaled[name], value * 1.85)
                    self.assertLessEqual(scaled[name], value * 2.05)
                else:
                    self.assertAlmostEqual(scaled[name], value * 2, delta=2)

    def test_shortcut_inputs_stay_compact_at_large_scale(self) -> None:
        self.controller.set_option("ui_scale_percent", 200)
        self.window.show()
        self.application.processEvents()

        for edit in (
            self.window.shortcut_start_edit,
            self.window.shortcut_pause_edit,
            self.window.shortcut_end_edit,
        ):
            with self.subTest(edit=edit.text()):
                self.assertLessEqual(edit.width(), 100)
                self.assertGreater(
                    edit.width(),
                    edit.fontMetrics().horizontalAdvance(edit.text()),
                )
        self.assertLess(
            self.window.key_controls_frame.geometry().right(),
            self.window.key_panel.width(),
        )

    def test_about_dialog_width_follows_ui_scale(self) -> None:
        self.controller.set_option("ui_scale_percent", 200)
        dialogs: list[QDialog] = []

        with patch.object(QDialog, "exec", new=lambda dialog: dialogs.append(dialog) or 0):
            self.window._open_about()

        self.assertEqual(dialogs[0].width(), 720)


if __name__ == "__main__":
    unittest.main()
