from __future__ import annotations

import queue
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from legacy_tk_main import App
from midi_parser import MidiEvent
from playback_timing import PlaybackTimeline
from player import MidiKeyboardPlayer


class FakeVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeLabel:
    def __init__(self):
        self.config: dict[str, object] = {}

    def configure(self, **kwargs):
        self.config.update(kwargs)


class FakeEntry:
    def __init__(self):
        self.config: dict[str, object] = {}

    def configure(self, **kwargs):
        self.config.update(kwargs)


class FakeKeyboardPlayer:
    calls: list[dict[str, object]] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def play(self, events, countdown_seconds: int = 0, start_time: float = 0.0) -> None:
        self.play_with_countdown_sound(events, countdown_seconds, start_time, None)

    def play_with_countdown_sound(
        self,
        events,
        countdown_seconds: int = 0,
        start_time: float = 0.0,
        on_countdown_tick=None,
    ) -> None:
        self.calls.append(
            {
                "events": events,
                "countdown_seconds": countdown_seconds,
                "start_time": start_time,
                "on_countdown_tick": on_countdown_tick,
            }
        )


class FakeOutput:
    def __init__(self):
        self.pressed: list[str] = []
        self.released: list[str] = []
        self.tapped: list[str] = []

    def press(self, key: str) -> None:
        self.pressed.append(key)

    def release(self, key: str) -> None:
        self.released.append(key)

    def tap(self, key: str) -> None:
        self.tapped.append(key)
        self.press(key)
        self.release(key)

    def release_all(self) -> None:
        self.released.append("*")


class FakeRunningPlayer:
    is_playing = True

    def __init__(self):
        self.stopped = False
        self.waited = False
        self.release_requested = False
        self.output = type("Output", (), {"released": False})()
        self.output.release_all = lambda: setattr(self.output, "released", True)

    def stop(self) -> None:
        self.stopped = True

    def wait_until_stopped(self, timeout: float = 1.0) -> None:
        self.waited = True

    def request_release_all(self) -> None:
        self.release_requested = True

    def set_humanize_timing(self, enabled: bool) -> None:
        self.humanize_timing = enabled

    def set_chord_optimization(self, enabled: bool) -> None:
        self.chord_optimization = enabled

    def set_chord_strum(self, enabled: bool) -> None:
        self.chord_strum = enabled

    def set_repeat_prevention(self, enabled: bool) -> None:
        self.repeat_prevention = enabled

    def set_playback_speed(self, speed_percent: int) -> None:
        self.playback_speed_percent = speed_percent

    def set_note_shift(self, transpose_semitones: int, octave_shift: int) -> None:
        self.transpose_semitones = transpose_semitones
        self.octave_shift = octave_shift


class KeyPlaybackTests(unittest.TestCase):
    def test_keyboard_optimization_reports_progress_and_completion(self) -> None:
        progress: list[int | None] = []
        player = MidiKeyboardPlayer(
            output=FakeOutput(),
            chord_optimization=True,
            on_optimization_progress=progress.append,
        )
        events = [
            MidiEvent(time=index * 0.1, kind="note_on", channel=0, note=60, velocity=80)
            for index in range(20)
        ]

        player._refresh_chord_optimization_plan(events, force=True)

        self.assertEqual(progress[0], 0)
        self.assertIn(100, progress)
        self.assertIsNone(progress[-1])

    def test_optimization_queue_message_uses_localized_status(self) -> None:
        app = object.__new__(App)
        app.log_queue = queue.Queue()
        app.log_queue.put("__OPTIMIZATION__4__42")
        app.playback_id = 4
        app.current_play_mode = "keys"
        app.language = "ja"
        app.state_var = FakeVar("")
        app.after = lambda _delay, _callback: None

        App._drain_log_queue(app)

        self.assertEqual(app.state_var.get(), "最適化中 42%")

    def test_chord_optimization_keeps_label_color_and_uses_common_checkbox_color(self) -> None:
        app = object.__new__(App)

        for theme in (
            "light",
            "dark",
            "green",
            "yellow",
            "blue",
            "sky_blue",
            "red",
            "pink",
            "orange",
        ):
            app.color_theme = theme
            palette = App._theme_palette(app)
            app.chord_optimization_check = FakeLabel()

            App._style_chord_optimization_control(app, palette)

            self.assertEqual(
                app.chord_optimization_check.config["background"],
                palette["panel"],
            )
            self.assertEqual(
                app.chord_optimization_check.config["selectcolor"],
                palette["field"],
            )

    def test_play_keys_passes_countdown_setting_to_player(self) -> None:
        app = object.__new__(App)
        app.events = [MidiEvent(time=0.0, kind="note_on", channel=0, note=60, velocity=64)]
        app.channel_vars = {0: FakeVar(True)}
        app.dry_run_var = FakeVar(True)
        app.countdown_var = FakeVar(4)
        app.countdown_sound_var = FakeVar(False)
        app.humanize_timing_var = FakeVar(True)
        app.chord_optimization_var = FakeVar(True)
        app.chord_strum_var = FakeVar(False)
        app.repeat_prevention_var = FakeVar(True)
        app.playback_speed_var = FakeVar(100)
        app.auto_fit_note_range_var = FakeVar(False)
        app.transpose_semitones_var = FakeVar(3)
        app.octave_shift_var = FakeVar(-1)
        app.log_queue = queue.Queue()
        app.current_play_mode = None
        app.playback_id = 0
        app.ignore_player_position_until = 0.0
        app._refresh_playback_buttons = lambda: None
        app._refresh_midi_input_button = lambda: None
        app._refresh_option_states = lambda: None
        app._play_start_position = lambda: 0.0
        app._text = lambda key: key
        app._log = lambda _message: None

        FakeKeyboardPlayer.calls.clear()
        with patch("legacy_tk_main.MidiKeyboardPlayer", FakeKeyboardPlayer):
            App.play(app)

        self.assertEqual(FakeKeyboardPlayer.calls[0]["countdown_seconds"], 4)
        self.assertIsNone(FakeKeyboardPlayer.calls[0]["on_countdown_tick"])
        self.assertEqual(app.current_play_mode, "keys")
        self.assertTrue(app.player.kwargs["humanize_timing"])
        self.assertTrue(app.player.kwargs["chord_optimization"])
        self.assertTrue(app.player.kwargs["repeat_prevention"])
        self.assertEqual(app.player.kwargs["transpose_semitones"], 3)
        self.assertEqual(app.player.kwargs["octave_shift"], -1)

    def test_play_keys_passes_countdown_sound_callback_when_enabled(self) -> None:
        app = object.__new__(App)
        app.events = [MidiEvent(time=0.0, kind="note_on", channel=0, note=60, velocity=64)]
        app.channel_vars = {0: FakeVar(True)}
        app.dry_run_var = FakeVar(True)
        app.countdown_var = FakeVar(4)
        app.countdown_sound_var = FakeVar(True)
        app.humanize_timing_var = FakeVar(False)
        app.chord_optimization_var = FakeVar(False)
        app.chord_strum_var = FakeVar(False)
        app.repeat_prevention_var = FakeVar(False)
        app.playback_speed_var = FakeVar(100)
        app.auto_fit_note_range_var = FakeVar(False)
        app.transpose_semitones_var = FakeVar(0)
        app.octave_shift_var = FakeVar(0)
        app.log_queue = queue.Queue()
        app.current_play_mode = None
        app.playback_id = 0
        app.ignore_player_position_until = 0.0
        app._refresh_playback_buttons = lambda: None
        app._refresh_midi_input_button = lambda: None
        app._refresh_option_states = lambda: None
        app._play_start_position = lambda: 0.0
        app._text = lambda key: key
        app._log = lambda _message: None

        FakeKeyboardPlayer.calls.clear()
        with patch("legacy_tk_main.MidiKeyboardPlayer", FakeKeyboardPlayer):
            App.play(app)

        self.assertIsNotNone(FakeKeyboardPlayer.calls[0]["on_countdown_tick"])

    def test_restart_keys_keeps_seeking_flag_until_old_stop_event_arrives(self) -> None:
        app = object.__new__(App)
        app.events = [MidiEvent(time=0.0, kind="note_on", channel=0, note=60, velocity=64)]
        app.channel_vars = {0: FakeVar(True)}
        app.dry_run_var = FakeVar(True)
        app.auto_fit_note_range_var = FakeVar(False)
        app.humanize_timing_var = FakeVar(True)
        app.chord_optimization_var = FakeVar(True)
        app.chord_strum_var = FakeVar(True)
        app.repeat_prevention_var = FakeVar(True)
        app.playback_speed_var = FakeVar(125)
        app.transpose_semitones_var = FakeVar(-2)
        app.octave_shift_var = FakeVar(1)
        app.log_queue = queue.Queue()
        app.playback_id = 0
        app.current_play_mode = "keys"
        app.seeking_keys = True
        app._text = lambda key: key
        app._next_playback_id = lambda: 1
        app._refresh_playback_buttons = lambda: None

        FakeKeyboardPlayer.calls.clear()
        with patch("legacy_tk_main.MidiKeyboardPlayer", FakeKeyboardPlayer):
            App._restart_keys_from(app, 2.5)

        self.assertTrue(app.seeking_keys)
        self.assertEqual(FakeKeyboardPlayer.calls[0]["start_time"], 2.5)
        self.assertTrue(app.player.kwargs["humanize_timing"])
        self.assertTrue(app.player.kwargs["chord_optimization"])
        self.assertTrue(app.player.kwargs["chord_strum"])
        self.assertTrue(app.player.kwargs["repeat_prevention"])
        self.assertEqual(app.player.kwargs["playback_speed_percent"], 125)
        self.assertEqual(app.player.kwargs["transpose_semitones"], -2)
        self.assertEqual(app.player.kwargs["octave_shift"], 1)

    def test_channel_change_keeps_player_running_and_releases_held_keys(self) -> None:
        app = object.__new__(App)
        player = FakeRunningPlayer()
        app.current_play_mode = "keys"
        app.player = player
        app.updating_channels = False
        app.channel_vars = {0: FakeVar(True)}

        App._on_channel_changed(app)

        self.assertFalse(player.stopped)
        self.assertFalse(player.waited)
        self.assertTrue(player.release_requested)

    def test_keyboard_player_filters_channels_dynamically_without_restart(self) -> None:
        enabled = {0}
        output = FakeOutput()
        player = MidiKeyboardPlayer(output=output, enabled_channels=lambda: enabled)

        player._handle_event(MidiEvent(time=0.0, kind="note_on", channel=1, note=60, velocity=64))
        player._handle_event(MidiEvent(time=0.1, kind="note_on", channel=0, note=60, velocity=64))

        self.assertEqual(output.pressed, ["a"])

    def test_keyboard_player_uses_custom_key_binding(self) -> None:
        output = FakeOutput()
        player = MidiKeyboardPlayer(output=output, key_bindings={60: "q"})

        player._handle_event(MidiEvent(time=0.0, kind="note_on", channel=0, note=60, velocity=64))

        self.assertEqual(output.pressed, ["q"])

    def test_key_binding_key_event_accepts_supported_keys(self) -> None:
        self.assertEqual(
            App._key_binding_from_event(SimpleNamespace(keysym="A", char="A")),
            "a",
        )
        self.assertEqual(
            App._key_binding_from_event(SimpleNamespace(keysym="bracketleft", char="")),
            "[",
        )
        self.assertEqual(
            App._key_binding_from_event(SimpleNamespace(keysym="space", char=" ")),
            "space",
        )

    def test_key_binding_key_event_rejects_unsupported_keys(self) -> None:
        self.assertIsNone(
            App._key_binding_from_event(SimpleNamespace(keysym="F1", char="")),
        )

    def test_game_countdown_tick_holds_c3_binding(self) -> None:
        app = object.__new__(App)
        output = FakeOutput()
        app.log_queue = queue.Queue()
        app.player = SimpleNamespace(output=output)
        app.key_bindings = App._current_key_bindings(app)
        app.countdown_sound_var = FakeVar(False)
        app.game_countdown_sound_var = FakeVar(True)

        App._play_countdown_tick(app, 2)

        self.assertEqual(output.pressed, ["z"])
        self.assertEqual(output.released, ["z"])
        self.assertEqual(app.log_queue.get_nowait(), "Countdown: 2")
        self.assertEqual(app.log_queue.get_nowait(), "Countdown game key: z")

    def test_duplicate_key_bindings_are_marked_with_red_entry_style(self) -> None:
        app = object.__new__(App)
        app.key_bindings = {**App._current_key_bindings(app), 60: "q", 61: "q"}
        first = FakeEntry()
        second = FakeEntry()
        third = FakeEntry()
        app.key_binding_entries = {60: first, 61: second, 62: third}

        App._refresh_key_binding_duplicate_styles(app)

        self.assertEqual(first.config["style"], "DuplicateKeyBinding.TEntry")
        self.assertEqual(second.config["style"], "DuplicateKeyBinding.TEntry")
        self.assertEqual(third.config["style"], "TEntry")

    def test_keyboard_player_filters_same_channel_by_track(self) -> None:
        enabled_sources = {(0, 0)}
        output = FakeOutput()
        player = MidiKeyboardPlayer(
            output=output,
            enabled_sources=lambda: enabled_sources,
        )

        player._handle_event(
            MidiEvent(
                time=0.0,
                kind="note_on",
                channel=0,
                note=60,
                velocity=64,
                track=1,
            )
        )
        player._handle_event(
            MidiEvent(
                time=0.1,
                kind="note_on",
                channel=0,
                note=60,
                velocity=64,
                track=0,
            )
        )

        self.assertEqual(output.pressed, ["a"])

    def test_track_channel_selection_updates_source_snapshot(self) -> None:
        app = object.__new__(App)
        app.updating_channels = False
        app.track_channel_vars = {
            (0, 0): FakeVar(True),
            (0, 1): FakeVar(False),
            (1, 0): FakeVar(True),
        }
        app.channel_vars = {}
        app.current_play_mode = None
        app.player = None
        app.sound_player = None

        App._on_channel_changed(app)

        self.assertEqual(
            app.enabled_sources_snapshot,
            frozenset({(0, 0), (1, 0)}),
        )

        app.track_channel_vars[(0, 0)].set(False)
        App._on_channel_changed(app)

        self.assertEqual(app.enabled_sources_snapshot, frozenset({(1, 0)}))

    def test_short_track_list_scrollregion_stays_aligned_to_top(self) -> None:
        self.assertEqual(
            App._channel_scrollregion(
                content_bbox=(0, 0, 120, 95),
                viewport_width=120,
                viewport_height=250,
            ),
            (0, 0, 120, 250),
        )
        self.assertEqual(
            App._channel_scrollregion(
                content_bbox=(0, 0, 120, 420),
                viewport_width=120,
                viewport_height=250,
            ),
            (0, 0, 120, 420),
        )

    def test_play_keeps_initially_disabled_channel_events_for_dynamic_enable(self) -> None:
        app = object.__new__(App)
        app.events = [
            MidiEvent(time=0.0, kind="note_on", channel=0, note=60, velocity=64),
            MidiEvent(time=0.1, kind="note_on", channel=1, note=64, velocity=64),
        ]
        app.channel_vars = {0: FakeVar(True), 1: FakeVar(False)}
        app.dry_run_var = FakeVar(True)
        app.countdown_var = FakeVar(0)
        app.countdown_sound_var = FakeVar(False)
        app.humanize_timing_var = FakeVar(False)
        app.chord_optimization_var = FakeVar(False)
        app.chord_strum_var = FakeVar(False)
        app.repeat_prevention_var = FakeVar(False)
        app.playback_speed_var = FakeVar(100)
        app.auto_fit_note_range_var = FakeVar(False)
        app.transpose_semitones_var = FakeVar(0)
        app.octave_shift_var = FakeVar(0)
        app.log_queue = queue.Queue()
        app.current_play_mode = None
        app.playback_id = 0
        app.ignore_player_position_until = 0.0
        app._refresh_playback_buttons = lambda: None
        app._refresh_midi_input_button = lambda: None
        app._refresh_option_states = lambda: None
        app._play_start_position = lambda: 0.0
        app._text = lambda key: key
        app._log = lambda _message: None

        FakeKeyboardPlayer.calls.clear()
        with patch("legacy_tk_main.MidiKeyboardPlayer", FakeKeyboardPlayer):
            App.play(app)

        self.assertEqual(FakeKeyboardPlayer.calls[0]["events"], app.events)

    def test_keyboard_player_reports_stopped_after_output_failure(self) -> None:
        class FailingOutput(FakeOutput):
            def press(self, key: str) -> None:
                raise OSError("blocked")

        states: list[str] = []
        logs: list[str] = []
        player = MidiKeyboardPlayer(
            output=FailingOutput(),
            on_state=states.append,
            log=logs.append,
            auto_fit_note_range=True,
        )

        player.play([MidiEvent(time=0.0, kind="note_on", channel=0, note=60, velocity=64)])
        player.wait_until_stopped(timeout=1.0)

        self.assertIn("stopped", states)
        self.assertTrue(any("failed" in message.lower() for message in logs))

    def test_same_note_on_different_channels_has_independent_note_off(self) -> None:
        output = FakeOutput()
        player = MidiKeyboardPlayer(output=output, auto_fit_note_range=True)

        player._handle_event(MidiEvent(time=0.0, kind="note_on", channel=0, note=60, velocity=64))
        player._handle_event(MidiEvent(time=0.1, kind="note_on", channel=1, note=60, velocity=64))
        player._handle_event(MidiEvent(time=0.2, kind="note_off", channel=0, note=60, velocity=0))
        player._handle_event(MidiEvent(time=0.3, kind="note_off", channel=1, note=60, velocity=0))

        self.assertEqual(output.pressed, ["a", "a"])
        self.assertEqual(output.released, ["a", "a"])

    def test_sustain_remains_pressed_until_all_channels_release(self) -> None:
        output = FakeOutput()
        player = MidiKeyboardPlayer(output=output)

        player._handle_event(MidiEvent(time=0.0, kind="sustain", channel=0, value=127))
        player._handle_event(MidiEvent(time=0.1, kind="sustain", channel=1, value=127))
        player._handle_event(MidiEvent(time=0.2, kind="sustain", channel=0, value=0))
        player._handle_event(MidiEvent(time=0.3, kind="sustain", channel=1, value=0))

        self.assertEqual(output.pressed, ["space"])
        self.assertEqual(output.released, ["space"])

    def test_repeat_prevention_ignores_impossibly_fast_same_key_repeats(self) -> None:
        output = FakeOutput()
        player = MidiKeyboardPlayer(output=output, repeat_prevention=True)

        player._handle_event(
            MidiEvent(time=0.0, kind="note_on", channel=0, note=60, velocity=64),
            emitted_at=1.0,
        )
        player._handle_event(MidiEvent(time=0.01, kind="note_off", channel=0, note=60, velocity=0))
        player._handle_event(
            MidiEvent(time=0.02, kind="note_on", channel=0, note=60, velocity=64),
            emitted_at=1.02,
        )
        player._handle_event(MidiEvent(time=0.03, kind="note_off", channel=0, note=60, velocity=0))
        player._handle_event(
            MidiEvent(time=0.05, kind="note_on", channel=0, note=60, velocity=64),
            emitted_at=1.05,
        )

        self.assertEqual(output.pressed, ["a", "a"])
        self.assertEqual(output.released, ["a"])

    def test_repeat_prevention_uses_output_interval_after_speed_change(self) -> None:
        output = FakeOutput()
        player = MidiKeyboardPlayer(output=output, repeat_prevention=True)

        player._handle_event(
            MidiEvent(time=0.0, kind="note_on", channel=0, note=60, velocity=64),
            emitted_at=10.0,
        )
        player._handle_event(MidiEvent(time=0.04, kind="note_off", channel=0, note=60, velocity=0))
        player._handle_event(
            MidiEvent(time=0.08, kind="note_on", channel=0, note=60, velocity=64),
            emitted_at=10.04,
        )

        self.assertEqual(output.pressed, ["a"])
        self.assertEqual(output.released, ["a"])

    def test_keyboard_player_applies_transpose_and_octave_shift(self) -> None:
        output = FakeOutput()
        player = MidiKeyboardPlayer(
            output=output,
            auto_fit_note_range=True,
            transpose_semitones=2,
            octave_shift=1,
        )

        player._handle_event(MidiEvent(time=0.0, kind="note_on", channel=0, note=48, velocity=64))
        player._handle_event(MidiEvent(time=0.1, kind="note_off", channel=0, note=48, velocity=0))

        self.assertEqual(output.pressed, ["s"])
        self.assertEqual(output.released, ["s"])

    def test_keyboard_optimization_uses_one_external_range_for_a_high_chord(self) -> None:
        output = FakeOutput()
        player = MidiKeyboardPlayer(output=output, chord_optimization=True)
        events = [
            MidiEvent(time=0.0, kind="note_on", channel=0, note=note, velocity=80, track=0)
            for note in (84, 88, 91)
        ]
        player._refresh_chord_optimization_plan(events, force=True)

        for event in events:
            player._handle_event(event)

        self.assertEqual(output.tapped, [">"])
        self.assertEqual(output.pressed[-3:], ["z", "c", "b"])

    def test_speed_change_rebuilds_keyboard_chord_optimization_plan(self) -> None:
        player = MidiKeyboardPlayer(
            output=FakeOutput(),
            chord_optimization=True,
            playback_speed_percent=100,
        )
        events = [MidiEvent(time=0.0, kind="note_on", channel=0, note=84, velocity=80)]
        player._refresh_chord_optimization_plan(events, force=True)

        self.assertFalse(player._chord_optimization_plan_dirty)
        self.assertEqual(player._chord_optimization_plan_speed, 100)

        player.set_playback_speed(73)

        self.assertTrue(player._chord_optimization_plan_dirty)
        player._refresh_chord_optimization_plan(events)
        player._optimization_planner.wait(timeout=1.0)
        self.assertEqual(player._chord_optimization_plan_speed, 73)

    def test_optimized_note_still_uses_rapid_repeat_prevention(self) -> None:
        output = FakeOutput()
        player = MidiKeyboardPlayer(
            output=output,
            chord_optimization=True,
            repeat_prevention=True,
        )
        events = [
            MidiEvent(time=0.00, kind="note_on", channel=0, note=96, velocity=80, track=0),
            MidiEvent(time=0.01, kind="note_off", channel=0, note=96, velocity=0, track=0),
            MidiEvent(time=0.04, kind="note_on", channel=0, note=96, velocity=80, track=0),
            MidiEvent(time=0.05, kind="note_off", channel=0, note=96, velocity=0, track=0),
        ]
        player._refresh_chord_optimization_plan(events, force=True)

        for event in events:
            player._handle_event(event, emitted_at=1.0 + event.time)

        self.assertEqual(output.pressed.count("a"), 1)

    def test_humanized_schedule_keeps_chords_together_and_event_order(self) -> None:
        class FixedRandom:
            values = iter((0.018, -0.018))

            def triangular(self, _low: float, _high: float, _mode: float) -> float:
                return next(self.values)

        events = [
            MidiEvent(time=1.0, kind="note_on", channel=0, note=60, velocity=64),
            MidiEvent(time=1.0, kind="note_on", channel=0, note=64, velocity=64),
            MidiEvent(time=1.01, kind="note_off", channel=0, note=60, velocity=0),
            MidiEvent(time=2.0, kind="end"),
        ]
        timeline = PlaybackTimeline(start_time=0.0, random_source=FixedRandom())
        scheduled_times = []
        for event in events:
            scheduled_time = timeline.scheduled_time(event, humanize_timing=True)
            scheduled_times.append(scheduled_time)
            timeline.mark_emitted(scheduled_time)

        self.assertEqual(scheduled_times[:2], [1.018, 1.018])
        self.assertEqual(scheduled_times[2], 1.018)
        self.assertEqual(scheduled_times[3], 2.0)

    def test_schedule_is_exact_when_humanize_is_disabled(self) -> None:
        class FixedRandom:
            def triangular(self, _low: float, _high: float, _mode: float) -> float:
                return 0.018

        events = [
            MidiEvent(time=0.5, kind="note_on", channel=0, note=60, velocity=64),
            MidiEvent(time=0.75, kind="note_off", channel=0, note=60, velocity=0),
        ]
        timeline = PlaybackTimeline(start_time=0.6, random_source=FixedRandom())
        scheduled_time = timeline.scheduled_time(events[1], humanize_timing=False)

        self.assertEqual(scheduled_time, 0.75)

    def test_current_event_is_rescheduled_immediately_when_humanize_changes(self) -> None:
        class FixedRandom:
            def triangular(self, _low: float, _high: float, _mode: float) -> float:
                return 0.018

        event = MidiEvent(time=1.0, kind="note_on", channel=0, note=60, velocity=64)
        timeline = PlaybackTimeline(start_time=0.0, random_source=FixedRandom())

        self.assertEqual(timeline.scheduled_time(event, humanize_timing=False), 1.0)
        self.assertEqual(timeline.scheduled_time(event, humanize_timing=True), 1.018)
        self.assertEqual(timeline.scheduled_time(event, humanize_timing=False), 1.0)

    def test_humanize_change_updates_active_key_and_sound_players(self) -> None:
        key_player = FakeRunningPlayer()
        sound_player = FakeRunningPlayer()
        app = object.__new__(App)
        app.humanize_timing_var = FakeVar(True)
        app.player = key_player
        app.sound_player = sound_player
        app._save_current_settings = lambda: None

        App._on_humanize_timing_changed(app)

        self.assertTrue(key_player.humanize_timing)
        self.assertTrue(sound_player.humanize_timing)

    def test_chord_strum_change_updates_active_key_and_sound_players(self) -> None:
        key_player = FakeRunningPlayer()
        sound_player = FakeRunningPlayer()
        app = object.__new__(App)
        app.chord_strum_var = FakeVar(True)
        app.player = key_player
        app.sound_player = sound_player
        app._save_current_settings = lambda: None

        App._on_chord_strum_changed(app)

        self.assertTrue(key_player.chord_strum)
        self.assertTrue(sound_player.chord_strum)

    def test_chord_optimization_change_updates_active_key_and_sound_players(self) -> None:
        key_player = FakeRunningPlayer()
        sound_player = FakeRunningPlayer()
        app = object.__new__(App)
        app.chord_optimization_var = FakeVar(True)
        app.player = key_player
        app.sound_player = sound_player
        app._save_current_settings = lambda: None

        App._on_chord_optimization_changed(app)

        self.assertTrue(key_player.chord_optimization)
        self.assertTrue(sound_player.chord_optimization)

    def test_repeat_prevention_change_updates_all_active_midi_paths(self) -> None:
        key_player = FakeRunningPlayer()
        sound_player = FakeRunningPlayer()
        midi_input_bridge = FakeRunningPlayer()
        realtime_sound_output = FakeRunningPlayer()
        app = object.__new__(App)
        app.repeat_prevention_var = FakeVar(True)
        app.player = key_player
        app.sound_player = sound_player
        app.midi_input_bridge = midi_input_bridge
        app.realtime_sound_output = realtime_sound_output
        app._save_current_settings = lambda: None

        App._on_repeat_prevention_changed(app)

        self.assertTrue(key_player.repeat_prevention)
        self.assertTrue(sound_player.repeat_prevention)
        self.assertTrue(midi_input_bridge.repeat_prevention)
        self.assertTrue(realtime_sound_output.repeat_prevention)

    def test_note_shift_change_updates_all_active_midi_paths(self) -> None:
        key_player = FakeRunningPlayer()
        sound_player = FakeRunningPlayer()
        midi_input_bridge = FakeRunningPlayer()
        realtime_sound_output = FakeRunningPlayer()
        app = object.__new__(App)
        app.transpose_semitones_var = FakeVar(5)
        app.octave_shift_var = FakeVar(-1)
        app.player = key_player
        app.sound_player = sound_player
        app.midi_input_bridge = midi_input_bridge
        app.realtime_sound_output = realtime_sound_output
        app._save_current_settings = lambda: None

        App._on_note_shift_changed(app)

        for target in (key_player, sound_player, midi_input_bridge, realtime_sound_output):
            self.assertEqual(target.transpose_semitones, 5)
            self.assertEqual(target.octave_shift, -1)

    def test_double_click_resets_note_shift_values_individually(self) -> None:
        app = object.__new__(App)
        app.transpose_semitones_var = FakeVar(7)
        app.octave_shift_var = FakeVar(-2)

        transpose_result = App._reset_transpose_semitones(app)

        self.assertEqual(transpose_result, "break")
        self.assertEqual(app.transpose_semitones_var.get(), 0)
        self.assertEqual(app.octave_shift_var.get(), -2)

        octave_result = App._reset_octave_shift(app)

        self.assertEqual(octave_result, "break")
        self.assertEqual(app.octave_shift_var.get(), 0)

    def test_clicking_outside_numeric_fields_clears_focus(self) -> None:
        app = object.__new__(App)
        app.countdown_spinbox = object()
        app.transpose_semitones_spinbox = object()
        app.octave_shift_spinbox = object()
        app.focused_widget = app.transpose_semitones_spinbox
        app.focus_was_cleared = False
        app.focus_get = lambda: app.focused_widget
        app.focus_set = lambda: setattr(app, "focus_was_cleared", True)
        outside_event = type("Event", (), {"widget": object()})()

        App._on_app_pointer_down(app, outside_event)

        self.assertTrue(app.focus_was_cleared)

    def test_clicking_another_numeric_field_keeps_field_focus(self) -> None:
        app = object.__new__(App)
        app.countdown_spinbox = object()
        app.transpose_semitones_spinbox = object()
        app.octave_shift_spinbox = object()
        app.focused_widget = app.transpose_semitones_spinbox
        app.focus_was_cleared = False
        app.focus_get = lambda: app.focused_widget
        app.focus_set = lambda: setattr(app, "focus_was_cleared", True)
        field_event = type(
            "Event",
            (),
            {"widget": app.octave_shift_spinbox},
        )()

        App._on_app_pointer_down(app, field_event)

        self.assertFalse(app.focus_was_cleared)

    def test_speed_change_updates_active_key_and_sound_players(self) -> None:
        key_player = FakeRunningPlayer()
        sound_player = FakeRunningPlayer()
        app = object.__new__(App)
        app.playback_speed_var = FakeVar(100)
        app.playback_speed_label = FakeLabel()
        app.player = key_player
        app.sound_player = sound_player
        app._save_current_settings = lambda: None

        App._on_playback_speed_changed(app, "150")

        self.assertEqual(key_player.playback_speed_percent, 150)
        self.assertEqual(sound_player.playback_speed_percent, 150)
        self.assertEqual(app.playback_speed_label.config["text"], "150")

    def test_double_click_resets_playback_speed_to_100_percent(self) -> None:
        key_player = FakeRunningPlayer()
        sound_player = FakeRunningPlayer()
        app = object.__new__(App)
        app.playback_speed_var = FakeVar(150)
        app.playback_speed_label = FakeLabel()
        app.player = key_player
        app.sound_player = sound_player
        app._save_current_settings = lambda: None

        result = App._reset_playback_speed(app)

        self.assertEqual(result, "break")
        self.assertEqual(app.playback_speed_var.get(), 100)
        self.assertEqual(key_player.playback_speed_percent, 100)
        self.assertEqual(sound_player.playback_speed_percent, 100)
        self.assertEqual(app.playback_speed_label.config["text"], "100")


if __name__ == "__main__":
    unittest.main()
