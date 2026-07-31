from __future__ import annotations

import unittest

from auto_sustain import AUTO_SUSTAIN_EVENT_KIND
from midi_parser import MidiEvent
from playback_timing import PlaybackTimeline
from player import MidiKeyboardPlayer


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


class KeyPlaybackTests(unittest.TestCase):
    def test_keyboard_player_reports_natural_completion(self) -> None:
        states: list[str] = []
        completions: list[bool] = []
        player = MidiKeyboardPlayer(
            output=FakeOutput(),
            on_state=states.append,
            on_complete=lambda: completions.append(True),
        )

        player.play([MidiEvent(time=0.0, kind="end")])
        player.wait_until_stopped(timeout=1.0)

        self.assertIn("stopped", states)
        self.assertEqual(completions, [True])

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

    def test_keyboard_player_reports_track_channel_for_output_notes(self) -> None:
        output = FakeOutput()
        source_events: list[tuple[int, int, int, bool]] = []
        player = MidiKeyboardPlayer(
            output=output,
            on_output_source_note=lambda *event: source_events.append(event),
        )

        player._handle_event(
            MidiEvent(
                0.0,
                "note_on",
                channel=0,
                note=60,
                velocity=80,
                track=2,
            )
        )
        player._handle_event(
            MidiEvent(
                0.5,
                "note_off",
                channel=0,
                note=60,
                velocity=0,
                track=2,
            )
        )

        self.assertEqual(
            source_events,
            [(60, 2, 0, True), (60, 2, 0, False)],
        )

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

    def test_keyboard_player_reports_the_full_piano_note_position(self) -> None:
        output = FakeOutput()
        displayed: list[tuple[int, bool]] = []
        player = MidiKeyboardPlayer(output=output, on_output_note=lambda *event: displayed.append(event))

        player._handle_event(MidiEvent(time=0.0, kind="note_on", channel=0, note=21, velocity=64))
        player._handle_event(MidiEvent(time=0.1, kind="note_off", channel=0, note=21, velocity=0))
        player._handle_event(MidiEvent(time=0.2, kind="note_on", channel=0, note=108, velocity=64))
        player._handle_event(MidiEvent(time=0.3, kind="note_off", channel=0, note=108, velocity=0))

        self.assertEqual(
            displayed,
            [(21, True), (21, False), (108, True), (108, False)],
        )

    def test_keyboard_player_clears_displayed_notes_when_releasing_all(self) -> None:
        output = FakeOutput()
        displayed: list[tuple[int, bool]] = []
        player = MidiKeyboardPlayer(output=output, on_output_note=lambda *event: displayed.append(event))
        player._handle_event(MidiEvent(time=0.0, kind="note_on", channel=0, note=60, velocity=64))

        player._release_active_note_keys()

        self.assertEqual(displayed, [(60, True), (60, False)])

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

    def test_keyboard_player_reports_stopped_after_output_failure(self) -> None:
        class FailingOutput(FakeOutput):
            def press(self, key: str) -> None:
                raise OSError("blocked")

        states: list[str] = []
        errors: list[str] = []
        player = MidiKeyboardPlayer(
            output=FailingOutput(),
            on_state=states.append,
            on_error=errors.append,
            auto_fit_note_range=True,
        )

        player.play([MidiEvent(time=0.0, kind="note_on", channel=0, note=60, velocity=64)])
        player.wait_until_stopped(timeout=1.0)

        self.assertIn("stopped", states)
        self.assertEqual(errors, ["blocked"])

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

    def test_auto_sustain_uses_the_same_space_key_path(self) -> None:
        output = FakeOutput()
        player = MidiKeyboardPlayer(output=output, auto_sustain=True)

        player._handle_event(
            MidiEvent(
                time=0.1,
                kind=AUTO_SUSTAIN_EVENT_KIND,
                channel=0,
                value=127,
                track=0,
            )
        )
        player._handle_event(
            MidiEvent(
                time=0.5,
                kind=AUTO_SUSTAIN_EVENT_KIND,
                channel=0,
                value=0,
                track=0,
            )
        )

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

    def test_shifted_note_still_uses_rapid_repeat_prevention(self) -> None:
        output = FakeOutput()
        player = MidiKeyboardPlayer(
            output=output,
            repeat_prevention=True,
        )
        events = [
            MidiEvent(time=0.00, kind="note_on", channel=0, note=60, velocity=80, track=0),
            MidiEvent(time=0.01, kind="note_off", channel=0, note=60, velocity=0, track=0),
            MidiEvent(time=0.04, kind="note_on", channel=0, note=60, velocity=80, track=0),
            MidiEvent(time=0.05, kind="note_off", channel=0, note=60, velocity=0, track=0),
        ]
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


if __name__ == "__main__":
    unittest.main()
