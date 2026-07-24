from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import app_controller
from app_controller import AppController
from app_state import TrackChannelItem
from config import (
    SOUND_PLAYBACK_MODE_CONTINUOUS,
    SOUND_PLAYBACK_MODE_OFF,
    SOUND_PLAYBACK_MODE_REPEAT_ONE,
)
from midi_parser import MidiEvent, MidiSummary, MidiTrackSummary
from settings import AppSettings


class RecordingView:
    def __init__(self) -> None:
        self.states = []
        self.logs: list[str] = []
        self.messages: list[tuple[str, str, str]] = []
        self.clear_count = 0
        self.output_release_delays: list[int] = []
        self.rhythm_score_delays: list[int | None] = []

    def render(self, state) -> None:  # type: ignore[no-untyped-def]
        self.states.append(state)

    def append_log(self, message: str) -> None:
        self.logs.append(message)

    def clear_log(self) -> None:
        self.clear_count += 1

    def show_message(self, level: str, title: str, message: str) -> None:
        self.messages.append((level, title, message))

    def schedule_output_note_release(self, delay_ms: int) -> None:
        self.output_release_delays.append(delay_ms)

    def schedule_rhythm_score_update(self, delay_ms: int | None) -> None:
        self.rhythm_score_delays.append(delay_ms)


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

    def play(self, events, **kwargs) -> None:  # type: ignore[no-untyped-def]
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


class FakeRealtimeSoundOutput:
    def __init__(self) -> None:
        self.enabled_calls: list[bool] = []

    def set_enabled(self, enabled: bool) -> bool:
        self.enabled_calls.append(bool(enabled))
        return True


class AppControllerTests(unittest.TestCase):
    def make_controller(self, **settings) -> AppController:  # type: ignore[no-untyped-def]
        return AppController(AppSettings(**settings))

    def test_controller_has_no_qt_or_tk_dependency(self) -> None:
        source = inspect.getsource(app_controller)
        self.assertNotIn("PySide6", source)
        self.assertNotIn("tkinter", source)

    def test_worker_messages_coalesce_event_dispatch_notifications(self) -> None:
        controller = self.make_controller()
        notifications: list[bool] = []
        controller.set_event_notifier(lambda: notifications.append(True))

        controller._queue_worker_message(("log", "first"))
        controller._queue_worker_message(("log", "second"))

        self.assertEqual(notifications, [True])
        controller.process_pending_events()
        controller._queue_worker_message(("log", "third"))
        self.assertEqual(notifications, [True, True])

    def test_seek_discards_queued_positions_from_the_previous_generation(self) -> None:
        controller = self.make_controller()
        controller.state.duration = 120.0
        controller.playback_id = 4
        previous_generation = controller.position_generation
        controller.worker_queue.put(
            ("position", 4, previous_generation, 12.0)
        )

        controller.seek(90.0)
        controller.worker_queue.put(
            ("position", 4, controller.position_generation, 90.1)
        )
        controller.process_pending_events()

        self.assertAlmostEqual(controller.state.position, 90.1)

    def test_settings_are_saved_only_when_controller_shuts_down(self) -> None:
        controller = self.make_controller()
        with patch("app_controller.save_settings") as save:
            controller.request_save()
            save.assert_not_called()

            controller.shutdown()

        save.assert_called_once()

    def test_settings_can_be_saved_explicitly_without_duplicate_shutdown_save(
        self,
    ) -> None:
        controller = self.make_controller()
        controller.request_save()

        with patch("app_controller.save_settings") as save:
            self.assertTrue(controller.save_settings_now())
            save.assert_called_once()

            controller.shutdown()

        save.assert_called_once()

    def test_output_note_release_uses_single_shot_view_schedule(self) -> None:
        controller = self.make_controller()
        view = RecordingView()
        controller.attach_view(view)

        controller._set_output_note_state(("sound", 1), 60, True)
        controller._set_output_note_state(("sound", 1), 60, False)

        self.assertEqual(len(view.output_release_delays), 1)
        self.assertGreater(view.output_release_delays[0], 0)

    def test_settings_initialize_state_without_a_view(self) -> None:
        controller = self.make_controller(
            language="ja",
            midi_sound_volume=64,
            sound_source="organ",
            playback_speed_percent=137,
            transpose_semitones=4,
            octave_shift=-1,
            automatic_audio_buffer_frames=2_048,
            hide_release_notes_on_startup=True,
        )

        self.assertEqual(controller.state.language, "ja")
        self.assertEqual(controller.state.midi_sound_volume, 64)
        self.assertEqual(controller.state.sound_source, "organ")
        self.assertEqual(controller.state.audio_qt_frames, 1_024)
        self.assertEqual(controller.state.audio_buffer_frames, 2_048)
        self.assertEqual(controller.state.playback_speed_percent, 137)
        self.assertEqual(controller.state.transpose_semitones, 4)
        self.assertEqual(controller.state.octave_shift, -1)
        self.assertTrue(controller.state.hide_release_notes_on_startup)

    def test_pause_and_resume_keyboard_playback_from_current_position(self) -> None:
        controller = self.make_controller()
        player = FakePlayer()
        controller.player = player
        controller.state.current_mode = "keys"
        controller.state.duration = 60.0
        controller.state.position = 4.0
        controller.state.active_output_notes = frozenset((60, 64))

        controller.toggle_keyboard_pause()

        self.assertTrue(player.stopped)
        self.assertIsNone(controller.player)
        self.assertTrue(controller.state.keyboard_paused)
        self.assertEqual(controller.state.position, 12.5)
        self.assertEqual(controller.state.status, "paused")
        self.assertEqual(controller.state.active_output_notes, frozenset())

        with patch.object(controller, "play_keyboard") as play_keyboard:
            controller.toggle_keyboard_pause()

        play_keyboard.assert_called_once_with(
            start_time=12.5,
            countdown=False,
            reset_rhythm_score=False,
        )
        self.assertIsNone(controller.state.current_mode)

    def test_pause_and_resume_sound_playback_from_current_position(self) -> None:
        controller = self.make_controller()
        player = FakePlayer()
        controller.sound_player = player
        controller.state.current_mode = "sound"
        controller.state.duration = 60.0
        controller.state.position = 4.0

        controller.toggle_sound_pause()

        self.assertTrue(player.stopped)
        self.assertIsNone(controller.sound_player)
        self.assertTrue(controller.state.sound_paused)
        self.assertEqual(controller.state.position, 12.5)

        with patch.object(controller, "play_sound") as play_sound:
            controller.toggle_sound_pause()

        play_sound.assert_called_once_with(
            start_time=12.5,
            reset_rhythm_score=False,
        )
        self.assertIsNone(controller.state.current_mode)

    def test_sound_playback_mode_cycles_and_is_persistent(self) -> None:
        controller = self.make_controller()
        self.assertEqual(
            controller.state.sound_playback_mode,
            SOUND_PLAYBACK_MODE_OFF,
        )

        controller.cycle_sound_playback_mode()
        self.assertEqual(
            controller.state.sound_playback_mode,
            SOUND_PLAYBACK_MODE_CONTINUOUS,
        )
        controller.cycle_sound_playback_mode()
        self.assertEqual(
            controller.state.sound_playback_mode,
            SOUND_PLAYBACK_MODE_REPEAT_ONE,
        )
        controller.cycle_sound_playback_mode()

        self.assertEqual(
            controller.current_settings().sound_playback_mode,
            SOUND_PLAYBACK_MODE_OFF,
        )

    def test_repeat_one_restarts_sound_after_natural_end(self) -> None:
        controller = self.make_controller(
            sound_playback_mode=SOUND_PLAYBACK_MODE_REPEAT_ONE
        )
        controller.sound_player = FakePlayer()
        controller.state.current_mode = "sound"
        controller.state.duration = 60.0
        controller.playback_id = 7
        controller.worker_queue.put(("sound_state", 7, "sound ended"))

        with patch.object(controller, "play_sound") as play_sound:
            controller.process_pending_events()

        play_sound.assert_called_once_with(start_time=0.0)
        self.assertEqual(controller.state.position, 0.0)

    def test_continuous_playback_wraps_from_last_song_to_first(self) -> None:
        controller = self.make_controller(
            sound_playback_mode=SOUND_PLAYBACK_MODE_CONTINUOUS
        )
        controller.midi_files = [Path("first.mid"), Path("last.mid")]
        controller.state.selected_midi_index = 1
        controller.sound_player = FakePlayer()
        controller.state.current_mode = "sound"
        controller.state.duration = 60.0
        controller.playback_id = 9
        controller.worker_queue.put(("sound_state", 9, "sound ended"))

        def select_first(index: int) -> None:
            controller.state.selected_midi_index = index

        with (
            patch.object(controller, "select_midi", side_effect=select_first) as select_midi,
            patch.object(controller, "play_sound") as play_sound,
        ):
            controller.process_pending_events()

        select_midi.assert_called_once_with(0)
        play_sound.assert_called_once_with(start_time=0.0)

    def test_playback_mode_off_stops_after_natural_end(self) -> None:
        controller = self.make_controller(
            sound_playback_mode=SOUND_PLAYBACK_MODE_OFF
        )
        controller.sound_player = FakePlayer()
        controller.state.current_mode = "sound"
        controller.state.duration = 60.0
        controller.playback_id = 11
        controller.worker_queue.put(("sound_state", 11, "sound ended"))

        with patch.object(controller, "play_sound") as play_sound:
            controller.process_pending_events()

        play_sound.assert_not_called()
        self.assertIsNone(controller.state.current_mode)
        self.assertEqual(controller.state.position, 60.0)

    def test_common_input_conversion_toggle_dispatches_selected_mode(self) -> None:
        controller = self.make_controller(input_conversion_mode="realtime")
        with (
            patch.object(controller, "start_midi_input") as start_realtime,
            patch.object(controller, "play_keyboard") as start_midi_file,
        ):
            controller.toggle_input_conversion()

        start_realtime.assert_called_once_with()
        start_midi_file.assert_not_called()

        controller.state.input_conversion_mode = "midi_file"
        with (
            patch.object(controller, "start_midi_input") as start_realtime,
            patch.object(controller, "play_keyboard") as start_midi_file,
        ):
            controller.toggle_input_conversion()

        start_realtime.assert_not_called()
        start_midi_file.assert_called_once_with()

    def test_midi_file_conversion_restarts_from_zero_while_sound_is_paused(self) -> None:
        controller = self.make_controller(input_conversion_mode="midi_file")
        controller.state.current_mode = "sound_paused"
        controller.state.position = 18.5

        with (
            patch.object(
                controller,
                "stop_playback",
                wraps=controller.stop_playback,
            ) as stop_playback,
            patch.object(controller, "play_keyboard") as play_keyboard,
        ):
            controller.toggle_input_conversion()

        stop_playback.assert_called_once_with()
        play_keyboard.assert_called_once_with(start_time=0.0)
        self.assertIsNone(controller.state.current_mode)
        self.assertEqual(controller.state.position, 0.0)

    def test_start_hotkey_restarts_midi_conversion_while_sound_is_paused(
        self,
    ) -> None:
        controller = self.make_controller(input_conversion_mode="midi_file")
        controller.state.current_mode = "sound_paused"
        controller.state.position = 18.5
        controller.worker_queue.put(("hotkey", "play"))

        with (
            patch.object(
                controller,
                "stop_playback",
                wraps=controller.stop_playback,
            ) as stop_playback,
            patch.object(controller, "play_keyboard") as play_keyboard,
        ):
            controller.process_pending_events()

        stop_playback.assert_called_once_with()
        play_keyboard.assert_called_once_with(start_time=0.0)
        self.assertIsNone(controller.state.current_mode)
        self.assertEqual(controller.state.position, 0.0)

    def test_start_hotkey_starts_idle_midi_file_conversion(self) -> None:
        controller = self.make_controller(input_conversion_mode="midi_file")
        controller.worker_queue.put(("hotkey", "play"))

        with patch.object(controller, "play_keyboard") as play_keyboard:
            controller.process_pending_events()

        play_keyboard.assert_called_once_with()

    def test_start_hotkey_does_not_stop_running_midi_conversion(self) -> None:
        controller = self.make_controller(input_conversion_mode="midi_file")
        controller.state.current_mode = "keys"
        controller.worker_queue.put(("hotkey", "play"))

        with (
            patch.object(controller, "stop_playback") as stop_playback,
            patch.object(controller, "play_keyboard") as play_keyboard,
        ):
            controller.process_pending_events()

        stop_playback.assert_not_called()
        play_keyboard.assert_not_called()
        self.assertTrue(controller.state.keyboard_playing)

    def test_start_hotkey_restarts_paused_midi_conversion_from_zero(self) -> None:
        controller = self.make_controller(input_conversion_mode="midi_file")
        controller.state.current_mode = "keys_paused"
        controller.state.position = 18.5
        controller.worker_queue.put(("hotkey", "play"))

        with (
            patch.object(
                controller,
                "stop_playback",
                wraps=controller.stop_playback,
            ) as stop_playback,
            patch.object(controller, "play_keyboard") as play_keyboard,
        ):
            controller.process_pending_events()

        stop_playback.assert_called_once_with()
        play_keyboard.assert_called_once_with(start_time=0.0)
        self.assertIsNone(controller.state.current_mode)
        self.assertEqual(controller.state.position, 0.0)

    def test_input_shortcuts_do_not_affect_realtime_input(self) -> None:
        for action in ("play", "pause_resume", "stop"):
            with self.subTest(action=action):
                controller = self.make_controller(
                    input_conversion_mode="realtime"
                )
                controller.state.midi_input_running = True
                controller.worker_queue.put(("hotkey", action))

                with (
                    patch.object(controller, "start_midi_input") as start_input,
                    patch.object(controller, "stop_midi_input") as stop_input,
                    patch.object(controller, "stop_playback") as stop_playback,
                    patch.object(controller, "play_keyboard") as play_keyboard,
                ):
                    controller.process_pending_events()

                start_input.assert_not_called()
                stop_input.assert_not_called()
                stop_playback.assert_not_called()
                play_keyboard.assert_not_called()
                self.assertTrue(controller.state.midi_input_running)

    def test_input_shortcuts_do_not_affect_active_midi_sound_playback(
        self,
    ) -> None:
        for action in ("play", "pause_resume", "stop"):
            with self.subTest(action=action):
                controller = self.make_controller(
                    input_conversion_mode="midi_file"
                )
                controller.state.current_mode = "sound"
                controller.worker_queue.put(("hotkey", action))

                with (
                    patch.object(controller, "stop_playback") as stop_playback,
                    patch.object(controller, "play_keyboard") as play_keyboard,
                ):
                    controller.process_pending_events()

                stop_playback.assert_not_called()
                play_keyboard.assert_not_called()
                self.assertTrue(controller.state.sound_playing)

    def test_pause_and_end_hotkeys_do_not_affect_paused_midi_sound(
        self,
    ) -> None:
        for action in ("pause_resume", "stop"):
            with self.subTest(action=action):
                controller = self.make_controller(
                    input_conversion_mode="midi_file"
                )
                controller.state.current_mode = "sound_paused"
                controller.state.position = 18.5
                controller.worker_queue.put(("hotkey", action))

                with (
                    patch.object(controller, "stop_playback") as stop_playback,
                    patch.object(controller, "play_keyboard") as play_keyboard,
                ):
                    controller.process_pending_events()

                stop_playback.assert_not_called()
                play_keyboard.assert_not_called()
                self.assertTrue(controller.state.sound_paused)
                self.assertEqual(controller.state.position, 18.5)

    def test_pause_hotkey_pauses_and_resumes_midi_file_conversion(
        self,
    ) -> None:
        controller = self.make_controller(input_conversion_mode="midi_file")
        player = FakePlayer()
        controller.player = player
        controller.state.current_mode = "keys"
        controller.state.duration = 60.0
        controller.worker_queue.put(("hotkey", "pause_resume"))

        controller.process_pending_events()

        self.assertTrue(player.stopped)
        self.assertTrue(controller.state.keyboard_paused)
        self.assertEqual(controller.state.position, 12.5)

        controller.worker_queue.put(("hotkey", "pause_resume"))
        with patch.object(controller, "play_keyboard") as play_keyboard:
            controller.process_pending_events()

        play_keyboard.assert_called_once_with(
            start_time=12.5,
            countdown=False,
            reset_rhythm_score=False,
        )

    def test_end_hotkey_stops_only_midi_file_conversion(self) -> None:
        for mode in ("keys", "keys_paused"):
            with self.subTest(mode=mode):
                controller = self.make_controller(
                    input_conversion_mode="midi_file"
                )
                controller.state.current_mode = mode
                controller.worker_queue.put(("hotkey", "stop"))

                with patch.object(
                    controller,
                    "stop_playback",
                ) as stop_playback:
                    controller.process_pending_events()

                stop_playback.assert_called_once_with()

    def test_common_input_conversion_toggle_stops_the_running_mode(self) -> None:
        controller = self.make_controller()
        controller.state.midi_input_running = True
        with (
            patch.object(controller, "stop_midi_input") as stop_realtime,
            patch.object(controller, "stop_playback") as stop_midi_file,
        ):
            controller.toggle_input_conversion()

        stop_realtime.assert_called_once_with()
        stop_midi_file.assert_not_called()

        controller.state.midi_input_running = False
        controller.state.current_mode = "keys"
        with (
            patch.object(controller, "stop_midi_input") as stop_realtime,
            patch.object(controller, "stop_playback") as stop_midi_file,
        ):
            controller.toggle_input_conversion()

        stop_realtime.assert_not_called()
        stop_midi_file.assert_called_once_with()

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

    def test_panel_order_is_normalized_and_persistent(self) -> None:
        controller = self.make_controller()
        view = RecordingView()
        controller.attach_view(view)

        controller.set_panel_order(("player", "keyboard", "player"))

        self.assertEqual(controller.state.panel_order[:2], ("player", "keyboard"))
        self.assertEqual(len(controller.state.panel_order), 5)
        self.assertEqual(controller.current_settings().panel_order, controller.state.panel_order)

    def test_section_visibility_is_restored_and_persistent(self) -> None:
        controller = self.make_controller(
            section_visibility={
                "input_conversion": False,
                "common_settings": True,
                "piano_roll": False,
                "keyboard": True,
                "player": True,
            }
        )

        self.assertFalse(controller.state.section_visibility["input_conversion"])
        self.assertFalse(controller.state.section_visibility["piano_roll"])

        controller.set_section_visible("keyboard", False)

        self.assertTrue(controller._settings_dirty)
        self.assertFalse(controller.current_settings().section_visibility["keyboard"])

    def test_auto_sustain_is_persistent_and_updates_all_active_outputs(self) -> None:
        controller = self.make_controller()
        targets = [FakePlayer(), FakePlayer(), FakePlayer(), FakePlayer()]
        for target in targets:
            target.set_auto_sustain = lambda value, item=target: setattr(
                item, "auto_sustain", value
            )
        (
            controller.player,
            controller.sound_player,
            controller.midi_input_bridge,
            controller.realtime_sound_output,
        ) = targets

        controller.set_option("auto_sustain", True)

        self.assertTrue(controller.current_settings().auto_sustain)
        self.assertTrue(all(target.auto_sustain for target in targets))

    def test_live_checkboxes_update_each_active_conversion_and_playback_target(self) -> None:
        controller = self.make_controller()
        controller.player = MagicMock()
        controller.sound_player = MagicMock()
        controller.midi_input_bridge = MagicMock()
        controller.realtime_sound_output = MagicMock()

        cases = (
            ("dry_run", "set_dry_run", ("player", "midi_input_bridge")),
            (
                "auto_fit_note_range",
                "set_auto_fit_note_range",
                ("player", "sound_player", "midi_input_bridge"),
            ),
            (
                "repeat_prevention",
                "set_repeat_prevention",
                (
                    "player",
                    "sound_player",
                    "midi_input_bridge",
                    "realtime_sound_output",
                ),
            ),
            (
                "auto_sustain",
                "set_auto_sustain",
                (
                    "player",
                    "sound_player",
                    "midi_input_bridge",
                    "realtime_sound_output",
                ),
            ),
            (
                "humanize_timing",
                "set_humanize_timing",
                ("player", "sound_player"),
            ),
            (
                "chord_strum",
                "set_chord_strum",
                ("player", "sound_player"),
            ),
            (
                "chord_optimization",
                "set_chord_optimization",
                ("player", "sound_player"),
            ),
        )

        for option, method_name, target_names in cases:
            with self.subTest(option=option):
                for target_name in (
                    "player",
                    "sound_player",
                    "midi_input_bridge",
                    "realtime_sound_output",
                ):
                    getattr(controller, target_name).reset_mock()

                controller.set_option(option, True)

                for target_name in target_names:
                    method = getattr(getattr(controller, target_name), method_name)
                    method.assert_called_once_with(True)

                if option == "dry_run":
                    controller.realtime_sound_output.set_enabled.assert_called_once_with(True)

    def test_sound_source_is_persistent_and_updates_active_outputs(self) -> None:
        controller = self.make_controller()
        sound_player = FakePlayer()
        realtime_output = FakeRealtimeSoundOutput()
        sound_player.set_sound_source = lambda value: setattr(sound_player, "sound_source", value)
        realtime_output.set_sound_source = lambda value: setattr(
            realtime_output, "sound_source", value
        )
        controller.sound_player = sound_player
        controller.realtime_sound_output = realtime_output

        controller.set_option("sound_source", "electric_piano")

        self.assertEqual(controller.state.sound_source, "electric_piano")
        self.assertEqual(controller.current_settings().sound_source, "electric_piano")
        self.assertEqual(sound_player.sound_source, "electric_piano")
        self.assertEqual(realtime_output.sound_source, "electric_piano")

    def test_automatic_audio_runtime_change_persists_buffer_state(self) -> None:
        controller = self.make_controller()
        view = RecordingView()
        controller.attach_view(view)

        controller._queue_worker_message(
            (
                "audio_runtime",
                480,
                1_024,
                "Audio runtime automatically adjusted",
            )
        )
        controller.process_pending_events()

        self.assertEqual(controller.state.audio_qt_frames, 480)
        self.assertEqual(controller.state.audio_buffer_frames, 1_024)
        self.assertEqual(
            controller.current_settings().automatic_audio_buffer_frames,
            1_024,
        )
        self.assertIn(
            "Audio runtime automatically adjusted",
            view.logs,
        )

    def test_learned_qt_minimum_is_persisted_through_settings(self) -> None:
        controller = self.make_controller(
            minimum_stable_qt_frames=1_024,
            qt_audio_environment="old-device|48000|2|Float",
        )
        view = RecordingView()
        controller.attach_view(view)

        controller._queue_worker_message(
            ("qt_learning", 512, "device|48000|2|Float")
        )
        controller.process_pending_events()

        current = controller.current_settings()
        self.assertEqual(current.minimum_stable_qt_frames, 512)
        self.assertEqual(
            current.qt_audio_environment,
            "device|48000|2|Float",
        )

    def test_changed_audio_environment_clears_learned_qt_minimum(self) -> None:
        controller = self.make_controller(
            minimum_stable_qt_frames=512,
            qt_audio_environment="old-device|48000|2|Float",
        )
        view = RecordingView()
        controller.attach_view(view)

        controller._queue_worker_message(
            ("qt_learning", None, "new-device|44100|2|Int16")
        )
        controller.process_pending_events()

        current = controller.current_settings()
        self.assertIsNone(current.minimum_stable_qt_frames)
        self.assertEqual(
            current.qt_audio_environment,
            "new-device|44100|2|Int16",
        )

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

    def test_track_toggle_enables_or_disables_every_channel_in_the_track(self) -> None:
        controller = self.make_controller()
        controller._set_enabled_sources(((0, 0), (1, 0)))
        controller.state.track_channels = [
            TrackChannelItem(0, 0, True),
            TrackChannelItem(0, 1, False),
            TrackChannelItem(1, 0, True),
        ]

        controller.toggle_track(0)

        self.assertEqual(
            controller.enabled_sources(),
            {(0, 0), (0, 1), (1, 0)},
        )
        self.assertTrue(all(item.enabled for item in controller.state.track_channels))

        controller.toggle_track(0)

        self.assertEqual(controller.enabled_sources(), {(1, 0)})
        self.assertFalse(controller.state.track_channels[0].enabled)
        self.assertFalse(controller.state.track_channels[1].enabled)
        self.assertTrue(controller.state.track_channels[2].enabled)

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

    def test_folder_load_recursively_lists_midi_with_folder_hierarchy(self) -> None:
        controller = self.make_controller()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            album = root / "Folder 1"
            disc = album / "Folder 2"
            disc.mkdir(parents=True)
            direct_midi = root / "root.mid"
            nested_midi = album / "nested.MIDI"
            deep_midi = disc / "deep.mid"
            ignored = disc / "notes.txt"
            for path in (direct_midi, nested_midi, deep_midi, ignored):
                path.write_bytes(b"test")

            with (
                patch.object(controller, "_start_metadata_scan") as metadata_scan,
                patch.object(controller, "select_midi") as select_midi,
            ):
                controller.load_midi_folder(root, save_folder=False)

        self.assertEqual(
            controller.midi_files,
            [direct_midi, nested_midi, deep_midi],
        )
        self.assertEqual(
            [(row.name, row.folder) for row in controller.state.midi_rows],
            [
                ("root.mid", root.name),
                ("nested.MIDI", f"{root.name} > Folder 1"),
                ("deep.mid", f"{root.name} > Folder 1 > Folder 2"),
            ],
        )
        metadata_scan.assert_called_once_with(controller.midi_files)
        select_midi.assert_called_once_with(0)

    def test_removed_duplicate_filename_does_not_select_another_folder(self) -> None:
        controller = self.make_controller()
        controller.midi_files = [
            Path("Folder 1") / "song.mid",
            Path("Folder 2") / "song.mid",
        ]

        self.assertEqual(
            controller._find_midi_index(Path("Removed") / "song.mid"),
            -1,
        )

    def test_keyboard_playback_receives_state_settings(self) -> None:
        controller = self.make_controller(
            countdown_seconds=4,
            playback_speed_percent=125,
            transpose_semitones=3,
            octave_shift=-1,
            humanize_timing=True,
            chord_optimization=True,
            repeat_prevention=True,
            sound_source="organ",
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

    def test_realtime_input_does_not_block_midi_sound_playback(self) -> None:
        controller = self.make_controller(sound_source="synth")
        controller.state.midi_input_running = True
        realtime_output = FakeRealtimeSoundOutput()
        controller.realtime_sound_output = realtime_output
        controller.events = [MidiEvent(0.0, "note_on", 0, 60, 80, track=0)]
        controller.summary = MidiSummary(
            path=Path("song.mid"),
            duration=1.0,
            channels=(0,),
            event_count=1,
            tracks=(MidiTrackSummary(index=0, channels=(0,)),),
        )
        controller._set_enabled_sources(((0, 0),))

        with patch("app_controller.MidiSoundPlayer", FakePlayer):
            controller.toggle_sound_playback()

        self.assertEqual(controller.state.current_mode, "sound")
        self.assertTrue(controller.state.midi_input_running)
        self.assertIsNotNone(FakePlayer.instance)
        self.assertEqual(FakePlayer.instance.play_args[0], controller.events)
        self.assertEqual(FakePlayer.instance.kwargs["sound_source"], "synth")
        self.assertIn("on_audio_runtime_changed", FakePlayer.instance.kwargs)
        self.assertEqual(realtime_output.enabled_calls, [])

        FakePlayer.instance.kwargs["on_output_note"](64, True)
        controller.process_pending_events()
        self.assertEqual(controller.state.active_output_notes, frozenset((64,)))

        controller._set_output_note_state(("midi", controller.midi_input_id), 60, True)
        controller.stop_playback()

        self.assertEqual(realtime_output.enabled_calls, [])
        self.assertEqual(controller.state.active_output_notes, frozenset((60,)))

    def test_midi_input_mode_state_does_not_block_midi_sound_playback(self) -> None:
        controller = self.make_controller()
        controller.state.current_mode = "midi_input"
        controller.state.midi_input_running = True
        controller.events = [MidiEvent(0.0, "note_on", 0, 60, 80, track=0)]
        controller.summary = MidiSummary(
            path=Path("song.mid"),
            duration=1.0,
            channels=(0,),
            event_count=1,
            tracks=(MidiTrackSummary(index=0, channels=(0,)),),
        )
        controller._set_enabled_sources(((0, 0),))

        with patch("app_controller.MidiSoundPlayer", FakePlayer):
            controller.toggle_sound_playback()

        self.assertEqual(controller.state.current_mode, "sound")
        self.assertTrue(controller.state.midi_input_running)

    def test_selecting_midi_during_realtime_input_does_not_stop_before_sound_playback(self) -> None:
        controller = self.make_controller()
        controller.state.current_mode = "midi_input"
        controller.state.midi_input_running = True
        with tempfile.TemporaryDirectory() as temporary_directory:
            midi_path = Path(temporary_directory) / "song.mid"
            midi_path.write_bytes(b"midi")
            controller.midi_files = [midi_path]
            summary = MidiSummary(
                path=midi_path,
                duration=1.0,
                channels=(0,),
                event_count=1,
                tracks=(MidiTrackSummary(index=0, channels=(0,)),),
            )
            events = [MidiEvent(0.0, "note_on", 0, 60, 80, track=0)]

            with (
                patch("app_controller.parse_midi", return_value=(events, summary)),
                patch.object(controller, "stop_playback") as stop_playback,
            ):
                controller.select_midi(0)

        stop_playback.assert_not_called()
        self.assertEqual(controller.state.current_mode, "midi_input")
        self.assertTrue(controller.state.midi_input_running)
        self.assertEqual(controller.events, events)

    def test_event_dispatch_ignores_stale_playback_messages(self) -> None:
        controller = self.make_controller()
        controller.playback_id = 5
        controller.state.status = "waiting.."
        controller.worker_queue.put(("key_state", 4, "playing"))

        controller.process_pending_events()

        self.assertEqual(controller.state.status, "waiting..")

    def test_event_dispatch_tracks_final_output_notes_and_ignores_stale_generations(self) -> None:
        controller = self.make_controller()
        controller.playback_id = 5
        controller.midi_input_id = 8
        controller.worker_queue.put(("key_output_note", 5, 60, True))
        controller.worker_queue.put(("key_output_note", 4, 61, True))
        controller.worker_queue.put(("sound_output_note", 5, 67, True))
        controller.worker_queue.put(("sound_output_note", 4, 68, True))
        controller.worker_queue.put(("midi_output_note", 8, 64, True))
        controller.worker_queue.put(("midi_output_note", 7, 65, True))

        controller.process_pending_events()

        self.assertEqual(controller.state.active_output_notes, frozenset((60, 64, 67)))

        controller._output_note_visible_until = {60: 0.0, 64: 0.0, 67: 0.0}
        controller.worker_queue.put(("key_output_note", 5, 60, False))
        controller.worker_queue.put(("sound_output_note", 5, 67, False))
        controller.worker_queue.put(("midi_output_note", 8, 64, False))
        controller.process_pending_events()

        self.assertEqual(controller.state.active_output_notes, frozenset())

    def test_event_dispatch_tracks_full_piano_range_for_every_output_source(self) -> None:
        controller = self.make_controller()
        controller.playback_id = 5
        controller.midi_input_id = 8
        controller.worker_queue.put(("key_output_note", 5, 21, True))
        controller.worker_queue.put(("sound_output_note", 5, 108, True))
        controller.worker_queue.put(("midi_output_note", 8, 22, True))
        controller.worker_queue.put(("sound_output_note", 5, 20, True))
        controller.worker_queue.put(("sound_output_note", 5, 109, True))

        controller.process_pending_events()

        self.assertEqual(controller.state.active_output_notes, frozenset((21, 22, 108)))

    def test_realtime_output_tracks_each_trigger_separately_from_playback(self) -> None:
        controller = self.make_controller()
        controller.playback_id = 5
        controller.midi_input_id = 8
        controller.worker_queue.put(("sound_output_note", 5, 60, True))
        controller.worker_queue.put(("midi_output_note", 8, 60, True))
        controller.process_pending_events()

        self.assertEqual(controller.state.active_output_notes, frozenset((60,)))
        self.assertEqual(controller.state.realtime_output_notes, frozenset((60,)))
        self.assertEqual(controller.state.realtime_note_trigger_events, ((60, 1),))

        controller.worker_queue.put(("midi_output_note", 8, 60, False))
        controller.worker_queue.put(("midi_output_note", 8, 60, True))
        controller.process_pending_events()

        self.assertEqual(controller.state.realtime_output_notes, frozenset((60,)))
        self.assertEqual(controller.state.realtime_note_trigger_events, ((60, 2),))

        controller.worker_queue.put(("midi_output_note", 8, 60, False))
        controller.process_pending_events()
        self.assertEqual(controller.state.active_output_notes, frozenset((60,)))
        self.assertEqual(controller.state.realtime_output_notes, frozenset())

    def test_same_note_stays_visible_until_sound_and_realtime_input_release_it(self) -> None:
        controller = self.make_controller()
        controller.playback_id = 3
        controller.midi_input_id = 4
        controller.worker_queue.put(("sound_output_note", 3, 60, True))
        controller.worker_queue.put(("midi_output_note", 4, 60, True))
        controller.process_pending_events()

        controller._output_note_visible_until[60] = 0.0
        controller.worker_queue.put(("sound_output_note", 3, 60, False))
        controller.process_pending_events()

        self.assertEqual(controller.state.active_output_notes, frozenset((60,)))

        controller.worker_queue.put(("midi_output_note", 4, 60, False))
        controller.process_pending_events()

        self.assertEqual(controller.state.active_output_notes, frozenset())

    def test_retriggering_an_active_note_emits_a_visual_event(self) -> None:
        controller = self.make_controller()
        controller.playback_id = 3
        controller.worker_queue.put(("sound_output_note", 3, 60, True))
        controller.process_pending_events()

        controller.worker_queue.put(("sound_output_note", 3, 60, True))
        controller.process_pending_events()

        self.assertEqual(controller.state.active_output_notes, frozenset((60,)))
        self.assertEqual(controller.state.output_note_retrigger_events, ((60, 1),))
        self.assertEqual(controller.state.output_note_retrigger_serial, 1)

    def test_note_off_then_on_in_one_dispatch_emits_a_visual_retrigger(self) -> None:
        controller = self.make_controller()
        controller.playback_id = 3
        controller.worker_queue.put(("key_output_note", 3, 60, True))
        controller.process_pending_events()
        controller._output_note_visible_until[60] = 0.0

        controller.worker_queue.put(("key_output_note", 3, 60, False))
        controller.worker_queue.put(("key_output_note", 3, 60, True))
        controller.process_pending_events()

        self.assertEqual(controller.state.active_output_notes, frozenset((60,)))
        self.assertEqual(controller.state.output_note_retrigger_events, ((60, 1),))
        self.assertEqual(controller.state.output_note_retrigger_serial, 1)

    def test_simultaneous_retriggers_emit_a_visual_event_for_every_note(self) -> None:
        controller = self.make_controller()
        controller.playback_id = 3
        for note in (60, 64, 67):
            controller.worker_queue.put(("sound_output_note", 3, note, True))
        controller.process_pending_events()

        for note in (60, 64, 67):
            controller.worker_queue.put(("sound_output_note", 3, note, True))
        controller.process_pending_events()

        self.assertEqual(
            controller.state.output_note_retrigger_events,
            ((60, 1), (64, 2), (67, 3)),
        )

    def test_short_final_output_note_remains_visible_for_one_frame(self) -> None:
        controller = self.make_controller()
        controller.playback_id = 2
        controller.worker_queue.put(("key_output_note", 2, 60, True))
        controller.worker_queue.put(("key_output_note", 2, 60, False))

        controller.process_pending_events()

        self.assertEqual(controller.state.active_output_notes, frozenset((60,)))
        controller._output_note_release_due[60] = 0.0
        controller.process_pending_events()
        self.assertEqual(controller.state.active_output_notes, frozenset())

    def test_short_realtime_note_remains_visible_for_one_frame(self) -> None:
        controller = self.make_controller()
        controller.midi_input_id = 2
        controller.worker_queue.put(("midi_output_note", 2, 60, True))
        controller.worker_queue.put(("midi_output_note", 2, 60, False))

        controller.process_pending_events()

        self.assertEqual(
            controller.state.realtime_visible_output_notes,
            frozenset((60,)),
        )
        controller._realtime_note_release_due[60] = 0.0
        controller.process_pending_events()
        self.assertEqual(
            controller.state.realtime_visible_output_notes,
            frozenset(),
        )

    def test_simultaneous_sound_and_realtime_events_update_score_and_combo(self) -> None:
        controller = self.make_controller()
        controller.playback_id = 3
        controller.midi_input_id = 4
        controller.state.current_mode = "sound"
        controller.state.midi_input_running = True
        controller.worker_queue.put(("sound_output_note", 3, 60, True, 10.0))
        controller.worker_queue.put(("midi_output_note", 4, 60, True, 10.1))

        with patch("app_controller.time.monotonic", return_value=10.1):
            controller.process_pending_events()

        self.assertEqual(controller.state.rhythm_score, 70)
        self.assertEqual(controller.state.rhythm_combo, 1)
        self.assertEqual(controller.state.rhythm_judgment, "GREAT")
        self.assertEqual(controller.state.rhythm_multiplier_tenths, 10)
        self.assertEqual(
            controller.state.rhythm_hit_events,
            ((1, 60, "GREAT", False),),
        )

    def test_release_timing_adds_score_and_emits_an_effect_event(self) -> None:
        controller = self.make_controller()
        controller.playback_id = 3
        controller.midi_input_id = 4
        controller.state.current_mode = "sound"
        controller.state.midi_input_running = True
        controller.worker_queue.put(("sound_output_note", 3, 60, True, 10.0))
        controller.worker_queue.put(("midi_output_note", 4, 60, True, 10.0))
        controller.worker_queue.put(("sound_output_note", 3, 60, False, 11.0))
        controller.worker_queue.put(("midi_output_note", 4, 60, False, 11.1))

        with patch("app_controller.time.monotonic", return_value=11.1):
            controller.process_pending_events()

        self.assertEqual(controller.state.rhythm_score, 270)
        self.assertEqual(controller.state.rhythm_combo, 2)
        self.assertEqual(controller.state.rhythm_judgment, "GREAT")
        self.assertEqual(
            controller.state.rhythm_hit_events,
            (
                (1, 60, "PERFECT", False),
                (2, 60, "GREAT", True),
            ),
        )

    def test_missed_release_resets_combo(self) -> None:
        controller = self.make_controller()
        controller.playback_id = 3
        controller.midi_input_id = 4
        controller.state.current_mode = "sound"
        controller.state.midi_input_running = True
        controller.worker_queue.put(("sound_output_note", 3, 60, True, 10.0))
        controller.worker_queue.put(("midi_output_note", 4, 60, True, 10.0))
        controller.worker_queue.put(("sound_output_note", 3, 60, False, 11.0))

        with patch("app_controller.time.monotonic", return_value=11.0):
            controller.process_pending_events()
        with patch("app_controller.time.monotonic", return_value=11.151):
            controller.process_pending_events()

        self.assertEqual(controller.state.rhythm_score, 200)
        self.assertEqual(controller.state.rhythm_combo, 0)
        self.assertEqual(controller.state.rhythm_judgment, "MISS")
        self.assertEqual(
            controller.state.rhythm_hit_events[-1],
            (2, 60, "MISS", True),
        )

    def test_simultaneous_scored_chord_preserves_every_hit_effect_event(self) -> None:
        controller = self.make_controller()
        controller.playback_id = 3
        controller.midi_input_id = 4
        controller.state.current_mode = "sound"
        controller.state.midi_input_running = True
        for note in (60, 64, 67):
            controller.worker_queue.put(
                ("sound_output_note", 3, note, True, 10.0)
            )
            controller.worker_queue.put(
                ("midi_output_note", 4, note, True, 10.0)
            )

        with patch("app_controller.time.monotonic", return_value=10.0):
            controller.process_pending_events()

        self.assertEqual(controller.state.rhythm_score, 300)
        self.assertEqual(controller.state.rhythm_combo, 3)
        self.assertEqual(
            controller.state.rhythm_hit_events,
            (
                (1, 60, "PERFECT", False),
                (2, 64, "PERFECT", False),
                (3, 67, "PERFECT", False),
            ),
        )

    def test_midi_playback_without_realtime_input_scores_automatic_perfect(
        self,
    ) -> None:
        controller = self.make_controller()
        controller.playback_id = 3
        controller.state.current_mode = "sound"
        controller.worker_queue.put(("sound_output_note", 3, 60, True, 10.0))
        controller.worker_queue.put(("sound_output_note", 3, 60, False, 11.0))

        with patch("app_controller.time.monotonic", return_value=11.0):
            controller.process_pending_events()

        self.assertEqual(controller.state.rhythm_score, 300)
        self.assertEqual(controller.state.rhythm_combo, 2)
        self.assertEqual(controller.state.rhythm_judgment, "PERFECT")
        self.assertEqual(
            controller.state.rhythm_hit_events,
            (
                (1, 60, "PERFECT", False),
                (2, 60, "PERFECT", True),
            ),
        )

    def test_midi_input_conversion_scores_automatic_perfect(self) -> None:
        controller = self.make_controller()
        controller.playback_id = 3
        controller.state.current_mode = "keys"
        controller.worker_queue.put(("key_output_note", 3, 60, True, 10.0))
        controller.worker_queue.put(("key_output_note", 3, 60, False, 11.0))

        with patch("app_controller.time.monotonic", return_value=11.0):
            controller.process_pending_events()

        self.assertEqual(controller.state.rhythm_score, 300)
        self.assertEqual(controller.state.rhythm_combo, 2)
        self.assertEqual(controller.state.rhythm_judgment, "PERFECT")
        self.assertEqual(
            controller.state.rhythm_hit_events,
            (
                (1, 60, "PERFECT", False),
                (2, 60, "PERFECT", True),
            ),
        )

    def test_hold_score_updates_from_a_single_shot_view_timer(self) -> None:
        controller = self.make_controller()
        view = RecordingView()
        controller.attach_view(view)
        controller.playback_id = 3
        controller.midi_input_id = 4
        controller.state.current_mode = "sound"
        controller.state.midi_input_running = True
        controller.worker_queue.put(("sound_output_note", 3, 60, True, 10.0))
        controller.worker_queue.put(("midi_output_note", 4, 60, True, 10.0))

        with patch("app_controller.time.monotonic", return_value=10.0):
            controller.process_pending_events()

        self.assertEqual(controller.state.rhythm_score, 100)
        self.assertEqual(controller.state.rhythm_combo, 1)
        self.assertEqual(view.rhythm_score_delays[-1], 100)

        with patch("app_controller.time.monotonic", return_value=10.1):
            controller.process_rhythm_score_update()

        self.assertEqual(controller.state.rhythm_score, 110)
        self.assertEqual(controller.state.rhythm_combo, 1)
        self.assertEqual(view.rhythm_score_delays[-1], 100)

    def test_hidden_rhythm_game_skips_automatic_scoring(self) -> None:
        controller = self.make_controller()
        controller.playback_id = 3
        controller.state.current_mode = "sound"
        controller.set_section_visible("piano_roll", False)
        controller.worker_queue.put(("sound_output_note", 3, 60, True, 10.0))
        controller.worker_queue.put(("sound_output_note", 3, 60, False, 11.0))

        with patch("app_controller.time.monotonic", return_value=11.0):
            controller.process_pending_events()

        self.assertEqual(controller.state.rhythm_score, 0)
        self.assertEqual(controller.state.rhythm_combo, 0)
        self.assertEqual(controller.state.rhythm_hit_events, ())

    def test_hiding_rhythm_game_cancels_pending_scoring_until_reshown(
        self,
    ) -> None:
        controller = self.make_controller()
        view = RecordingView()
        controller.attach_view(view)
        controller.playback_id = 3
        controller.midi_input_id = 4
        controller.state.current_mode = "sound"
        controller.state.midi_input_running = True
        controller.worker_queue.put(("sound_output_note", 3, 60, True, 10.0))
        controller.worker_queue.put(("midi_output_note", 4, 60, True, 10.0))

        with patch("app_controller.time.monotonic", return_value=10.0):
            controller.process_pending_events()

        self.assertEqual(controller.state.rhythm_score, 100)
        self.assertTrue(controller._rhythm_scorer.has_active_holds)

        controller.set_section_visible("piano_roll", False)
        self.assertIsNone(view.rhythm_score_delays[-1])
        self.assertFalse(controller._rhythm_scorer.has_active_holds)

        with patch("app_controller.time.monotonic", return_value=10.5):
            controller.process_rhythm_score_update()
        self.assertEqual(controller.state.rhythm_score, 100)
        self.assertEqual(controller.state.rhythm_hit_events, ((1, 60, "PERFECT", False),))
        self.assertIsNone(view.rhythm_score_delays[-1])

        controller.set_section_visible("piano_roll", True)
        controller.worker_queue.put(("sound_output_note", 3, 64, True, 11.0))
        controller.worker_queue.put(("midi_output_note", 4, 64, True, 11.0))
        with patch("app_controller.time.monotonic", return_value=11.0):
            controller.process_pending_events()

        self.assertGreater(controller.state.rhythm_score, 100)
        self.assertEqual(controller.state.rhythm_hit_events[-1][1:], (64, "PERFECT", False))

    def test_pending_note_timer_displays_miss_without_another_midi_event(
        self,
    ) -> None:
        controller = self.make_controller()
        view = RecordingView()
        controller.attach_view(view)
        controller.playback_id = 3
        controller.midi_input_id = 4
        controller.state.current_mode = "sound"
        controller.state.midi_input_running = True
        controller.worker_queue.put(("sound_output_note", 3, 60, True, 10.0))

        with patch("app_controller.time.monotonic", return_value=10.0):
            controller.process_pending_events()

        self.assertEqual(view.rhythm_score_delays[-1], 151)

        with patch("app_controller.time.monotonic", return_value=10.151):
            controller.process_rhythm_score_update()

        self.assertEqual(controller.state.rhythm_judgment, "MISS")
        self.assertEqual(controller.state.rhythm_combo, 0)
        self.assertEqual(
            controller.state.rhythm_hit_events,
            ((1, 60, "MISS", False),),
        )
        self.assertIsNone(view.rhythm_score_delays[-1])

    def test_stopping_playback_cancels_pending_rhythm_updates(self) -> None:
        controller = self.make_controller()
        view = RecordingView()
        controller.attach_view(view)
        controller.playback_id = 3
        controller.state.current_mode = "keys"
        controller.worker_queue.put(("key_output_note", 3, 60, True, 10.0))

        with patch("app_controller.time.monotonic", return_value=10.0):
            controller.process_pending_events()

        self.assertEqual(view.rhythm_score_delays[-1], 100)
        controller.stop_playback()

        self.assertIsNone(view.rhythm_score_delays[-1])
        self.assertFalse(controller._rhythm_scorer.has_active_holds)

    def test_realtime_input_without_midi_playback_does_not_score(self) -> None:
        controller = self.make_controller()
        controller.midi_input_id = 4
        controller.state.midi_input_running = True
        controller.worker_queue.put(("midi_output_note", 4, 60, True, 10.0))

        with patch("app_controller.time.monotonic", return_value=10.0):
            controller.process_pending_events()

        self.assertEqual(controller.state.rhythm_score, 0)
        self.assertEqual(controller.state.rhythm_combo, 0)
        self.assertEqual(controller.state.rhythm_hit_events, ())

    def test_sound_note_remap_updates_visuals_without_adding_score(self) -> None:
        controller = self.make_controller()
        controller.playback_id = 3
        controller.midi_input_id = 4
        controller.state.current_mode = "sound"
        controller.state.midi_input_running = True
        controller.worker_queue.put(("sound_output_remap", 3, 48, True))
        controller.worker_queue.put(("midi_output_note", 4, 48, True, 10.0))

        with patch("app_controller.time.monotonic", return_value=10.0):
            controller.process_pending_events()

        self.assertIn(48, controller.state.active_output_notes)
        self.assertEqual(controller.state.rhythm_score, 0)
        self.assertEqual(controller.state.rhythm_combo, 0)

    def test_stopping_realtime_input_clears_displayed_output_notes(self) -> None:
        controller = self.make_controller()
        controller.state.midi_input_running = True
        for note in (48, 60, 72):
            controller._set_output_note_state(("midi", controller.midi_input_id), note, True)

        controller.stop_midi_input()

        self.assertEqual(controller.state.active_output_notes, frozenset())

    def test_note_range_format_is_standard_midi_notation(self) -> None:
        self.assertEqual(AppController.format_note_range((36, 85)), "C2-C#6")


if __name__ == "__main__":
    unittest.main()
