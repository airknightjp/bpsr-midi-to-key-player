from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from legacy_tk_main import App


class FakeButton:
    def __init__(self):
        self.config: dict[str, str] = {}

    def configure(self, **kwargs: str) -> None:
        self.config.update(kwargs)


class FakeSelect(FakeButton):
    pass


class FakeStringVar:
    def __init__(self):
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value


class FakeSoundPlayer:
    def __init__(self):
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True

    def wait_until_stopped(self, timeout: float = 1.0) -> None:
        pass


class ButtonStateTests(unittest.TestCase):
    def make_app(self, mode: str | None) -> App:
        app = object.__new__(App)
        app.current_play_mode = mode
        app.play_button = FakeButton()
        app.sound_button = FakeButton()
        app._text = lambda key: key
        return app

    def test_keyboard_mode_turns_keyboard_button_into_stop(self) -> None:
        app = self.make_app("keys")

        App._refresh_playback_buttons(app)

        self.assertEqual(app.play_button.config["text"], "stop_keys")
        self.assertEqual(app.play_button.config["state"], "normal")
        self.assertEqual(app.play_button.config["style"], "ActiveAction.TButton")
        self.assertEqual(app.sound_button.config["state"], "disabled")
        self.assertEqual(app.sound_button.config["text"], "play_midi_sound")
        self.assertEqual(app.sound_button.config["image"], "")
        self.assertEqual(app.sound_button.config["style"], "DisabledAction.TButton")

    def test_midi_mode_turns_keyboard_button_into_disabled(self) -> None:
        app = self.make_app("sound")

        App._refresh_playback_buttons(app)

        self.assertEqual(app.sound_button.config["text"], "stop_midi")
        self.assertEqual(app.sound_button.config["state"], "normal")
        self.assertEqual(app.sound_button.config["style"], "ActiveAction.TButton")
        self.assertEqual(app.play_button.config["text"], "play_keys")
        self.assertEqual(app.play_button.config["image"], "")
        self.assertEqual(app.play_button.config["state"], "disabled")
        self.assertEqual(app.play_button.config["style"], "DisabledAction.TButton")

    def test_midi_input_mode_turns_keyboard_button_into_disabled(self) -> None:
        app = self.make_app(None)
        app.midi_input_bridge = type("Bridge", (), {"is_running": True})()

        App._refresh_playback_buttons(app)

        self.assertEqual(app.play_button.config["text"], "play_keys")
        self.assertEqual(app.play_button.config["image"], "")
        self.assertEqual(app.play_button.config["state"], "disabled")
        self.assertEqual(app.play_button.config["style"], "DisabledAction.TButton")

    def test_keyboard_mode_turns_midi_input_button_into_disabled(self) -> None:
        app = object.__new__(App)
        app.current_play_mode = "keys"
        app.midi_input_button = FakeButton()
        app.midi_input_select = FakeSelect()
        app.midi_input_bridge = None
        app._text = lambda key: key

        App._refresh_midi_input_button(app)

        self.assertEqual(app.midi_input_button.config["text"], "start_midi_input")
        self.assertEqual(app.midi_input_button.config["image"], "")
        self.assertEqual(app.midi_input_button.config["state"], "disabled")
        self.assertEqual(app.midi_input_button.config["style"], "DisabledAction.TButton")

    def test_midi_sound_mode_keeps_midi_input_button_enabled(self) -> None:
        app = object.__new__(App)
        app.current_play_mode = "sound"
        app.midi_input_button = FakeButton()
        app.midi_input_select = FakeSelect()
        app.midi_input_bridge = None
        app._text = lambda key: key

        App._refresh_midi_input_button(app)

        self.assertEqual(app.midi_input_button.config["text"], "start_midi_input")
        self.assertEqual(app.midi_input_button.config["state"], "normal")
        self.assertEqual(app.midi_input_button.config["style"], "TButton")
        self.assertEqual(app.midi_input_button.config["image"], "")

    def test_running_midi_input_keeps_pressed_button_color(self) -> None:
        app = object.__new__(App)
        app.current_play_mode = None
        app.midi_input_button = FakeButton()
        app.midi_input_select = FakeSelect()
        app.midi_input_bridge = type("Bridge", (), {"is_running": True})()
        app._text = lambda key: key

        App._refresh_midi_input_button(app)

        self.assertEqual(app.midi_input_button.config["text"], "stop_midi_input")
        self.assertEqual(app.midi_input_button.config["state"], "normal")
        self.assertEqual(app.midi_input_button.config["style"], "ActiveAction.TButton")
        self.assertEqual(app.midi_input_button.config["image"], "")

    def test_keyboard_mode_keeps_humanize_option_enabled(self) -> None:
        app = object.__new__(App)
        app.current_play_mode = "keys"
        app.midi_input_bridge = None
        app.dry_run_check = FakeButton()
        app.countdown_spinbox = FakeButton()
        app.countdown_sound_check = FakeButton()
        app.humanize_timing_check = FakeButton()

        App._refresh_option_states(app)

        self.assertEqual(app.dry_run_check.config["state"], "disabled")
        self.assertEqual(app.countdown_spinbox.config["state"], "disabled")
        self.assertEqual(app.countdown_sound_check.config["state"], "disabled")
        self.assertEqual(app.humanize_timing_check.config["state"], "normal")

    def test_midi_input_mode_disables_dry_run_only(self) -> None:
        app = object.__new__(App)
        app.current_play_mode = None
        app.midi_input_bridge = type("Bridge", (), {"is_running": True})()
        app.dry_run_check = FakeButton()
        app.countdown_spinbox = FakeButton()
        app.countdown_sound_check = FakeButton()
        app.humanize_timing_check = FakeButton()

        App._refresh_option_states(app)

        self.assertEqual(app.dry_run_check.config["state"], "disabled")
        self.assertEqual(app.countdown_spinbox.config["state"], "normal")
        self.assertEqual(app.countdown_sound_check.config["state"], "normal")
        self.assertEqual(app.humanize_timing_check.config["state"], "normal")

    def test_midi_sound_mode_keeps_humanize_option_enabled(self) -> None:
        app = object.__new__(App)
        app.current_play_mode = "sound"
        app.midi_input_bridge = None
        app.dry_run_check = FakeButton()
        app.countdown_spinbox = FakeButton()
        app.countdown_sound_check = FakeButton()
        app.humanize_timing_check = FakeButton()

        App._refresh_option_states(app)

        self.assertEqual(app.humanize_timing_check.config["state"], "normal")

    def test_stopping_midi_sound_updates_state_immediately(self) -> None:
        app = object.__new__(App)
        app.current_play_mode = "sound"
        app.playback_id = 0
        app.player = None
        app.sound_player = FakeSoundPlayer()
        app.seeking_keys = False
        app.state_var = FakeStringVar()
        logs: list[str] = []
        app._next_playback_id = lambda: 1
        app._log = logs.append
        app._text = lambda key: {
            "sound_playback_stopped": "MIDI sound playback stopped",
        }.get(key, key)
        app._refresh_playback_buttons = lambda: None
        app._refresh_midi_input_button = lambda: None
        app._refresh_option_states = lambda: None
        app._set_position = lambda _position: None

        App.stop(app)

        self.assertEqual(app.state_var.value, "sound stopped")
        self.assertEqual(logs, ["MIDI sound playback stopped"])


class ReloadTabTests(unittest.TestCase):
    def test_view_menu_places_scale_before_opacity(self) -> None:
        source = inspect.getsource(App._build_menu_bar)
        scale_entry = 'view_menu.add_cascade(label=self._text("ui_scale")'
        opacity_entry = 'view_menu.add_cascade(label=self._text("window_opacity")'

        self.assertLess(source.index(scale_entry), source.index(opacity_entry))

    def test_scale_and_opacity_menus_rely_on_variable_traces_only(self) -> None:
        source = inspect.getsource(App._build_menu_bar)
        opacity_block = source[source.index("for opacity in"):source.index("scale_menu =")]
        scale_block = source[source.index("for percent in"):source.index("view_menu =")]

        self.assertNotIn("command=", opacity_block)
        self.assertNotIn("command=", scale_block)

    def test_text_refresh_keeps_midi_device_refresh_button_as_an_icon(self) -> None:
        self.assertNotIn(
            "refresh_midi_inputs_button.configure",
            inspect.getsource(App._refresh_text),
        )

    def test_text_refresh_has_no_reference_to_removed_reload_button(self) -> None:
        self.assertNotIn("reload_button", inspect.getsource(App._refresh_text))

    def test_reload_button_restores_color_without_a_timer(self) -> None:
        app = object.__new__(App)
        app.reload_tab_button = FakeButton()
        app._theme_palette = lambda: {
            "panel": "panel",
            "select": "select",
            "fg": "foreground",
        }
        rendered_colors: list[str] = []
        colors_during_reload: list[str] = []
        app.update_idletasks = lambda: rendered_colors.append(
            app.reload_tab_button.config["background"]
        )
        app.reload_midi_folder = lambda: colors_during_reload.append(
            app.reload_tab_button.config["background"]
        )

        result = App._on_reload_tab_button(app)

        self.assertEqual(result, "break")
        self.assertEqual(rendered_colors, ["select"])
        self.assertEqual(colors_during_reload, ["select"])
        self.assertEqual(app.reload_tab_button.config["background"], "panel")
        self.assertEqual(app.reload_tab_button.config["foreground"], "foreground")
        self.assertNotIn("reload_button_restore_after_id", app.__dict__)


class MidiScrollbarTests(unittest.TestCase):
    def test_ui_layout_does_not_use_place_geometry_manager(self) -> None:
        self.assertNotIn(".place(", inspect.getsource(App))

    def test_channel_refresh_does_not_rebuild_fixed_header(self) -> None:
        self.assertNotIn("_add_channel_grid_header", inspect.getsource(App._set_channels))

    def test_midi_tree_row_height_scales_and_fits_the_font(self) -> None:
        app = object.__new__(App)
        app._scaled_dimension = lambda value: value * 2
        font = type("Font", (), {"metrics": lambda self, _name: 45})()

        with patch("legacy_tk_main.tkfont.nametofont", return_value=font):
            row_height = App._midi_tree_row_height(app)

        self.assertEqual(row_height, 53)

    def test_window_configure_remembers_width_and_height(self) -> None:
        app = object.__new__(App)
        app.saved_window_width = 900
        app.saved_window_height = 560
        app.state = lambda: "normal"
        app._visible_section_min_height = lambda: 1
        event = type("Event", (), {"widget": app, "width": 1440, "height": 900})()

        App._on_window_configure(app, event)

        self.assertEqual(app.saved_window_width, 1440)
        self.assertEqual(app.saved_window_height, 900)


if __name__ == "__main__":
    unittest.main()
