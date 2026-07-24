from __future__ import annotations

import queue
import unittest
from unittest.mock import patch

from legacy_tk_main import App
from sound_player import RealtimeMidiSoundOutput


class RecordingSynthClient:
    def __init__(self, messages: list[tuple[int, int, int]]) -> None:
        self.messages = messages
        self.is_open = False
        self.sound_source = "piano"

    def open(self) -> bool:
        self.is_open = True
        return True

    def close(self) -> None:
        self.is_open = False

    def set_sound_source(self, sound_source: str) -> None:
        self.sound_source = sound_source

    def note_on(self, channel: int, note: int, velocity: int) -> None:
        self.messages.append((0x90 | channel, note, velocity))

    def note_off(self, channel: int, note: int) -> None:
        self.messages.append((0x80 | channel, note, 0))

    def set_sustain(self, channel: int, enabled: bool) -> None:
        self.messages.append((0xB0 | channel, 64, 127 if enabled else 0))

    def release_all(self, channel: int | None = None) -> None:
        if channel is not None:
            self.messages.append((0xB0 | channel, 123, 0))


class RecordingRealtimeMidiSoundOutput(RealtimeMidiSoundOutput):
    def __init__(self, volume: int = 100, **kwargs):
        super().__init__(volume=volume, **kwargs)
        self.messages: list[tuple[int, int, int]] = []
        self._synth = RecordingSynthClient(self.messages)


class RealtimeMidiSoundOutputTests(unittest.TestCase):
    def test_note_velocity_uses_current_midi_volume(self) -> None:
        output = RecordingRealtimeMidiSoundOutput(volume=50)
        self.assertTrue(output.set_enabled(True))

        output.process_message(0x90, 2, 60, 100)
        output.set_volume(80)
        output.process_message(0x90, 2, 62, 100)
        output.process_message(0x80, 2, 60, 0)

        self.assertEqual(
            output.messages[:3],
            [
                (0x92, 60, 50),
                (0x92, 62, 80),
                (0x82, 60, 0),
            ],
        )

    def test_disabling_releases_notes_and_ignores_future_input(self) -> None:
        output = RecordingRealtimeMidiSoundOutput()
        output.set_enabled(True)
        output.process_message(0x90, 0, 60, 100)

        output.set_enabled(False)
        message_count = len(output.messages)
        output.process_message(0x90, 0, 64, 100)

        self.assertIn((0x80, 60, 0), output.messages)
        self.assertIn((0xB0, 123, 0), output.messages)
        self.assertEqual(len(output.messages), message_count)

    def test_sustain_is_forwarded_and_released_on_close(self) -> None:
        output = RecordingRealtimeMidiSoundOutput()
        output.set_enabled(True)
        output.process_message(0xB0, 1, 64, 127)

        output.close()

        self.assertEqual(output.messages[0], (0xB1, 64, 127))
        self.assertIn((0xB1, 64, 0), output.messages)
        self.assertIn((0xB1, 123, 0), output.messages)

    def test_transpose_and_octave_shift_are_applied_to_realtime_sound(self) -> None:
        output = RecordingRealtimeMidiSoundOutput(
            transpose_semitones=2,
            octave_shift=1,
        )
        output.set_enabled(True)

        output.process_message(0x90, 0, 48, 100)
        output.process_message(0x80, 0, 48, 0)

        self.assertEqual(output.messages[:2], [(0x90, 62, 100), (0x80, 62, 0)])

    def test_repeat_prevention_suppresses_realtime_sound_and_consumes_note_off(self) -> None:
        output = RecordingRealtimeMidiSoundOutput(repeat_prevention=True)
        output.set_enabled(True)

        output.process_message(0x90, 0, 60, 100, received_at=1.0)
        output.process_message(0x90, 0, 60, 100, received_at=1.02)
        output.process_message(0x80, 0, 60, 0)

        self.assertEqual(output.messages, [(0x90, 60, 100)])

        output.process_message(0x80, 0, 60, 0)
        self.assertEqual(output.messages, [(0x90, 60, 100), (0x80, 60, 0)])


class FakeVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class ConfiguredKeyboardOutput:
    instance = None

    def __init__(self, dry_run: bool):
        self.dry_run = dry_run
        ConfiguredKeyboardOutput.instance = self


class ConfiguredRealtimeSoundOutput:
    instance = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.enabled_calls: list[bool] = []
        ConfiguredRealtimeSoundOutput.instance = self

    def set_enabled(self, enabled: bool) -> bool:
        self.enabled_calls.append(enabled)
        return True

    def process_message(self, *_message) -> None:
        pass

    def close(self) -> None:
        pass


class ConfiguredMidiInputBridge:
    instance = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.is_running = False
        ConfiguredMidiInputBridge.instance = self

    def start(self) -> None:
        self.is_running = True


class RealtimeInputSoundModeTests(unittest.TestCase):
    def test_realtime_sound_follows_test_mode_when_input_starts(self) -> None:
        for test_mode in (False, True):
            with self.subTest(test_mode=test_mode):
                app = object.__new__(App)
                app.current_play_mode = None
                app.midi_input_bridge = None
                app.realtime_sound_output = None
                app.midi_input_device_var = FakeVar("USB MIDI")
                app.dry_run_var = FakeVar(test_mode)
                app.sound_volume_var = FakeVar(72)
                app.auto_fit_note_range_var = FakeVar(False)
                app.transpose_semitones_var = FakeVar(-4)
                app.octave_shift_var = FakeVar(1)
                app.repeat_prevention_var = FakeVar(True)
                app.log_queue = queue.Queue()
                app._selected_midi_input_device_id = lambda: 2
                app._save_current_settings = lambda: None
                app._refresh_playback_buttons = lambda: None
                app._refresh_midi_input_button = lambda: None
                app._refresh_option_states = lambda: None

                with (
                    patch("legacy_tk_main.KeyboardOutput", ConfiguredKeyboardOutput),
                    patch("legacy_tk_main.RealtimeMidiSoundOutput", ConfiguredRealtimeSoundOutput),
                    patch("legacy_tk_main.MidiInputKeyboardBridge", ConfiguredMidiInputBridge),
                ):
                    App.start_midi_input(app)

                self.assertEqual(ConfiguredKeyboardOutput.instance.dry_run, test_mode)
                self.assertEqual(ConfiguredRealtimeSoundOutput.instance.enabled_calls, [test_mode])
                self.assertTrue(ConfiguredMidiInputBridge.instance.is_running)
                self.assertEqual(
                    ConfiguredRealtimeSoundOutput.instance.kwargs["transpose_semitones"],
                    -4,
                )
                self.assertEqual(ConfiguredMidiInputBridge.instance.kwargs["octave_shift"], 1)
                self.assertTrue(
                    ConfiguredRealtimeSoundOutput.instance.kwargs["repeat_prevention"]
                )
                self.assertTrue(
                    ConfiguredMidiInputBridge.instance.kwargs["repeat_prevention"]
                )


if __name__ == "__main__":
    unittest.main()
