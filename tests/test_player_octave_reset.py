from __future__ import annotations

import unittest
from unittest.mock import patch

from midi_parser import MidiEvent
from player import MidiKeyboardPlayer


class FakeOutput:
    def __init__(self):
        self.events: list[tuple[str, str]] = []

    def press(self, key: str) -> None:
        self.events.append(("press", key))

    def release(self, key: str) -> None:
        self.events.append(("release", key))

    def tap(self, key: str) -> None:
        self.events.append(("tap", key))

    def release_all(self) -> None:
        self.events.append(("release_all", ""))


class PlayerOctaveResetTests(unittest.TestCase):
    def test_keyboard_player_resets_external_octave_before_playing(self) -> None:
        output = FakeOutput()
        player = MidiKeyboardPlayer(output)

        player._reset_external_octave_to_base()

        self.assertEqual(output.events, [("tap", "<"), ("tap", "<"), ("tap", ">")])

    def test_keyboard_player_skips_startup_reset_when_auto_fit_is_enabled(self) -> None:
        output = FakeOutput()
        player = MidiKeyboardPlayer(output, auto_fit_note_range=True)

        player._reset_external_octave_to_base_if_needed()

        self.assertEqual(output.events, [])

    def test_keyboard_player_returns_octave_shift_to_base(self) -> None:
        output = FakeOutput()
        player = MidiKeyboardPlayer(output)

        player._handle_event(MidiEvent(time=0.0, kind="note_on", channel=0, note=21, velocity=100))
        player._move_to_octave_shift(0)

        self.assertIn(("tap", "<"), output.events)
        self.assertIn(("tap", ">"), output.events)

    def test_keyboard_player_resets_external_octave_before_countdown(self) -> None:
        output = FakeOutput()
        states: list[str] = []
        player = MidiKeyboardPlayer(output, on_state=states.append)

        with patch("player.time.sleep", side_effect=lambda _seconds: player.stop()):
            player._run([], countdown_seconds=1, start_time=0.0, on_countdown_tick=None)

        self.assertEqual(output.events[:3], [("tap", "<"), ("tap", "<"), ("tap", ">")])
        self.assertNotIn("playing in 1", states)


if __name__ == "__main__":
    unittest.main()
