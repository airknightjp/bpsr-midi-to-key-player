from __future__ import annotations

import unittest
from types import SimpleNamespace

from main import App
from global_hotkeys import GlobalHotkeyManager, HotkeySpec, MOD_CONTROL, shortcut_to_hotkey_spec


class ShortcutTests(unittest.TestCase):
    def test_shortcut_from_key_event_detects_modifiers(self) -> None:
        event = SimpleNamespace(keysym="p", state=0x0004)

        self.assertEqual(App._shortcut_from_event(event), "Ctrl+P")

    def test_shortcut_from_key_event_ignores_modifier_only(self) -> None:
        event = SimpleNamespace(keysym="Control_L", state=0x0004)

        self.assertIsNone(App._shortcut_from_event(event))

    def test_shortcut_to_hotkey_spec_supports_function_keys(self) -> None:
        spec = shortcut_to_hotkey_spec("F5", "play")

        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.vk, 0x74)
        self.assertEqual(spec.action, "play")

    def test_shortcut_to_hotkey_spec_supports_ctrl_letters(self) -> None:
        spec = shortcut_to_hotkey_spec("Ctrl+P", "play")

        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.modifiers, MOD_CONTROL)
        self.assertEqual(spec.vk, ord("P"))

    def test_play_shortcut_starts_play_immediately(self) -> None:
        app = object.__new__(App)
        calls: list[str] = []
        app.current_play_mode = None
        app._shortcut_entry_has_focus = lambda: False
        app._midi_input_is_running = lambda: False
        app.play = lambda: calls.append("play")

        result = App._on_keyboard_play_shortcut(app, None)

        self.assertEqual(result, "break")
        self.assertEqual(calls, ["play"])

    def test_global_play_hotkey_works_even_when_shortcut_entry_has_focus(self) -> None:
        app = object.__new__(App)
        calls: list[str] = []
        app.current_play_mode = None
        app._shortcut_entry_has_focus = lambda: True
        app._midi_input_is_running = lambda: False
        app.play = lambda: calls.append("play")

        result = App._on_keyboard_play_shortcut(app, None)

        self.assertEqual(result, "break")
        self.assertEqual(calls, ["play"])

    def test_app_local_play_shortcut_is_ignored_when_shortcut_entry_has_focus(self) -> None:
        app = object.__new__(App)
        calls: list[str] = []
        app.current_play_mode = None
        app._shortcut_entry_has_focus = lambda: True
        app._midi_input_is_running = lambda: False
        app.play = lambda: calls.append("play")

        result = App._on_keyboard_play_shortcut(app, object())

        self.assertIsNone(result)
        self.assertEqual(calls, [])

    def test_shortcut_watchdog_rebinds_when_global_hotkeys_are_unhealthy(self) -> None:
        app = object.__new__(App)
        calls: list[str] = []
        scheduled: list[tuple[int, object]] = []
        app.exiting = False
        app.global_hotkeys = SimpleNamespace(is_healthy=False)
        app._bind_keyboard_shortcuts = lambda: calls.append("bind")
        app.after = lambda delay, callback: scheduled.append((delay, callback))

        App._ensure_keyboard_shortcuts(app)

        self.assertEqual(calls, ["bind"])
        self.assertEqual(scheduled[0][0], 3000)
        self.assertIs(scheduled[0][1].__self__, app)
        self.assertIs(scheduled[0][1].__func__, App._ensure_keyboard_shortcuts)

    def test_shortcut_watchdog_does_not_rebind_when_global_hotkeys_are_healthy(self) -> None:
        app = object.__new__(App)
        calls: list[str] = []
        scheduled: list[tuple[int, object]] = []
        app.exiting = False
        app.global_hotkeys = SimpleNamespace(is_healthy=True)
        app._bind_keyboard_shortcuts = lambda: calls.append("bind")
        app.after = lambda delay, callback: scheduled.append((delay, callback))

        App._ensure_keyboard_shortcuts(app)

        self.assertEqual(calls, [])
        self.assertEqual(scheduled[0][0], 3000)
        self.assertIs(scheduled[0][1].__self__, app)
        self.assertIs(scheduled[0][1].__func__, App._ensure_keyboard_shortcuts)

    def test_partial_global_hotkey_registration_is_unhealthy(self) -> None:
        manager = GlobalHotkeyManager(
            [
                HotkeySpec("play", 0, 0x74),
                HotkeySpec("stop", 0, 0x75),
            ],
            lambda _action: None,
        )
        manager._thread = SimpleNamespace(is_alive=lambda: True)
        manager._registered_count = 1

        self.assertFalse(manager.is_healthy)

    def test_common_navigation_key_is_supported_globally(self) -> None:
        spec = shortcut_to_hotkey_spec("Ctrl+Left", "play")

        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.vk, 0x25)


if __name__ == "__main__":
    unittest.main()
