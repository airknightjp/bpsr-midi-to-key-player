from __future__ import annotations

import unittest

from chord_optimization import (
    EXPRESSIVE_CHORD_MAX_OFFSET_SECONDS,
    ChordOptimizationCancelled,
    build_chord_optimization_plan,
)
from midi_parser import MidiEvent


def note_on(
    time: float,
    note: int,
    *,
    channel: int = 0,
    track: int = 0,
    velocity: int = 80,
) -> MidiEvent:
    return MidiEvent(
        time=time,
        kind="note_on",
        channel=channel,
        note=note,
        velocity=velocity,
        track=track,
    )


def note_off(
    time: float,
    note: int,
    *,
    channel: int = 0,
    track: int = 0,
) -> MidiEvent:
    return MidiEvent(
        time=time,
        kind="note_off",
        channel=channel,
        note=note,
        velocity=0,
        track=track,
    )


def planned_notes(plan, events: list[MidiEvent]) -> list[int | None]:
    return [plan.target_for(event)[1] for event in events]


class ChordOptimizationTests(unittest.TestCase):
    def test_reports_monotonic_progress_from_zero_to_one_hundred(self) -> None:
        progress: list[int] = []
        events = [note_on(index * 0.1, 60 + index % 12) for index in range(40)]

        build_chord_optimization_plan(
            events,
            auto_fit_note_range=False,
            progress_callback=progress.append,
        )

        self.assertEqual(progress[0], 0)
        self.assertEqual(progress[-1], 100)
        self.assertEqual(progress, sorted(set(progress)))

    def test_cancels_obsolete_plan_during_analysis(self) -> None:
        progress: list[int] = []

        with self.assertRaises(ChordOptimizationCancelled):
            build_chord_optimization_plan(
                [note_on(index * 0.1, 60) for index in range(100)],
                auto_fit_note_range=False,
                progress_callback=progress.append,
                cancel_callback=lambda: bool(progress and progress[-1] >= 25),
            )

        self.assertGreaterEqual(progress[-1], 25)
        self.assertLess(progress[-1], 100)

    def test_wide_chord_is_optimized_into_one_playable_window(self) -> None:
        events = [
            note_on(0.0, 36),
            note_on(0.0, 64),
            note_on(0.0, 79),
            note_on(0.0, 96),
        ]

        plan = build_chord_optimization_plan(events, auto_fit_note_range=False)
        targets = planned_notes(plan, events)

        self.assertEqual(targets, [48, 64, 67, 72])
        self.assertEqual(len(set(targets)), len(targets))
        self.assertTrue(all(48 <= target <= 83 for target in targets if target is not None))

    def test_high_chord_uses_the_high_external_range_when_auto_fit_is_off(self) -> None:
        events = [note_on(0.0, note) for note in (84, 88, 91)]

        plan = build_chord_optimization_plan(events, auto_fit_note_range=False)

        self.assertEqual(planned_notes(plan, events), [84, 88, 91])

    def test_auto_fit_keeps_every_optimized_note_in_the_base_three_octaves(self) -> None:
        events = [note_on(0.0, note) for note in (24, 52, 79, 108)]

        plan = build_chord_optimization_plan(events, auto_fit_note_range=True)
        targets = planned_notes(plan, events)

        self.assertTrue(all(48 <= target <= 83 for target in targets if target is not None))
        self.assertEqual(
            [target % 12 for target in targets if target is not None],
            [event.note % 12 for event in events],
        )

    def test_held_notes_prevent_an_external_range_change(self) -> None:
        first_on = note_on(0.0, 60)
        high_chord = [note_on(0.5, note) for note in (96, 100, 103)]
        events = [
            first_on,
            *high_chord,
            note_off(1.0, 60),
            *(note_off(1.0, note) for note in (96, 100, 103)),
        ]

        plan = build_chord_optimization_plan(events, auto_fit_note_range=False)
        targets = planned_notes(plan, high_chord)

        self.assertTrue(all(48 <= target <= 83 for target in targets if target is not None))
        self.assertNotIn(plan.target_for(first_on)[1], targets)

    def test_duplicate_simultaneous_pitch_keeps_stronger_note_and_matching_off(self) -> None:
        quiet_on = note_on(0.0, 60, channel=0, track=0, velocity=40)
        strong_on = note_on(0.0, 60, channel=1, track=1, velocity=100)
        quiet_off = note_off(1.0, 60, channel=0, track=0)
        strong_off = note_off(1.0, 60, channel=1, track=1)
        events = [quiet_on, strong_on, quiet_off, strong_off]

        plan = build_chord_optimization_plan(events, auto_fit_note_range=True)

        self.assertEqual(plan.target_for(quiet_on), (True, None))
        self.assertEqual(plan.target_for(quiet_off), (True, None))
        self.assertEqual(plan.target_for(strong_on), (True, 60))
        self.assertEqual(plan.target_for(strong_off), (True, 60))

    def test_nearby_onsets_share_an_optimization_group_without_changing_their_times(self) -> None:
        events = [
            note_on(1.000, 36),
            note_on(1.020, 64),
            note_on(1.034, 96),
        ]

        plan = build_chord_optimization_plan(events, auto_fit_note_range=False)
        targets = planned_notes(plan, events)

        self.assertTrue(all(48 <= target <= 83 for target in targets if target is not None))
        self.assertEqual([event.time for event in events], [1.000, 1.020, 1.034])
        self.assertEqual(
            [plan.timing_offset_for(event) for event in events],
            [0.0, 0.0, 0.0],
        )

    def test_simultaneous_chord_leads_with_top_voice_and_delays_inner_voice(self) -> None:
        bass = note_on(1.0, 60, velocity=80)
        inner = note_on(1.0, 64, velocity=40)
        melody = note_on(1.0, 67, velocity=100)

        plan = build_chord_optimization_plan(
            [bass, inner, melody],
            auto_fit_note_range=True,
        )

        bass_offset = plan.timing_offset_for(bass)
        inner_offset = plan.timing_offset_for(inner)
        melody_offset = plan.timing_offset_for(melody)
        self.assertEqual(melody_offset, 0.0)
        self.assertGreater(bass_offset, melody_offset)
        self.assertGreater(inner_offset, bass_offset)
        self.assertLessEqual(inner_offset, EXPRESSIVE_CHORD_MAX_OFFSET_SECONDS)

    def test_note_off_inherits_optimized_onset_offset(self) -> None:
        note_ons = [note_on(0.0, note) for note in (60, 64, 67)]
        note_offs = [note_off(1.0, note) for note in (60, 64, 67)]

        plan = build_chord_optimization_plan(
            [*note_ons, *note_offs],
            auto_fit_note_range=True,
        )

        self.assertEqual(
            [plan.timing_offset_for(event) for event in note_offs],
            [plan.timing_offset_for(event) for event in note_ons],
        )

    def test_transpose_is_applied_before_selecting_the_playable_window(self) -> None:
        events = [note_on(0.0, note) for note in (82, 86, 89)]

        plan = build_chord_optimization_plan(
            events,
            auto_fit_note_range=False,
            transpose_semitones=2,
        )

        self.assertEqual(planned_notes(plan, events), [84, 88, 91])

    def test_voice_leading_keeps_common_tone_between_adjacent_chords(self) -> None:
        first = [note_on(0.0, note) for note in (60, 64, 67)]
        first_off = [note_off(0.5, note) for note in (60, 64, 67)]
        second = [note_on(1.0, note) for note in (60, 65, 69)]

        plan = build_chord_optimization_plan(
            [*first, *first_off, *second],
            auto_fit_note_range=True,
        )

        self.assertEqual(plan.target_for(first[0])[1], 60)
        self.assertEqual(plan.target_for(second[0])[1], 60)

    def test_long_rest_starts_a_fresh_phrase_but_short_rest_keeps_continuity(self) -> None:
        first = [note_on(0.0, note) for note in (84, 88, 91)]
        first_off = [note_off(0.1, note) for note in (84, 88, 91)]
        short_rest_chord = [note_on(0.7, note) for note in (24, 28, 31)]
        long_rest_chord = [note_on(1.0, note) for note in (24, 28, 31)]

        short_plan = build_chord_optimization_plan(
            [*first, *first_off, *short_rest_chord],
            auto_fit_note_range=False,
        )
        long_plan = build_chord_optimization_plan(
            [*first, *first_off, *long_rest_chord],
            auto_fit_note_range=False,
        )

        self.assertTrue(
            all(note >= 84 for note in planned_notes(short_plan, short_rest_chord))
        )
        self.assertTrue(
            all(note <= 47 for note in planned_notes(long_plan, long_rest_chord))
        )

    def test_current_playback_speed_continuously_changes_range_switch_planning(self) -> None:
        first = [note_on(0.0, note) for note in (84, 88, 91)]
        first_off = [note_off(0.05, note) for note in (84, 88, 91)]
        second = [note_on(0.2, note) for note in (24, 28, 32)]
        events = [*first, *first_off, *second]

        faster_plan = build_chord_optimization_plan(
            events,
            auto_fit_note_range=False,
            playback_speed_percent=137,
        )
        slow_plan = build_chord_optimization_plan(
            events,
            auto_fit_note_range=False,
            playback_speed_percent=73,
        )

        self.assertTrue(all(note >= 84 for note in planned_notes(faster_plan, second)))
        self.assertTrue(all(note <= 47 for note in planned_notes(slow_plan, second)))

    def test_auto_fit_range_does_not_expand_at_slow_playback_speed(self) -> None:
        events = [
            note_on(0.0, 96),
            note_off(0.05, 96),
            note_on(0.2, 24),
        ]

        normal_plan = build_chord_optimization_plan(
            events,
            auto_fit_note_range=True,
            playback_speed_percent=100,
        )
        slow_plan = build_chord_optimization_plan(
            events,
            auto_fit_note_range=True,
            playback_speed_percent=50,
        )

        self.assertEqual(planned_notes(normal_plan, events), planned_notes(slow_plan, events))
        self.assertTrue(
            all(
                48 <= note <= 83
                for note in planned_notes(slow_plan, events)
                if note is not None
            )
        )


if __name__ == "__main__":
    unittest.main()
