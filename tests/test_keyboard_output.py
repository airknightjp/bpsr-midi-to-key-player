from __future__ import annotations

import unittest
import threading
from unittest.mock import patch

from keyboard_output import (
    KeyboardOutput,
    TAP_GAP_SECONDS,
    TAP_HOLD_SECONDS,
    foreground_window_belongs_to_current_process,
)


class KeyboardOutputTests(unittest.TestCase):
    def test_foreground_window_from_current_process_is_detected(self) -> None:
        with (
            patch("keyboard_output.ctypes.windll") as windll,
            patch("keyboard_output.os.getpid", return_value=42),
        ):
            windll.user32.GetForegroundWindow.return_value = 100

            def set_process_id(_window, process_id) -> int:
                process_id._obj.value = 42
                return 1

            windll.user32.GetWindowThreadProcessId.side_effect = set_process_id

            self.assertTrue(foreground_window_belongs_to_current_process())

    def test_foreground_window_from_another_process_is_not_detected(self) -> None:
        with (
            patch("keyboard_output.ctypes.windll") as windll,
            patch("keyboard_output.os.getpid", return_value=42),
        ):
            windll.user32.GetForegroundWindow.return_value = 100

            def set_process_id(_window, process_id) -> int:
                process_id._obj.value = 99
                return 1

            windll.user32.GetWindowThreadProcessId.side_effect = set_process_id

            self.assertFalse(foreground_window_belongs_to_current_process())

    def test_dry_run_change_releases_current_mode_before_switching(self) -> None:
        class RecordingKeyboardOutput(KeyboardOutput):
            def __init__(self):
                super().__init__(dry_run=False)
                self.sent: list[tuple[int, bool]] = []

            def _send_scancode(self, scancode: int, key_up: bool) -> None:
                if not self.dry_run:
                    self.sent.append((scancode, key_up))

        output = RecordingKeyboardOutput()

        with (
            patch("keyboard_output.time.sleep"),
            patch(
                "keyboard_output.foreground_window_belongs_to_current_process",
                return_value=False,
            ),
        ):
            output.press("a")
            output.set_dry_run(True)
            output.press("b")
            output.set_dry_run(False)
            output.press("c")

        self.assertEqual(
            output.sent,
            [
                (0x1E, False),
                (0x1E, True),
                (0x2E, False),
            ],
        )
        self.assertEqual(output._pressed, {"c"})

    def test_angle_bracket_keys_are_supported(self) -> None:
        output = KeyboardOutput(dry_run=True)

        output.press("<")
        output.release("<")
        output.press(">")
        output.release(">")

        self.assertEqual(output._pressed, set())

    def test_angle_bracket_keys_are_sent_as_unshifted_comma_and_period_keys(self) -> None:
        class RecordingKeyboardOutput(KeyboardOutput):
            def __init__(self):
                super().__init__(dry_run=False)
                self.sent: list[tuple[int, bool]] = []

            def _send_scancode(self, scancode: int, key_up: bool) -> None:
                self.sent.append((scancode, key_up))

        output = RecordingKeyboardOutput()

        with (
            patch("keyboard_output.time.sleep") as sleep,
            patch(
                "keyboard_output.foreground_window_belongs_to_current_process",
                return_value=False,
            ),
        ):
            output.tap("<")
            output.tap(">")

        self.assertEqual(
            output.sent,
            [
                (0x33, False),
                (0x33, True),
                (0x34, False),
                (0x34, True),
            ],
        )
        self.assertEqual(len(sleep.call_args_list), 4)
        self.assertAlmostEqual(sleep.call_args_list[0].args[0], TAP_HOLD_SECONDS, places=2)
        self.assertAlmostEqual(sleep.call_args_list[1].args[0], TAP_GAP_SECONDS, places=2)
        self.assertAlmostEqual(sleep.call_args_list[2].args[0], TAP_HOLD_SECONDS, places=2)
        self.assertAlmostEqual(sleep.call_args_list[3].args[0], TAP_GAP_SECONDS, places=2)

    def test_repeated_same_key_waits_between_release_and_next_press(self) -> None:
        class RecordingKeyboardOutput(KeyboardOutput):
            def __init__(self):
                super().__init__(dry_run=False)
                self.sent: list[tuple[int, bool]] = []

            def _send_scancode(self, scancode: int, key_up: bool) -> None:
                self.sent.append((scancode, key_up))

        output = RecordingKeyboardOutput()

        with (
            patch("keyboard_output.time.sleep") as sleep,
            patch(
                "keyboard_output.foreground_window_belongs_to_current_process",
                return_value=False,
            ),
        ):
            output.press("b")
            output.release("b")
            output.press("b")

        self.assertEqual(output.sent, [(0x30, False), (0x30, True), (0x30, False)])
        self.assertGreaterEqual(len(sleep.call_args_list), 2)

    def test_key_output_is_suppressed_while_an_app_window_has_focus(self) -> None:
        class RecordingKeyboardOutput(KeyboardOutput):
            def __init__(self):
                super().__init__(dry_run=False)
                self.sent: list[tuple[int, bool]] = []

            def _send_scancode(self, scancode: int, key_up: bool) -> None:
                self.sent.append((scancode, key_up))

        output = RecordingKeyboardOutput()

        with (
            patch("keyboard_output.time.sleep"),
            patch(
                "keyboard_output.foreground_window_belongs_to_current_process",
                return_value=True,
            ),
        ):
            output.press("a")
            output.release("a")

        self.assertEqual(output.sent, [])
        self.assertEqual(output._pressed, set())
        self.assertEqual(output._suppressed, set())

    def test_key_output_is_sent_while_another_app_has_focus(self) -> None:
        class RecordingKeyboardOutput(KeyboardOutput):
            def __init__(self):
                super().__init__(dry_run=False)
                self.sent: list[tuple[int, bool]] = []

            def _send_scancode(self, scancode: int, key_up: bool) -> None:
                self.sent.append((scancode, key_up))

        output = RecordingKeyboardOutput()

        with (
            patch("keyboard_output.time.sleep"),
            patch(
                "keyboard_output.foreground_window_belongs_to_current_process",
                return_value=False,
            ),
        ):
            output.press("a")
            output.release("a")

        self.assertEqual(output.sent, [(0x1E, False), (0x1E, True)])

    def test_concurrent_release_of_same_key_is_safe(self) -> None:
        class CoordinatedOutput(KeyboardOutput):
            def __init__(self):
                super().__init__(dry_run=True)
                self.entered = threading.Event()

            def _wait_for_minimum_hold(self, key: str) -> None:
                self.entered.set()

        output = CoordinatedOutput()
        output.press("a")
        errors: list[Exception] = []

        def release() -> None:
            try:
                output.release("a")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=release) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(output._pressed, set())


if __name__ == "__main__":
    unittest.main()
