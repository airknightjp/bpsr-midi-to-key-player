from __future__ import annotations

import inspect
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QHeaderView

import qt_main_window
from app_controller import AppController
from app_state import TrackChannelItem
from qt_main_window import MidiMainWindow
from qt_components import ThemedBackground
from qt_styles import THEMES, build_stylesheet
from settings import AppSettings


class QtUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.save_settings_patch = patch("app_controller.save_settings")
        self.save_settings_patch.start()
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
        self.assertNotIn("save_settings", source)

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
                self.assertEqual(self.window.countdown_spin.width(), 70)

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

    def test_realtime_start_button_is_disabled_during_key_playback(self) -> None:
        self.controller.state.current_mode = "keys"
        self.controller._notify()

        self.assertFalse(self.window.realtime_button.isEnabled())

        self.controller.state.current_mode = "midi_input"
        self.controller.state.midi_input_running = True
        self.controller._notify()

        self.assertTrue(self.window.realtime_button.isEnabled())

    def test_realtime_start_button_stays_enabled_during_midi_sound_playback(self) -> None:
        self.controller.state.current_mode = "sound"
        self.controller._notify()

        self.assertTrue(self.window.realtime_button.isEnabled())

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

    def test_track_channel_header_and_rows_use_compact_notation(self) -> None:
        self.controller.state.track_channels = [TrackChannelItem(0, 0), TrackChannelItem(1, 2)]
        self.controller._notify()

        self.assertEqual(self.window.track_channels.horizontalHeaderItem(0).text(), "TC")
        self.assertEqual(self.window.track_channels.item(0, 0).text(), "11")
        self.assertEqual(self.window.track_channels.item(1, 0).text(), "23")
        self.assertEqual(self.window.track_channels.font().pixelSize(), 11)
        track_header_rule = self.window.styleSheet().split(
            "QTableWidget#TrackChannelTable QHeaderView::section",
            1,
        )[1].split("}", 1)[0]
        self.assertIn("padding: 4px 1px", track_header_rule)

    def test_track_channel_header_cannot_be_hidden_by_dragging(self) -> None:
        self.window.show()
        self.application.processEvents()
        table = self.window.track_channels
        header = table.horizontalHeader()
        original_width = header.sectionSize(0)

        QTest.mousePress(
            header.viewport(),
            Qt.MouseButton.LeftButton,
            pos=QPoint(header.viewport().width() - 1, header.height() // 2),
        )
        QTest.mouseMove(header.viewport(), QPoint(1, header.height() // 2), delay=20)
        QTest.mouseRelease(
            header.viewport(),
            Qt.MouseButton.LeftButton,
            pos=QPoint(1, header.height() // 2),
        )
        self.application.processEvents()

        self.assertEqual(header.sectionResizeMode(0), QHeaderView.ResizeMode.Fixed)
        self.assertFalse(header.sectionsMovable())
        self.assertEqual(header.sectionSize(0), original_width)
        self.assertFalse(header.isSectionHidden(0))
        self.assertEqual(table.horizontalHeaderItem(0).text(), "TC")

    def test_track_channel_bottom_corners_align_with_midi_table(self) -> None:
        self.assertIn("border-bottom-left-radius: 4px", self.window.styleSheet())
        self.assertIn("border-bottom-right-radius: 4px", self.window.styleSheet())
        self.assertIn(
            f"border-bottom-color: {THEMES['sky_blue'].surface}",
            self.window.styleSheet(),
        )
        self.assertIn("border-top-left-radius: 3px", self.window.styleSheet())
        self.assertIn("border-top-right-radius: 3px", self.window.styleSheet())

    def test_double_clicking_track_channel_header_enables_every_source(self) -> None:
        self.controller.state.track_channels = [
            TrackChannelItem(0, 0, False),
            TrackChannelItem(1, 2, True),
        ]
        self.controller._set_enabled_sources(((1, 2),))
        self.controller._notify()
        self.window.show()
        self.application.processEvents()

        header = self.window.track_channels.horizontalHeader().viewport()
        QTest.mouseDClick(
            header,
            Qt.MouseButton.LeftButton,
            pos=QPoint(header.width() // 2, header.height() // 2),
        )

        self.assertTrue(all(item.enabled for item in self.controller.state.track_channels))
        self.assertEqual(self.controller.enabled_sources(), {(0, 0), (1, 2)})

    def test_scale_changes_stylesheet_and_keeps_sections_visible(self) -> None:
        self.window.resize(self.window.minimumSizeHint().expandedTo(self.window.size()))
        self.window.show()
        self.application.processEvents()
        original = self.window.styleSheet()
        original_width = self.window.width()
        original_margin = self.window.root_layout.contentsMargins().left()
        original_track_width = self.window.track_channels.width()
        original_sections = {
            "realtime": self.window.realtime_panel.geometry().getRect(),
            "key": self.window.key_panel.geometry().getRect(),
            "settings": self.window.settings_panel.geometry().getRect(),
            "player": self.window.player_panel.geometry().getRect(),
        }

        self.controller.set_option("ui_scale_percent", 150)
        self.application.processEvents()

        self.assertNotEqual(self.window.styleSheet(), original)
        self.assertAlmostEqual(self.window.width() / original_width, 1.5, delta=0.03)
        self.assertEqual(self.window.root_layout.contentsMargins().left(), round(original_margin * 1.5))
        self.assertEqual(self.window.track_channels.width(), round(original_track_width * 1.5))
        self.assertEqual(self.controller.state.window_width, self.window.width())
        self.assertEqual(self.controller.state.window_height, self.window.height())
        for name, original_rect in original_sections.items():
            scaled_rect = getattr(self.window, f"{name}_panel").geometry().getRect()
            for original_value, scaled_value in zip(original_rect, scaled_rect):
                self.assertAlmostEqual(scaled_value / original_value, 1.5, delta=0.02)
        self.assertTrue(self.window.realtime_panel.isVisibleTo(self.window))
        self.assertTrue(self.window.player_panel.isVisibleTo(self.window))

    def test_player_layout_matches_legacy_order_and_spacing(self) -> None:
        self.window.show()
        self.application.processEvents()

        self.assertLess(self.window.status_label.geometry().top(), self.window.position_slider.geometry().top())
        self.assertEqual(self.window.player_body_gap.height(), 12)
        self.assertEqual(self.window.slider_track_gap.width(), 6)
        self.assertEqual(self.window.player_detail_gap.width(), 2)
        self.assertEqual(self.window.track_channels.width(), 28)
        self.assertEqual(self.window.volume_control.label.text(), "V\nO\nL")
        self.assertEqual(self.window.speed_control.label.text(), "S\nP\nD")

    def test_section_visibility_hides_complete_panel(self) -> None:
        self.window.resize(self.window.width(), 700)
        self.window.show()
        self.application.processEvents()
        initial_height = self.window.height()
        initial_player_top = self.window.player_panel.geometry().top()

        self.controller.set_section_visible("common_settings", False)
        self.application.processEvents()

        self.assertTrue(self.window.settings_panel.isHidden())
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

        for section in ("midi_input", "key_playback", "common_settings", "player"):
            with self.subTest(section=section):
                visible_height = self.window.height()
                self.controller.set_section_visible(section, False)
                self.application.processEvents()
                self.assertLess(self.window.height(), visible_height)

                self.controller.set_section_visible(section, True)
                self.application.processEvents()
                self.assertEqual(self.window.height(), visible_height)

    def test_hiding_player_section_compacts_to_current_minimum_height(self) -> None:
        self.window.resize(self.window.width(), 700)
        self.window.show()
        self.application.processEvents()

        self.controller.set_section_visible("player", False)
        self.application.processEvents()

        self.assertTrue(self.window.player_panel.isHidden())
        self.assertEqual(self.window.minimumSize().height(), self.window.minimumSizeHint().height())
        self.assertEqual(self.window.height(), self.window.minimumSizeHint().height())

    def test_value_labels_reset_speed_and_volume_to_100(self) -> None:
        self.controller.set_option("playback_speed_percent", 170)
        QTest.mouseDClick(self.window.speed_control.label, Qt.MouseButton.LeftButton)

        self.assertEqual(self.controller.state.playback_speed_percent, 100)
        self.controller.set_option("midi_sound_volume", 40)
        QTest.mouseDClick(self.window.volume_control.label, Qt.MouseButton.LeftButton)
        self.assertEqual(self.controller.state.midi_sound_volume, 100)

    def test_double_clicking_speed_bar_does_not_reset_to_100(self) -> None:
        self.controller.set_option("playback_speed_percent", 170)
        slider = self.window.speed_control.slider

        QTest.mouseDClick(
            slider,
            Qt.MouseButton.LeftButton,
            pos=QPoint(slider.width() // 2, 1),
        )

        self.assertNotEqual(self.controller.state.playback_speed_percent, 100)

    def test_double_clicking_midi_list_tab_reloads_folder(self) -> None:
        calls = []
        self.controller.reload_midi_folder = lambda: calls.append(True)

        self.window.tab_bar.tabBarDoubleClicked.emit(0)
        self.window.tab_bar.tabBarDoubleClicked.emit(1)

        self.assertEqual(calls, [True])

    def test_midi_list_tab_has_reload_icon_and_aligns_with_track_header(self) -> None:
        self.window.show()
        self.application.processEvents()

        self.assertFalse(self.window.tab_bar.tabIcon(0).isNull())
        tab_top = self.window.tab_bar.mapTo(self.window, QPoint(0, 0)).y()
        track_top = self.window.track_channels.mapTo(
            self.window,
            QPoint(0, 0),
        ).y()
        self.assertEqual(tab_top, track_top)
        self.assertEqual(
            self.window.tab_bar.height() - 1,
            self.window.track_channels.horizontalHeader().height(),
        )
        tab_bottom = self.window.tab_bar.mapTo(
            self.window,
            QPoint(0, self.window.tab_bar.height() - 1),
        ).y()
        track_header = self.window.track_channels.horizontalHeader()
        track_bottom = track_header.mapTo(
            self.window,
            QPoint(0, track_header.height() - 1),
        ).y()
        self.assertEqual(
            tab_bottom,
            track_bottom,
        )

    def test_transpose_and_octave_labels_move_with_their_input_boxes(self) -> None:
        self.window.show()
        self.application.processEvents()

        controls_top = self.window.transform_controls.mapTo(self.window, QPoint(0, 0)).y()
        tab_top = self.window.tab_bar.mapTo(self.window, QPoint(0, 0)).y()
        transpose_label_top = self.window.transpose_label.mapTo(self.window, QPoint(0, 0)).y()
        transpose_top = self.window.transpose_spin.mapTo(self.window, QPoint(0, 0)).y()
        octave_label_top = self.window.octave_label.mapTo(self.window, QPoint(0, 0)).y()
        octave_top = self.window.octave_spin.mapTo(self.window, QPoint(0, 0)).y()
        self.assertEqual(transpose_label_top, controls_top)
        self.assertEqual(transpose_top, controls_top)
        self.assertEqual(octave_label_top, controls_top)
        self.assertEqual(octave_top, controls_top)
        self.assertEqual(transpose_top, tab_top - 1)
        self.assertLessEqual(
            abs(
                self.window.transpose_label.geometry().center().y()
                - self.window.transpose_spin.geometry().center().y()
            ),
            1,
        )
        self.assertLessEqual(
            abs(
                self.window.octave_label.geometry().center().y()
                - self.window.octave_spin.geometry().center().y()
            ),
            1,
        )
        self.assertEqual(
            self.window.octave_label.geometry().left()
            - self.window.transpose_spin.geometry().right()
            - 1,
            12,
        )
        self.assertEqual(
            self.window.transpose_spin.geometry().left()
            - self.window.transpose_label.geometry().right()
            - 1,
            4,
        )
        self.assertEqual(
            self.window.octave_spin.geometry().left()
            - self.window.octave_label.geometry().right()
            - 1,
            4,
        )
        self.assertEqual(
            self.window.transform_controls.geometry().left()
            - self.window.tab_bar.geometry().right()
            - 1,
            8,
        )

    def test_transform_spin_boxes_scale_with_their_step_buttons(self) -> None:
        self.controller.set_option("ui_scale_percent", 100)
        self.window.show()
        self.application.processEvents()
        transpose_edit_width = self.window.transpose_spin.lineEdit().width()
        octave_edit_width = self.window.octave_spin.lineEdit().width()

        self.controller.set_option("ui_scale_percent", 200)
        self.application.processEvents()

        self.assertEqual(self.window.transpose_spin.width(), 140)
        self.assertEqual(self.window.octave_spin.width(), 132)
        self.assertGreaterEqual(self.window.transpose_spin.lineEdit().width(), transpose_edit_width * 2)
        self.assertGreaterEqual(self.window.octave_spin.lineEdit().width(), octave_edit_width * 2)

    def test_midi_header_and_rows_have_more_vertical_room(self) -> None:
        self.window.show()
        self.application.processEvents()

        self.assertEqual(self.window.midi_table.horizontalHeader().height(), 24)

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

    def test_playback_position_uses_compact_time_label(self) -> None:
        self.window.show()
        self.application.processEvents()

        self.assertEqual(self.window.time_label.width(), 80)
        self.assertGreater(self.window.position_slider.width(), 690)
        self.assertLessEqual(
            self.window.time_label.fontMetrics().horizontalAdvance("00:00 / 00:00"),
            self.window.time_label.width(),
        )

    def test_double_clicking_playback_position_returns_to_start(self) -> None:
        self.controller.state.duration = 120.0
        self.controller.state.position = 75.0
        self.controller._notify()
        self.window.show()
        self.application.processEvents()

        QTest.mouseDClick(self.window.position_label, Qt.MouseButton.LeftButton)

        self.assertEqual(self.controller.state.position, 0.0)
        self.assertEqual(self.window.position_slider.value(), 0)

    def test_clicking_vertical_sliders_jumps_to_clicked_value(self) -> None:
        self.window.show()
        self.application.processEvents()

        QTest.mouseClick(
            self.window.volume_control.slider,
            Qt.MouseButton.LeftButton,
            pos=QPoint(
                self.window.volume_control.slider.width() // 2,
                self.window.volume_control.slider.height() // 4,
            ),
        )
        QTest.mouseClick(
            self.window.speed_control.slider,
            Qt.MouseButton.LeftButton,
            pos=QPoint(
                self.window.speed_control.slider.width() // 2,
                self.window.speed_control.slider.height() * 3 // 4,
            ),
        )

        self.assertAlmostEqual(self.controller.state.midi_sound_volume, 75, delta=2)
        self.assertAlmostEqual(self.controller.state.playback_speed_percent, 58, delta=3)

    def test_status_remains_english_in_all_languages(self) -> None:
        for language in ("en", "ja", "zh"):
            self.controller.set_option("language", language)
            self.controller.state.status = "sound playing"
            self.controller._notify()
            self.assertEqual(self.window.status_label.text(), "sound playing")

    def test_track_channel_colors_reflect_enabled_state_on_first_render(self) -> None:
        self.controller.state.track_channels = [
            TrackChannelItem(0, 0, True),
            TrackChannelItem(0, 1, False),
        ]
        self.controller._notify()
        palette = THEMES[self.controller.state.color_theme]

        self.assertEqual(self.window.track_channels.item(0, 0).background().color().name(), palette.accent)
        self.assertEqual(self.window.track_channels.item(1, 0).background().color().name(), palette.canvas)

    def test_view_section_actions_are_direct_menu_items(self) -> None:
        view_action = next(
            action for action in self.window.menuBar().actions() if action.text() == "View"
        )
        view_menu = view_action.menu()
        direct_actions = {action.text(): action for action in view_menu.actions()}

        for label in ("Realtime Input Conversion", "MIDI Input Conversion", "Advanced Settings", "Player"):
            self.assertIn(label, direct_actions)
            self.assertIsNone(direct_actions[label].menu())

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

    def test_common_and_performance_items_share_the_same_indent(self) -> None:
        common_items = (self.window.dry_run_check, self.window.auto_fit_check, self.window.repeat_check)
        performance_items = (
            self.window.humanize_check,
            self.window.strum_check,
            self.window.optimization_check,
        )

        self.assertTrue(all(item.property("settingsItem") for item in common_items + performance_items))
        self.assertIn('margin-left: 6px', self.window.styleSheet())

    def test_common_and_performance_captions_are_raised_one_pixel(self) -> None:
        self.window.show()
        self.application.processEvents()
        panel_top = self.window.settings_panel.mapTo(self.window, QPoint(0, 0)).y()
        common_top = self.window.common_caption.mapTo(self.window, QPoint(0, 0)).y()
        performance_top = self.window.performance_caption.mapTo(self.window, QPoint(0, 0)).y()

        self.assertEqual(common_top - panel_top, 9)
        self.assertEqual(performance_top, common_top)

    def test_section_title_backgrounds_use_rounded_corners_in_every_theme(self) -> None:
        for theme in THEMES:
            with self.subTest(theme=theme):
                self.controller.set_option("color_theme", theme)
                title_rule = self.window.styleSheet().split('QGroupBox[section="true"]::title', 1)[1]
                self.assertIn("border-radius: 4px", title_rule.split("}", 1)[0])

    def test_dark_theme_uses_high_contrast_checked_indicators(self) -> None:
        self.controller.set_option("color_theme", "dark")
        stylesheet = self.window.styleSheet()
        checked_rule = stylesheet.split("QCheckBox::indicator:checked", 1)[1].split("}", 1)[0]

        self.assertIn(f"background: {THEMES['dark'].canvas}", checked_rule)
        self.assertIn(f"border: 1px solid {THEMES['dark'].muted}", checked_rule)
        self.assertIn("check_white.svg", checked_rule)
        self.assertIn("image: url", checked_rule)

        self.controller.set_option("color_theme", "light")
        self.assertNotIn("QCheckBox::indicator:checked", self.window.styleSheet())

    def test_slider_handle_shape_scales_without_becoming_rectangular(self) -> None:
        stylesheet = build_stylesheet("light", 200)
        vertical_rule = stylesheet.split("QSlider::handle:vertical", 1)[1].split("}", 1)[0]
        horizontal_rule = stylesheet.split("QSlider::handle:horizontal", 1)[1].split("}", 1)[0]

        self.assertIn("height: 28px", vertical_rule)
        self.assertIn("margin: 0 -10px", vertical_rule)
        self.assertIn("border-radius: 14px", vertical_rule)
        self.assertIn("width: 28px", horizontal_rule)
        self.assertIn("margin: -10px 0", horizontal_rule)
        self.assertIn("border-radius: 14px", horizontal_rule)

    def test_sky_blue_theme_uses_whale_slider_handles(self) -> None:
        sky_blue_stylesheet = build_stylesheet("sky_blue", 200)
        light_stylesheet = build_stylesheet("light", 200)
        vertical_rule = sky_blue_stylesheet.rsplit("QSlider::handle:vertical", 1)[1].split("}", 1)[0]
        horizontal_rule = sky_blue_stylesheet.rsplit("QSlider::handle:horizontal", 1)[1].split("}", 1)[0]

        self.assertIn("app_icon_whale.png", vertical_rule)
        self.assertIn("app_icon_whale_flipped.png", horizontal_rule)
        self.assertIn("image: url", vertical_rule)
        self.assertIn("image: url", horizontal_rule)
        self.assertIn("width: 32px", vertical_rule)
        self.assertIn("height: 32px", horizontal_rule)
        self.assertNotIn("app_icon_whale.png", light_stylesheet)

    def test_sky_blue_theme_menu_item_uses_whale_icon(self) -> None:
        self.window.show()
        self.application.processEvents()

        sky_blue_action = self.window.theme_actions["sky_blue"]
        light_action = self.window.theme_actions["light"]

        self.assertEqual(sky_blue_action.text(), "Sky Blue")
        self.assertFalse(sky_blue_action.icon().isNull())
        self.assertTrue(light_action.icon().isNull())

    def test_vertical_slider_width_scales_to_keep_handle_visible(self) -> None:
        self.controller.set_option("ui_scale_percent", 200)
        self.window.show()
        self.application.processEvents()

        self.assertGreaterEqual(self.window.volume_control.slider.width(), 44)
        self.assertGreaterEqual(self.window.speed_control.slider.width(), 44)
        self.assertLessEqual(
            self.window.volume_control.slider.width(),
            self.window.volume_control.width(),
        )
        self.assertLessEqual(
            self.window.speed_control.slider.width(),
            self.window.speed_control.width(),
        )

    def test_fixed_layout_dimensions_follow_ui_scale(self) -> None:
        self.controller.set_option("ui_scale_percent", 100)
        self.window.show()
        self.application.processEvents()
        base = {
            "realtime_button_width": self.window.realtime_button.width(),
            "keyboard_button_width": self.window.keyboard_play_button.width(),
            "keyboard_button_height": self.window.keyboard_play_button.height(),
            "countdown_width": self.window.countdown_spin.width(),
            "time_width": self.window.time_label.width(),
            "slider_pane_width": self.window.slider_pane.width(),
            "track_width": self.window.track_channel_container.width(),
            "tab_height": self.window.tab_bar.height(),
            "transpose_width": self.window.transpose_spin.width(),
            "octave_width": self.window.octave_spin.width(),
            "length_column": self.window.midi_table.columnWidth(1),
            "range_column": self.window.midi_table.columnWidth(2),
        }

        self.controller.set_option("ui_scale_percent", 200)
        self.application.processEvents()
        scaled = {
            "realtime_button_width": self.window.realtime_button.width(),
            "keyboard_button_width": self.window.keyboard_play_button.width(),
            "keyboard_button_height": self.window.keyboard_play_button.height(),
            "countdown_width": self.window.countdown_spin.width(),
            "time_width": self.window.time_label.width(),
            "slider_pane_width": self.window.slider_pane.width(),
            "track_width": self.window.track_channel_container.width(),
            "tab_height": self.window.tab_bar.height(),
            "transpose_width": self.window.transpose_spin.width(),
            "octave_width": self.window.octave_spin.width(),
            "length_column": self.window.midi_table.columnWidth(1),
            "range_column": self.window.midi_table.columnWidth(2),
        }

        for name, value in base.items():
            with self.subTest(dimension=name):
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
            self.window.shortcut_group.geometry().right(),
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
