from __future__ import annotations

import unittest
from unittest.mock import patch

from live_midi_input import MIM_DATA, MidiInputKeyboardBridge


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


class LiveMidiInputTests(unittest.TestCase):
    @staticmethod
    def _running_bridge(output: FakeOutput, **kwargs) -> MidiInputKeyboardBridge:
        bridge = MidiInputKeyboardBridge(device_id=0, output=output, **kwargs)
        bridge._running = True
        return bridge

    def test_note_on_and_off_are_converted_to_keyboard_output(self) -> None:
        output = FakeOutput()
        bridge = self._running_bridge(output)

        bridge._note_on(channel=0, note=60, velocity=100)
        bridge._note_off(channel=0, note=60)

        self.assertEqual(output.events, [("press", "a"), ("release", "a")])

    def test_custom_key_binding_is_used_for_realtime_input(self) -> None:
        output = FakeOutput()
        bridge = self._running_bridge(output, key_bindings={60: "q"})

        bridge._note_on(channel=0, note=60, velocity=100)
        bridge._note_off(channel=0, note=60)

        self.assertEqual(output.events, [("press", "q"), ("release", "q")])

    def test_transpose_and_octave_shift_are_applied_to_realtime_input(self) -> None:
        output = FakeOutput()
        bridge = self._running_bridge(
            output,
            transpose_semitones=2,
            octave_shift=1,
        )

        bridge._note_on(channel=0, note=48, velocity=100)
        bridge._note_off(channel=0, note=48)

        self.assertEqual(output.events, [("press", "s"), ("release", "s")])

    def test_changing_note_shift_releases_active_realtime_keys(self) -> None:
        output = FakeOutput()
        bridge = self._running_bridge(output)
        bridge._note_on(channel=0, note=60, velocity=100)

        bridge.set_note_shift(transpose_semitones=1, octave_shift=0)

        self.assertEqual(
            output.events,
            [("press", "a"), ("release", "a"), ("release_all", "")],
        )

    def test_out_of_range_note_is_skipped(self) -> None:
        output = FakeOutput()
        bridge = self._running_bridge(output)

        bridge._note_on(channel=0, note=20, velocity=100)

        self.assertEqual(output.events, [])

    def test_low_to_high_octave_presses_up_twice(self) -> None:
        output = FakeOutput()
        bridge = self._running_bridge(output)

        bridge._note_on(channel=0, note=21, velocity=100)
        bridge._note_on(channel=0, note=84, velocity=100)

        self.assertEqual(
            output.events,
            [
                ("tap", "<"),
                ("press", "n"),
                ("release", "n"),
                ("tap", ">"),
                ("tap", ">"),
                ("press", "z"),
            ],
        )

    def test_low_to_normal_releases_same_physical_key_before_repress(self) -> None:
        output = FakeOutput()
        bridge = self._running_bridge(output)

        bridge._note_on(channel=0, note=21, velocity=100)
        bridge._note_on(channel=0, note=57, velocity=100)

        self.assertEqual(
            output.events,
            [
                ("tap", "<"),
                ("press", "n"),
                ("release", "n"),
                ("tap", ">"),
                ("press", "n"),
            ],
        )

    def test_stop_returns_octave_shift_to_base(self) -> None:
        output = FakeOutput()
        bridge = self._running_bridge(output)

        bridge._note_on(channel=0, note=21, velocity=100)
        bridge._move_to_octave_shift(0)

        self.assertIn(("tap", "<"), output.events)
        self.assertIn(("tap", ">"), output.events)

    def test_startup_reset_presses_down_down_up(self) -> None:
        output = FakeOutput()
        bridge = MidiInputKeyboardBridge(device_id=0, output=output)

        bridge._reset_external_octave_to_base()

        self.assertEqual(output.events, [("tap", "<"), ("tap", "<"), ("tap", ">")])

    def test_startup_reset_is_skipped_when_auto_fit_is_enabled(self) -> None:
        output = FakeOutput()
        bridge = MidiInputKeyboardBridge(device_id=0, output=output, auto_fit_note_range=True)

        bridge._reset_external_octave_to_base_if_needed()

        self.assertEqual(output.events, [])

    def test_state_logs_are_not_indented_and_input_events_are_indented(self) -> None:
        output = FakeOutput()
        logs: list[str] = []
        bridge = self._running_bridge(output, log=logs.append)

        bridge.log("MIDI keyboard input started")
        bridge._note_on(channel=0, note=55, velocity=93)
        bridge.log("MIDI keyboard input stopped")

        self.assertEqual(
            logs,
            [
                "MIDI keyboard input started",
                "   input ch 0 on  G3  -> b v93",
                "MIDI keyboard input stopped",
            ],
        )

    def test_auto_fit_note_range_uses_base_range_without_octave_switch(self) -> None:
        output = FakeOutput()
        bridge = self._running_bridge(output, auto_fit_note_range=True)

        bridge._note_on(channel=0, note=84, velocity=100)
        bridge._note_off(channel=0, note=84)

        self.assertEqual(output.events, [("press", "q"), ("release", "q")])

    def test_auto_fit_overlapping_notes_keep_key_pressed_until_all_are_off(self) -> None:
        output = FakeOutput()
        bridge = self._running_bridge(output, auto_fit_note_range=True)

        bridge._note_on(channel=0, note=72, velocity=100)
        bridge._note_on(channel=0, note=84, velocity=100)
        bridge._note_off(channel=0, note=72)
        bridge._note_off(channel=0, note=84)

        self.assertEqual(
            output.events,
            [
                ("press", "q"),
                ("release", "q"),
                ("press", "q"),
                ("release", "q"),
            ],
        )

    def test_repeat_prevention_suppresses_realtime_same_target_and_consumes_note_off(self) -> None:
        output = FakeOutput()
        logs: list[str] = []
        bridge = self._running_bridge(
            output,
            log=logs.append,
            repeat_prevention=True,
        )

        bridge._note_on(channel=0, note=60, velocity=100, received_at=1.0)
        bridge._note_on(channel=0, note=60, velocity=100, received_at=1.049)
        bridge._note_off(channel=0, note=60)

        self.assertEqual(output.events, [("press", "a")])
        self.assertTrue(any("skip rapid repeat" in message for message in logs))

        bridge._note_off(channel=0, note=60)
        self.assertEqual(output.events, [("press", "a"), ("release", "a")])

    def test_repeat_prevention_uses_converted_realtime_target(self) -> None:
        output = FakeOutput()
        bridge = self._running_bridge(
            output,
            auto_fit_note_range=True,
            repeat_prevention=True,
        )

        bridge._note_on(channel=0, note=72, velocity=100, received_at=2.0)
        bridge._note_off(channel=0, note=72)
        bridge._note_on(channel=0, note=84, velocity=100, received_at=2.04)
        bridge._note_off(channel=0, note=84)

        self.assertEqual(output.events, [("press", "q"), ("release", "q")])

    def test_enabling_repeat_prevention_during_realtime_input_takes_effect_immediately(self) -> None:
        output = FakeOutput()
        bridge = self._running_bridge(output)

        bridge.set_repeat_prevention(True)
        bridge._note_on(channel=0, note=60, velocity=100, received_at=3.0)
        bridge._note_off(channel=0, note=60)
        bridge._note_on(channel=0, note=60, velocity=100, received_at=3.02)
        bridge._note_off(channel=0, note=60)

        self.assertEqual(output.events, [("press", "a"), ("release", "a")])

    def test_disabling_repeat_prevention_keeps_pending_suppressed_note_off(self) -> None:
        output = FakeOutput()
        bridge = self._running_bridge(output, repeat_prevention=True)

        bridge._note_on(channel=0, note=60, velocity=100, received_at=4.0)
        bridge._note_on(channel=0, note=60, velocity=100, received_at=4.02)
        bridge.set_repeat_prevention(False)
        bridge._note_off(channel=0, note=60)

        self.assertEqual(output.events, [("press", "a")])

        bridge._note_off(channel=0, note=60)
        self.assertEqual(output.events, [("press", "a"), ("release", "a")])

    def test_note_event_after_stop_is_ignored(self) -> None:
        output = FakeOutput()
        bridge = MidiInputKeyboardBridge(device_id=0, output=output)

        bridge._note_on(channel=0, note=60, velocity=100)

        self.assertEqual(output.events, [])

    def test_sustain_remains_pressed_until_all_channels_release(self) -> None:
        output = FakeOutput()
        bridge = self._running_bridge(output)

        bridge._sustain(channel=0, value=127)
        bridge._sustain(channel=1, value=127)
        bridge._sustain(channel=0, value=0)
        bridge._sustain(channel=1, value=0)

        self.assertEqual(output.events, [("press", "space"), ("release", "space")])

    def test_raw_midi_messages_are_forwarded_to_sound_callback(self) -> None:
        output = FakeOutput()
        messages: list[tuple[int, int, int, int, float]] = []
        bridge = self._running_bridge(output, on_midi_message=lambda *message: messages.append(message))

        with patch("live_midi_input.time.perf_counter", return_value=12.5):
            bridge._midi_callback(None, MIM_DATA, 0, 0x90 | (60 << 8) | (100 << 16), 0)
            bridge._midi_callback(None, MIM_DATA, 0, 0x80 | (60 << 8), 0)
            bridge._midi_callback(None, MIM_DATA, 0, 0xB0 | (64 << 8) | (127 << 16), 0)

        self.assertEqual(
            messages,
            [
                (0x90, 0, 60, 100, 12.5),
                (0x80, 0, 60, 0, 12.5),
                (0xB0, 0, 64, 127, 12.5),
            ],
        )

    def test_sound_callback_failure_does_not_stop_keyboard_input(self) -> None:
        output = FakeOutput()

        def fail_sound(*_message) -> None:
            raise RuntimeError("sound failed")

        bridge = self._running_bridge(output, on_midi_message=fail_sound)
        bridge._midi_callback(None, MIM_DATA, 0, 0x90 | (60 << 8) | (100 << 16), 0)

        self.assertTrue(bridge.is_running)
        self.assertEqual(output.events, [("press", "a")])


if __name__ == "__main__":
    unittest.main()
