from __future__ import annotations

import inspect
import unittest

from main import App


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


class FakeTabs:
    def __init__(self, clicked_index: int, reload_index: int = 0):
        self.clicked_index = clicked_index
        self.reload_index = reload_index

    def index(self, tab: object) -> int:
        if isinstance(tab, str) and tab.startswith("@"):
            return self.clicked_index
        return self.reload_index


class FakePointerEvent:
    x = 24
    y = 8


class FakeMidiTree:
    def winfo_exists(self) -> bool:
        return True

    def winfo_height(self) -> int:
        return 100

    def identify_region(self, _x: int, y: int) -> str:
        if 2 <= y < 22:
            return "heading"
        return "tree" if y >= 22 else "nothing"


class FakePlacedScrollbar:
    def __init__(self):
        self.place_config: dict[str, object] = {}
        self.lifted = False
        self.place_count = 0

    def place(self, **kwargs: object) -> None:
        self.place_config = kwargs
        self.place_count += 1

    def lift(self) -> None:
        self.lifted = True


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
    def test_text_refresh_has_no_reference_to_removed_reload_button(self) -> None:
        self.assertNotIn("reload_button", inspect.getsource(App._refresh_text))

    def test_clicking_reload_tab_reloads_without_selecting_empty_tab(self) -> None:
        app = object.__new__(App)
        app.reload_tab = "reload"
        app.detail_tabs = FakeTabs(clicked_index=0)
        reloaded: list[bool] = []
        app.reload_midi_folder = lambda: reloaded.append(True)

        result = App._on_detail_tab_pointer(app, FakePointerEvent())

        self.assertEqual(reloaded, [True])
        self.assertEqual(result, "break")

    def test_clicking_regular_tab_does_not_reload(self) -> None:
        app = object.__new__(App)
        app.reload_tab = "reload"
        app.detail_tabs = FakeTabs(clicked_index=1)
        reloaded: list[bool] = []
        app.reload_midi_folder = lambda: reloaded.append(True)

        result = App._on_detail_tab_pointer(app, FakePointerEvent())

        self.assertEqual(reloaded, [])
        self.assertIsNone(result)


class MidiScrollbarTests(unittest.TestCase):
    def test_scrollbar_starts_below_column_headings(self) -> None:
        app = object.__new__(App)
        app.midi_tree = FakeMidiTree()
        app.midi_scrollbar = FakePlacedScrollbar()

        App._align_midi_scrollbar(app)

        self.assertEqual(
            app.midi_scrollbar.place_config,
            {
                "relx": 1.0,
                "x": 0,
                "y": 22,
                "anchor": "ne",
                "relheight": 1.0,
                "height": -22,
            },
        )
        self.assertTrue(app.midi_scrollbar.lifted)

        App._align_midi_scrollbar(app)

        self.assertEqual(app.midi_scrollbar.place_count, 1)


if __name__ == "__main__":
    unittest.main()
