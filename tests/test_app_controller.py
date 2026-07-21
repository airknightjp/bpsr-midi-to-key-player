from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_controller
from app_controller import AppController
from app_state import TrackChannelItem
from midi_parser import MidiEvent, MidiSummary, MidiTrackSummary
from settings import AppSettings


class RecordingView:
    def __init__(self) -> None:
        self.states = []
        self.logs: list[str] = []
        self.messages: list[tuple[str, str, str]] = []
        self.clear_count = 0

    def render(self, state) -> None:  # type: ignore[no-untyped-def]
        self.states.append(state)

    def append_log(self, message: str) -> None:
        self.logs.append(message)

    def clear_log(self) -> None:
        self.clear_count += 1

    def show_message(self, level: str, title: str, message: str) -> None:
        self.messages.append((level, title, message))


class FakePlayer:
    instance = None
    is_playing = True

    def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.kwargs = kwargs
        self.play_args = None
        self.stopped = False
        FakePlayer.instance = self

    def play_with_countdown_sound(self, events, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.play_args = (events, kwargs)

    def stop(self) -> None:
        self.stopped = True
        self.is_playing = False

    def wait_until_stopped(self, timeout: float = 1.0) -> None:
        pass

    def current_position(self) -> float:
        return 12.5

    def set_playback_speed(self, value: int) -> None:
        self.speed = value

    def request_chord_optimization_refresh(self) -> None:
        self.refreshed = True

    def request_release_all(self) -> None:
        self.released = True


class AppControllerTests(unittest.TestCase):
    def make_controller(self, **settings) -> AppController:  # type: ignore[no-untyped-def]
        return AppController(AppSettings(**settings))

    def test_controller_has_no_qt_or_tk_dependency(self) -> None:
        source = inspect.getsource(app_controller)
        self.assertNotIn("PySide6", source)
        self.assertNotIn("tkinter", source)

    def test_settings_initialize_state_without_a_view(self) -> None:
        controller = self.make_controller(
            language="ja",
            midi_sound_volume=64,
            playback_speed_percent=137,
            transpose_semitones=4,
            octave_shift=-1,
        )

        self.assertEqual(controller.state.language, "ja")
        self.assertEqual(controller.state.midi_sound_volume, 64)
        self.assertEqual(controller.state.playback_speed_percent, 137)
        self.assertEqual(controller.state.transpose_semitones, 4)
        self.assertEqual(controller.state.octave_shift, -1)

    def test_pause_and_resume_keyboard_playback_from_current_position(self) -> None:
        controller = self.make_controller()
        player = FakePlayer()
        controller.player = player
        controller.state.current_mode = "keys"
        controller.state.duration = 60.0
        controller.state.position = 4.0

        controller.toggle_keyboard_pause()

        self.assertTrue(player.stopped)
        self.assertIsNone(controller.player)
        self.assertTrue(controller.state.keyboard_paused)
        self.assertEqual(controller.state.position, 12.5)
        self.assertEqual(controller.state.status, "paused")

        with patch.object(controller, "play_keyboard") as play_keyboard:
            controller.toggle_keyboard_pause()

        play_keyboard.assert_called_once_with(start_time=12.5, countdown=False)
        self.assertIsNone(controller.state.current_mode)

    def test_pause_shortcut_option_is_persistent_and_rebinds_hotkeys(self) -> None:
        controller = self.make_controller()
        with patch.object(controller, "_bind_global_hotkeys") as bind_hotkeys:
            controller.set_option("keyboard_pause_shortcut", "Ctrl+R")

        self.assertEqual(controller.state.keyboard_pause_shortcut, "Ctrl+R")
        self.assertEqual(controller.current_settings().keyboard_pause_shortcut, "Ctrl+R")
        bind_hotkeys.assert_called_once_with()

    def test_live_speed_setting_updates_active_player(self) -> None:
        controller = self.make_controller()
        controller.player = FakePlayer()

        controller.set_option("playback_speed_percent", 155)

        self.assertEqual(controller.state.playback_speed_percent, 155)
        self.assertEqual(controller.player.speed, 155)

    def test_track_channel_toggle_updates_source_snapshots(self) -> None:
        controller = self.make_controller()
        controller._set_enabled_sources(((0, 0), (0, 1)))
        controller.state.track_channels = [
            TrackChannelItem(0, 0),
            TrackChannelItem(0, 1),
        ]

        controller.toggle_track_channel(0, 1)

        self.assertEqual(controller.enabled_sources(), {(0, 0)})
        self.assertTrue(controller.state.track_channels[0].enabled)
        self.assertFalse(controller.state.track_channels[1].enabled)

    def test_first_folder_load_enables_all_track_channels(self) -> None:
        controller = self.make_controller()
        with tempfile.TemporaryDirectory() as temporary_directory:
            midi_path = Path(temporary_directory) / "song.mid"
            midi_path.write_bytes(b"midi")
            summary = MidiSummary(
                path=midi_path,
                duration=1.0,
                channels=(0, 1),
                event_count=2,
                tracks=(MidiTrackSummary(index=0, channels=(0, 1)),),
            )
            with (
                patch.object(controller, "_start_metadata_scan"),
                patch("app_controller.parse_midi", return_value=([], summary)),
            ):
                controller.load_midi_folder(temporary_directory, save_folder=False)

        self.assertEqual(
            controller.state.track_channels,
            [TrackChannelItem(0, 0, True), TrackChannelItem(0, 1, True)],
        )
        self.assertEqual(controller.enabled_sources(), {(0, 0), (0, 1)})

    def test_keyboard_playback_receives_state_settings(self) -> None:
        controller = self.make_controller(
            countdown_seconds=4,
            playback_speed_percent=125,
            transpose_semitones=3,
            octave_shift=-1,
            humanize_timing=True,
            chord_optimization=True,
            repeat_prevention=True,
        )
        controller.events = [MidiEvent(0.0, "note_on", 0, 60, 80, track=0)]
        controller._set_enabled_sources(((0, 0),))
        with (
            patch("app_controller.MidiKeyboardPlayer", FakePlayer),
            patch("app_controller.KeyboardOutput"),
        ):
            controller.play_keyboard()

        player = FakePlayer.instance
        self.assertIsNotNone(player)
        self.assertEqual(player.kwargs["playback_speed_percent"], 125)
        self.assertEqual(player.kwargs["transpose_semitones"], 3)
        self.assertEqual(player.kwargs["octave_shift"], -1)
        self.assertTrue(player.kwargs["humanize_timing"])
        self.assertTrue(player.kwargs["chord_optimization"])
        self.assertTrue(player.kwargs["repeat_prevention"])
        self.assertEqual(player.play_args[1]["countdown_seconds"], 4)

    def test_poll_ignores_stale_playback_messages(self) -> None:
        controller = self.make_controller()
        controller.playback_id = 5
        controller.state.status = "waiting.."
        controller.worker_queue.put(("key_state", 4, "playing"))

        controller.poll()

        self.assertEqual(controller.state.status, "waiting..")

    def test_note_range_format_is_standard_midi_notation(self) -> None:
        self.assertEqual(AppController.format_note_range((36, 85)), "C2-C#6")


if __name__ == "__main__":
    unittest.main()
