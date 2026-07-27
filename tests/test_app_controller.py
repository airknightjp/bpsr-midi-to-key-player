from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

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
from source_colors import track_channel_color


class RecordingView:
    def __init__(self) -> None:
        self.states = []
        self.positions: list[tuple[float, float]] = []
        self.messages: list[tuple[str, str, str]] = []
        self.output_release_delays: list[int] = []

    def render(self, state) -> None:  # type: ignore[no-untyped-def]
        self.states.append(state)

    def render_position(self, position: float, duration: float) -> None:
        self.positions.append((position, duration))

    def show_message(self, level: str, title: str, message: str) -> None:
        self.messages.append((level, title, message))

    def schedule_output_note_release(self, delay_ms: int) -> None:
        self.output_release_delays.append(delay_ms)


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

    def test_controller_has_no_qt_dependency(self) -> None:
        source = inspect.getsource(app_controller)
        self.assertNotIn("PySide6", source)

    def test_cached_piano_arrangement_drives_sound_and_key_conversion(self) -> None:
        controller = self.make_controller(play_sound=False)
        path = Path("arranged.mid")
        source_events = [
            MidiEvent(0.0, "note_on", 0, 60, 80, track=0, note_id=0),
            MidiEvent(1.0, "note_off", 0, 60, 0, track=0, note_id=0),
        ]
        arranged_events = [
            MidiEvent(0.0, "note_on", 0, 72, 90, track=0, note_id=10),
            MidiEvent(1.0, "note_off", 0, 72, 0, track=0, note_id=10),
            MidiEvent(1.0, "end"),
        ]
        summary = MidiSummary(
            path=path,
            duration=1.0,
            channels=(0,),
            event_count=2,
            tracks=(MidiTrackSummary(0, (0,)),),
            note_range=(60, 60),
            file_hash="a" * 64,
        )
        cached_plan = MagicMock()
        cached_plan.duration = 1.0
        cached_plan.to_midi_events.return_value = arranged_events
        with (
            patch.object(
                controller.midi_parser_process,
                "parse",
                return_value=(source_events, summary),
            ),
            patch(
                "app_controller.cached_piano_arrangement",
                return_value=cached_plan,
            ),
        ):
            self.assertTrue(controller._load_midi_file(path, stop_playback=False))

        self.assertIs(controller.source_events, source_events)
        self.assertIs(controller.events, arranged_events)
        self.assertEqual(controller.state.arrangement_status, "ready")

        with (
            patch("app_controller.MidiKeyboardPlayer", FakePlayer),
            patch("app_controller.KeyboardOutput"),
        ):
            controller.play_keyboard(countdown=False)
        self.assertIs(FakePlayer.instance.play_args[0], arranged_events)
        controller.stop_playback()

        with patch("app_controller.MidiSoundPlayer", FakePlayer):
            controller.play_sound(start_time=0.0)
        self.assertIs(FakePlayer.instance.play_args[0], arranged_events)

    def test_arrangement_setting_switches_between_source_and_cached_events(
        self,
    ) -> None:
        controller = self.make_controller(use_piano_arrangement=False)
        path = Path("arranged.mid")
        source_events = [
            MidiEvent(0.0, "note_on", 0, 60, 80, track=0, note_id=0),
            MidiEvent(1.0, "note_off", 0, 60, 0, track=0, note_id=0),
        ]
        arranged_events = [
            MidiEvent(0.0, "note_on", 0, 72, 90, track=0, note_id=10),
            MidiEvent(1.0, "note_off", 0, 72, 0, track=0, note_id=10),
            MidiEvent(1.0, "end"),
        ]
        summary = MidiSummary(
            path=path,
            duration=1.0,
            channels=(0,),
            event_count=2,
            tracks=(MidiTrackSummary(0, (0,)),),
            note_range=(60, 60),
            file_hash="a" * 64,
        )
        cached_plan = MagicMock()
        cached_plan.duration = 1.0
        cached_plan.to_midi_events.return_value = arranged_events
        with (
            patch.object(
                controller.midi_parser_process,
                "parse",
                return_value=(source_events, summary),
            ),
            patch(
                "app_controller.cached_piano_arrangement",
                return_value=cached_plan,
            ),
        ):
            self.assertTrue(
                controller._load_midi_file(path, stop_playback=False)
            )
            self.assertIs(controller.events, source_events)
            controller.set_option("use_piano_arrangement", True)
            self.assertIs(controller.events, arranged_events)
            controller.set_option("use_piano_arrangement", False)
            self.assertIs(controller.events, source_events)

        self.assertFalse(
            controller.current_settings().use_piano_arrangement
        )

    def test_arrangement_checkbox_switches_sound_playback_immediately(
        self,
    ) -> None:
        controller = self.make_controller(use_piano_arrangement=False)
        source_events = [
            MidiEvent(0.0, "note_on", 0, 60, 80, track=0, note_id=0),
            MidiEvent(1.0, "note_off", 0, 60, 0, track=0, note_id=0),
        ]
        arranged_events = [
            MidiEvent(0.0, "note_on", 0, 72, 90, track=0, note_id=10),
            MidiEvent(1.0, "note_off", 0, 72, 0, track=0, note_id=10),
            MidiEvent(1.0, "end"),
        ]
        controller.source_events = source_events
        controller.events = source_events
        controller.summary = MidiSummary(
            path=Path("current.mid"),
            duration=1.0,
            channels=(0,),
            event_count=2,
            tracks=(MidiTrackSummary(0, (0,)),),
            file_hash="b" * 64,
        )
        controller.state.current_mode = "sound"
        controller.sound_player = MagicMock()
        controller.sound_player.is_playing = True
        controller.sound_player.current_position.return_value = 0.4
        plan = MagicMock()
        plan.duration = 1.0
        plan.to_midi_events.return_value = arranged_events

        with patch(
            "app_controller.cached_piano_arrangement",
            return_value=plan,
        ):
            controller.set_option("use_piano_arrangement", True)
            controller.set_option("use_piano_arrangement", False)

        self.assertEqual(
            controller.sound_player.switch.call_args_list,
            [
                call(arranged_events, start_time=0.4),
                call(source_events, start_time=0.4),
            ],
        )
        self.assertIs(controller.events, source_events)

    def test_arrangement_checkbox_restarts_keyboard_conversion_immediately(
        self,
    ) -> None:
        controller = self.make_controller(use_piano_arrangement=False)
        source_events = [
            MidiEvent(0.0, "note_on", 0, 60, 80, track=0, note_id=0),
            MidiEvent(1.0, "note_off", 0, 60, 0, track=0, note_id=0),
        ]
        arranged_events = [
            MidiEvent(0.0, "note_on", 0, 72, 90, track=0, note_id=10),
            MidiEvent(1.0, "note_off", 0, 72, 0, track=0, note_id=10),
            MidiEvent(1.0, "end"),
        ]
        controller.source_events = source_events
        controller.events = source_events
        controller.summary = MidiSummary(
            path=Path("current.mid"),
            duration=1.0,
            channels=(0,),
            event_count=2,
            tracks=(MidiTrackSummary(0, (0,)),),
            file_hash="b" * 64,
        )
        controller.state.current_mode = "keys"
        controller.player = MagicMock()
        controller.player.is_playing = True
        controller.player.current_position.return_value = 0.6
        plan = MagicMock()
        plan.duration = 1.0
        plan.to_midi_events.return_value = arranged_events

        with (
            patch(
                "app_controller.cached_piano_arrangement",
                return_value=plan,
            ),
            patch.object(controller, "seek") as seek,
        ):
            controller.set_option("use_piano_arrangement", True)

        self.assertIs(controller.events, arranged_events)
        seek.assert_called_once_with(0.6)

    def test_stale_arrangement_completion_is_not_applied_to_another_midi(self) -> None:
        controller = self.make_controller()
        controller.summary = MidiSummary(
            path=Path("current.mid"),
            duration=1.0,
            channels=(0,),
            event_count=0,
            file_hash="b" * 64,
        )
        controller.state.arrangement_status = "analyzing"
        controller.worker_queue.put(
            (
                "arrangement_complete",
                "a" * 64,
                controller.current_piano_arrangement_config().cache_key(),
            )
        )

        controller.process_pending_events()

        self.assertEqual(controller.state.arrangement_status, "idle")
        self.assertIsNone(controller.arrangement_plan)

    def test_arrangement_can_run_in_every_playback_state(self) -> None:
        for current_mode, midi_input_running in (
            (None, False),
            ("sound", False),
            ("sound_paused", False),
            ("keys", False),
            ("keys_paused", False),
            (None, True),
            ("sound", True),
        ):
            with self.subTest(
                current_mode=current_mode,
                midi_input_running=midi_input_running,
            ):
                controller = self.make_controller()
                controller.summary = MidiSummary(
                    path=Path("current.mid"),
                    duration=1.0,
                    channels=(0,),
                    event_count=0,
                    file_hash="b" * 64,
                )
                controller.state.current_mode = current_mode
                controller.state.midi_input_running = midi_input_running

                with patch.object(
                    controller.piano_arrangement_process,
                    "start",
                ) as start:
                    controller.analyze_selected_midi()

                start.assert_called_once()
                self.assertEqual(
                    controller.state.arrangement_status,
                    "analyzing",
                )

    def test_arrangement_completed_during_sound_playback_applies_immediately(
        self,
    ) -> None:
        controller = self.make_controller()
        source_events = [
            MidiEvent(0.0, "note_on", 0, 60, 80, track=0, note_id=0),
            MidiEvent(1.0, "note_off", 0, 60, 0, track=0, note_id=0),
        ]
        arranged_events = [
            MidiEvent(0.0, "note_on", 0, 72, 90, track=0, note_id=10),
            MidiEvent(1.0, "note_off", 0, 72, 0, track=0, note_id=10),
            MidiEvent(1.0, "end"),
        ]
        controller.source_events = source_events
        controller.events = source_events
        controller.summary = MidiSummary(
            path=Path("current.mid"),
            duration=1.0,
            channels=(0,),
            event_count=2,
            tracks=(MidiTrackSummary(0, (0,)),),
            file_hash="b" * 64,
        )
        controller._set_enabled_sources(((0, 0),))
        controller.state.current_mode = "sound"
        controller.state.position = 0.25
        controller.state.arrangement_status = "analyzing"
        controller.sound_player = MagicMock()
        controller.sound_player.is_playing = True
        controller.sound_player.current_position.return_value = 0.4
        controller.worker_queue.put(
            (
                "arrangement_complete",
                "b" * 64,
                controller.current_piano_arrangement_config().cache_key(),
            )
        )
        plan = MagicMock()
        plan.duration = 1.0
        plan.to_midi_events.return_value = arranged_events

        with patch(
            "app_controller.cached_piano_arrangement",
            return_value=plan,
        ) as load_cache:
            controller.process_pending_events()
            load_cache.assert_called_once()
            self.assertIs(controller.events, arranged_events)
            self.assertEqual(
                controller.state.arrangement_status,
                "ready",
            )
            controller.sound_player.switch.assert_called_once_with(
                arranged_events,
                start_time=0.4,
            )

    def test_arrangement_completion_does_not_restart_source_when_use_is_off(
        self,
    ) -> None:
        controller = self.make_controller(use_piano_arrangement=False)
        source_events = [
            MidiEvent(0.0, "note_on", 0, 60, 80, track=0, note_id=0),
            MidiEvent(1.0, "note_off", 0, 60, 0, track=0, note_id=0),
        ]
        controller.source_events = source_events
        controller.events = source_events
        controller.summary = MidiSummary(
            path=Path("current.mid"),
            duration=1.0,
            channels=(0,),
            event_count=2,
            tracks=(MidiTrackSummary(0, (0,)),),
            file_hash="b" * 64,
        )
        controller.state.current_mode = "sound"
        controller.state.arrangement_status = "analyzing"
        controller.sound_player = MagicMock()
        controller.sound_player.is_playing = True
        controller.worker_queue.put(
            (
                "arrangement_complete",
                "b" * 64,
                controller.current_piano_arrangement_config().cache_key(),
            )
        )
        plan = MagicMock()
        plan.duration = 1.0

        with patch(
            "app_controller.cached_piano_arrangement",
            return_value=plan,
        ):
            controller.process_pending_events()

        self.assertIs(controller.events, source_events)
        controller.sound_player.switch.assert_not_called()
        self.assertEqual(controller.state.arrangement_status, "ready")

    def test_arrangement_completed_during_keyboard_conversion_applies_immediately(
        self,
    ) -> None:
        controller = self.make_controller()
        source_events = [
            MidiEvent(0.0, "note_on", 0, 60, 80, track=0, note_id=0),
            MidiEvent(1.0, "note_off", 0, 60, 0, track=0, note_id=0),
        ]
        arranged_events = [
            MidiEvent(0.0, "note_on", 0, 72, 90, track=0, note_id=10),
            MidiEvent(1.0, "note_off", 0, 72, 0, track=0, note_id=10),
            MidiEvent(1.0, "end"),
        ]
        controller.source_events = source_events
        controller.events = source_events
        controller.summary = MidiSummary(
            path=Path("current.mid"),
            duration=1.0,
            channels=(0,),
            event_count=2,
            tracks=(MidiTrackSummary(0, (0,)),),
            file_hash="b" * 64,
        )
        controller.state.current_mode = "keys"
        controller.state.arrangement_status = "analyzing"
        controller.player = MagicMock()
        controller.player.is_playing = True
        controller.player.current_position.return_value = 0.6
        controller.worker_queue.put(
            (
                "arrangement_complete",
                "b" * 64,
                controller.current_piano_arrangement_config().cache_key(),
            )
        )
        plan = MagicMock()
        plan.duration = 1.0
        plan.to_midi_events.return_value = arranged_events

        with (
            patch(
                "app_controller.cached_piano_arrangement",
                return_value=plan,
            ),
            patch.object(controller, "seek") as seek,
        ):
            controller.process_pending_events()

        self.assertIs(controller.events, arranged_events)
        seek.assert_called_once_with(0.6)
        self.assertEqual(controller.state.arrangement_status, "ready")

    def test_worker_messages_coalesce_event_dispatch_notifications(self) -> None:
        controller = self.make_controller()
        notifications: list[bool] = []
        controller.set_event_notifier(lambda: notifications.append(True))

        generation = controller.position_generation
        controller._queue_worker_message(("position", 0, generation, 1.0))
        controller._queue_worker_message(("position", 0, generation, 2.0))

        self.assertEqual(notifications, [True])
        controller.process_pending_events()
        controller._queue_worker_message(("position", 0, generation, 3.0))
        self.assertEqual(notifications, [True, True])

    def test_realtime_timing_emits_great_without_score_state(self) -> None:
        controller = self.make_controller()
        controller.playback_id = 3
        controller.midi_input_id = 4
        controller.state.current_mode = "sound"
        controller.state.midi_input_running = True
        controller.worker_queue.put(
            ("sound_output_note", 3, 60, True, 10.0)
        )
        controller.worker_queue.put(
            ("midi_output_note", 4, 60, True, 10.075)
        )

        controller.process_pending_events()

        self.assertEqual(
            controller.state.rhythm_hit_events,
            ((1, 60, "GREAT", False),),
        )
        self.assertFalse(hasattr(controller.state, "rhythm_score"))
        self.assertFalse(hasattr(controller.state, "rhythm_combo"))

    def test_midi_only_and_conversion_events_are_automatic_perfect(self) -> None:
        controller = self.make_controller()
        controller.playback_id = 3
        controller.state.current_mode = "sound"
        controller.worker_queue.put(
            ("sound_output_note", 3, 60, True, 10.0)
        )
        controller.worker_queue.put(
            ("sound_output_note", 3, 60, False, 11.0)
        )

        controller.process_pending_events()

        self.assertEqual(
            controller.state.rhythm_hit_events,
            (
                (1, 60, "PERFECT", False),
                (2, 60, "PERFECT", True),
            ),
        )

        controller.state.current_mode = "keys"
        controller.worker_queue.put(
            ("key_output_note", 3, 64, True, 12.0)
        )
        controller.process_pending_events()

        self.assertEqual(
            controller.state.rhythm_hit_events[-1],
            (3, 64, "PERFECT", False),
        )

    def test_unmatched_timing_does_not_emit_miss(self) -> None:
        controller = self.make_controller()
        controller.playback_id = 3
        controller.midi_input_id = 4
        controller.state.current_mode = "sound"
        controller.state.midi_input_running = True
        controller.worker_queue.put(
            ("sound_output_note", 3, 60, True, 10.0)
        )
        controller.worker_queue.put(
            ("midi_output_note", 4, 60, True, 10.2)
        )

        controller.process_pending_events()

        self.assertEqual(controller.state.rhythm_hit_events, ())

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

    def test_worker_position_uses_dedicated_view_update(self) -> None:
        controller = self.make_controller()
        view = RecordingView()
        controller.attach_view(view)
        view.states.clear()
        controller.state.duration = 120.0
        controller.playback_id = 7

        controller.worker_queue.put(
            ("position", 7, controller.position_generation, 10.0)
        )
        controller.worker_queue.put(
            ("position", 7, controller.position_generation, 10.5)
        )
        controller.process_pending_events()

        self.assertEqual(view.states, [])
        self.assertEqual(view.positions, [(10.5, 120.0)])

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
            hide_release_notes_on_startup=True,
        )

        self.assertEqual(controller.state.language, "ja")
        self.assertEqual(controller.state.midi_sound_volume, 64)
        self.assertEqual(controller.state.sound_source, "organ")
        self.assertEqual(controller.state.audio_qt_frames, 1_024)
        self.assertEqual(controller.state.audio_buffer_frames, 512)
        self.assertEqual(controller.state.playback_speed_percent, 137)
        self.assertEqual(controller.state.transpose_semitones, 4)
        self.assertEqual(controller.state.octave_shift, -1)
        self.assertTrue(controller.state.hide_release_notes_on_startup)

    def test_pause_and_resume_keyboard_playback_from_current_position(self) -> None:
        controller = self.make_controller()
        player = FakePlayer()
        sound_player = FakePlayer()
        controller.player = player
        controller.sound_player = sound_player
        controller.state.current_mode = "keys"
        controller.state.duration = 60.0
        controller.state.position = 4.0
        controller.state.active_output_notes = frozenset((60, 64))

        controller.toggle_keyboard_pause()

        self.assertTrue(player.stopped)
        self.assertTrue(sound_player.stopped)
        self.assertIsNone(controller.player)
        self.assertIsNone(controller.sound_player)
        self.assertTrue(controller.state.keyboard_paused)
        self.assertEqual(controller.state.position, 12.5)
        self.assertEqual(controller.state.status, "paused")
        self.assertEqual(controller.state.active_output_notes, frozenset())

        with patch.object(controller, "play_keyboard") as play_keyboard:
            controller.toggle_keyboard_pause()

        play_keyboard.assert_called_once_with(
            start_time=12.5,
            countdown=False,
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

    def test_midi_file_conversion_restarts_from_zero_during_sound_playback(
        self,
    ) -> None:
        controller = self.make_controller(input_conversion_mode="midi_file")
        controller.state.current_mode = "sound"
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

    def test_start_hotkey_restarts_midi_conversion_during_sound_playback(
        self,
    ) -> None:
        controller = self.make_controller(input_conversion_mode="midi_file")
        controller.state.current_mode = "sound"
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

    def test_pause_and_end_shortcuts_do_not_affect_active_midi_sound_playback(
        self,
    ) -> None:
        for action in ("pause_resume", "stop"):
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

    def test_play_sound_updates_realtime_preview_without_disabling_key_output(
        self,
    ) -> None:
        controller = self.make_controller(play_sound=True)
        controller.midi_input_bridge = MagicMock()
        controller.realtime_sound_output = MagicMock()

        controller.set_option("play_sound", False)

        self.assertFalse(controller.state.play_sound)
        controller.realtime_sound_output.set_enabled.assert_called_once_with(False)
        controller.midi_input_bridge.set_dry_run.assert_not_called()

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

    def test_audio_runtime_change_updates_display_state(self) -> None:
        controller = self.make_controller()
        view = RecordingView()
        controller.attach_view(view)

        controller._queue_worker_message(
            (
                "audio_runtime",
                512,
                1_024,
                128,
                512,
                8,
            )
        )
        controller.process_pending_events()

        self.assertEqual(controller.state.audio_qt_frames, 512)
        self.assertEqual(controller.state.audio_buffer_frames, 1_024)
        self.assertEqual(controller.state.audio_response_frames, 128)
        self.assertEqual(controller.state.audio_chunk_frames, 512)
        self.assertEqual(controller.state.audio_fallback_interval_ms, 8)
        self.assertFalse(
            hasattr(
                controller.current_settings(),
                "automatic_audio_buffer_frames",
            )
        )

    def test_manual_audio_settings_are_applied_and_saved(self) -> None:
        controller = self.make_controller()
        controller.sound_player = MagicMock()
        controller.realtime_sound_output = MagicMock()

        controller.set_option("audio_qt_frames", 512)
        controller.set_option("audio_buffer_frames", 256)

        self.assertEqual(controller.state.audio_qt_frames, 512)
        self.assertEqual(controller.state.audio_buffer_frames, 256)
        self.assertEqual(controller.current_settings().audio_qt_frames, 512)
        self.assertEqual(
            controller.current_settings().audio_buffer_frames,
            256,
        )
        controller.sound_player.set_audio_settings.assert_called_with(
            512,
            256,
            256,
            1_024,
            4,
        )
        controller.realtime_sound_output.set_audio_settings.assert_called_with(
            512,
            256,
            256,
            1_024,
            4,
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
                patch.object(
                    controller.midi_parser_process,
                    "parse",
                    return_value=([], summary),
                ),
            ):
                controller.load_midi_folder(temporary_directory, save_folder=False)

        self.assertEqual(
            controller.state.track_channels,
            [
                TrackChannelItem(0, 0, True, track_channel_color(0, 0)),
                TrackChannelItem(0, 1, True, track_channel_color(0, 1)),
            ],
        )
        self.assertEqual(controller.enabled_sources(), {(0, 0), (0, 1)})

    def test_track_channels_include_stable_source_colors(self) -> None:
        controller = self.make_controller()
        controller.events = [
            MidiEvent(0.0, "note_on", 0, 48, 70, track=0),
            MidiEvent(0.0, "note_on", 0, 52, 70, track=0),
            MidiEvent(0.0, "note_on", 0, 55, 70, track=0),
            MidiEvent(0.0, "note_on", 1, 72, 95, track=1),
            MidiEvent(0.5, "note_on", 0, 50, 70, track=0),
            MidiEvent(0.5, "note_on", 0, 53, 70, track=0),
            MidiEvent(0.5, "note_on", 0, 57, 70, track=0),
            MidiEvent(0.5, "note_on", 1, 74, 95, track=1),
        ]
        summary = MidiSummary(
            path=Path("song.mid"),
            duration=1.0,
            channels=(0, 1),
            event_count=len(controller.events),
            tracks=(
                MidiTrackSummary(index=0, channels=(0,)),
                MidiTrackSummary(index=1, channels=(1,)),
            ),
        )

        controller._set_track_channels(summary)

        self.assertEqual(
            controller.state.track_channels,
            [
                TrackChannelItem(0, 0, True, track_channel_color(0, 0)),
                TrackChannelItem(1, 1, True, track_channel_color(1, 1)),
            ],
        )

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

    def test_reload_reuses_unchanged_midi_rows_without_restarting_metadata(self) -> None:
        controller = self.make_controller()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first = root / "first.mid"
            second = root / "second.mid"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            summary = MidiSummary(
                path=first,
                duration=1.0,
                channels=(0,),
                event_count=1,
                tracks=(MidiTrackSummary(index=0, channels=(0,)),),
            )
            with (
                patch.object(
                    controller.midi_parser_process,
                    "parse",
                    return_value=([], summary),
                ) as parse_midi,
                patch.object(controller, "_start_metadata_scan") as metadata_scan,
            ):
                controller.load_midi_folder(root)
                rows = controller.state.midi_rows
                metadata_scan.reset_mock()

                controller.reload_midi_folder()

        self.assertIs(controller.state.midi_rows, rows)
        parse_midi.assert_called_once_with(first)
        metadata_scan.assert_not_called()

    def test_reload_rebuilds_only_the_modified_midi_row(self) -> None:
        controller = self.make_controller()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first = root / "first.mid"
            second = root / "second.mid"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            summary = MidiSummary(
                path=first,
                duration=1.0,
                channels=(0,),
                event_count=1,
                tracks=(MidiTrackSummary(index=0, channels=(0,)),),
            )
            with (
                patch.object(
                    controller.midi_parser_process,
                    "parse",
                    return_value=([], summary),
                ),
                patch.object(controller, "_start_metadata_scan") as metadata_scan,
            ):
                controller.load_midi_folder(root)
                previous_rows = controller.state.midi_rows
                metadata_scan.reset_mock()
                second.write_bytes(b"second changed")

                with patch.object(
                    controller,
                    "_format_midi_folder",
                    wraps=controller._format_midi_folder,
                ) as format_folder:
                    controller.reload_midi_folder()

        self.assertIs(controller.state.midi_rows[0], previous_rows[0])
        self.assertIsNot(controller.state.midi_rows[1], previous_rows[1])
        format_folder.assert_called_once_with(root, second)
        metadata_scan.assert_called_once_with([second])

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

    def test_keyboard_conversion_uses_regular_sound_player_when_enabled(
        self,
    ) -> None:
        controller = self.make_controller(
            play_sound=True,
            midi_sound_volume=67,
            sound_source="organ",
        )
        controller.events = [
            MidiEvent(0.0, "note_on", 0, 60, 80, track=0)
        ]
        controller._set_enabled_sources(((0, 0),))
        keyboard_player = MagicMock()
        sound_player = MagicMock()
        sound_player.is_playing = False

        with (
            patch("app_controller.KeyboardOutput") as output_class,
            patch(
                "app_controller.MidiKeyboardPlayer",
                return_value=keyboard_player,
            ) as keyboard_player_class,
            patch(
                "app_controller.MidiSoundPlayer",
                return_value=sound_player,
            ) as sound_player_class,
        ):
            controller.play_keyboard(start_time=2.5, countdown=False)
            keyboard_player_class.call_args.kwargs["on_state"]("playing")

        output_class.assert_called_once_with()
        sound_player_class.assert_called_once()
        self.assertEqual(
            sound_player_class.call_args.kwargs["volume"],
            67,
        )
        self.assertEqual(
            sound_player_class.call_args.kwargs["sound_source"],
            "organ",
        )
        sound_player.play.assert_called_once_with(
            controller.events,
            start_time=2.5,
        )

    def test_keyboard_conversion_sends_keys_without_sound_when_disabled(
        self,
    ) -> None:
        controller = self.make_controller(play_sound=False)
        controller.events = [
            MidiEvent(0.0, "note_on", 0, 60, 80, track=0)
        ]
        controller._set_enabled_sources(((0, 0),))
        keyboard_player = MagicMock()

        with (
            patch("app_controller.KeyboardOutput") as output_class,
            patch(
                "app_controller.MidiKeyboardPlayer",
                return_value=keyboard_player,
            ),
            patch("app_controller.MidiSoundPlayer") as sound_player_class,
        ):
            controller.play_keyboard(countdown=False)

        output_class.assert_called_once_with()
        sound_player_class.assert_not_called()

    def test_keyboard_conversion_sound_can_be_toggled_while_running(
        self,
    ) -> None:
        controller = self.make_controller(play_sound=False)
        controller.events = [
            MidiEvent(0.0, "note_on", 0, 60, 80, track=0)
        ]
        controller.player = MagicMock()
        controller.player.current_position.return_value = 3.25
        controller.state.current_mode = "keys"
        sound_player = MagicMock()
        sound_player.is_playing = False

        with patch(
            "app_controller.MidiSoundPlayer",
            return_value=sound_player,
        ):
            controller.set_option("play_sound", True)
            controller.set_option("play_sound", False)

        sound_player.play.assert_called_once_with(
            controller.events,
            start_time=3.25,
        )
        sound_player.stop.assert_called_once_with()
        sound_player.wait_until_stopped.assert_called_once_with(timeout=2.0)
        self.assertIsNone(controller.sound_player)

    def test_keyboard_conversion_end_stops_its_sound_player(self) -> None:
        controller = self.make_controller(play_sound=True)
        sound_player = MagicMock()
        controller.player = MagicMock()
        controller.sound_player = sound_player
        controller.state.current_mode = "keys"
        controller.playback_id = 6
        controller.worker_queue.put(("key_state", 6, "stopped"))

        controller.process_pending_events()

        sound_player.stop.assert_called_once_with()
        sound_player.wait_until_stopped.assert_called_once_with(timeout=2.0)
        self.assertIsNone(controller.sound_player)
        self.assertIsNone(controller.state.current_mode)

    def test_realtime_conversion_always_sends_keys_and_optionally_plays_sound(
        self,
    ) -> None:
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                controller = self.make_controller(play_sound=enabled)
                controller.midi_input_devices = [(7, "USB MIDI")]
                controller.state.midi_input_device = "USB MIDI"
                bridge = MagicMock()
                realtime_sound = MagicMock()

                with (
                    patch("app_controller.KeyboardOutput") as output_class,
                    patch(
                        "app_controller.RealtimeMidiSoundOutput",
                        return_value=realtime_sound,
                    ),
                    patch(
                        "app_controller.MidiInputKeyboardBridge",
                        return_value=bridge,
                    ),
                ):
                    controller.start_midi_input()

                output_class.assert_called_once_with()
                realtime_sound.set_enabled.assert_called_once_with(enabled)
                bridge.start.assert_called_once_with()

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
                patch.object(
                    controller.midi_parser_process,
                    "parse",
                    return_value=(events, summary),
                ),
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

    def test_event_dispatch_tracks_output_sources_by_track_and_channel(self) -> None:
        controller = self.make_controller()
        controller.playback_id = 5
        controller.midi_input_id = 8
        controller.worker_queue.put(
            ("sound_output_source", 5, 60, 2, 3, True)
        )
        controller.worker_queue.put(
            ("midi_output_source", 8, 64, -1, 4, True)
        )

        controller.process_pending_events()

        self.assertEqual(
            controller.state.output_note_sources,
            ((60, 2, 3), (64, -1, 4)),
        )
        self.assertEqual(
            controller.state.realtime_output_note_sources,
            ((64, -1, 4),),
        )

        controller.worker_queue.put(
            ("sound_output_source", 5, 60, 2, 3, False)
        )
        controller.process_pending_events()

        self.assertEqual(
            controller.state.output_note_sources,
            ((64, -1, 4),),
        )

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

    def test_stopping_realtime_input_clears_displayed_output_notes(self) -> None:
        controller = self.make_controller()
        controller.state.midi_input_running = True
        for note in (48, 60, 72):
            controller._set_output_note_state(("midi", controller.midi_input_id), note, True)

        controller.stop_midi_input()

        self.assertEqual(controller.state.active_output_notes, frozenset())

if __name__ == "__main__":
    unittest.main()
