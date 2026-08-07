from __future__ import annotations

import unittest
from chord_optimization import ChordOptimizationPlan
from midi_parser import MidiEvent
from note_visualization import (
    PianoRollNote,
    build_output_note_range,
    build_piano_roll_notes,
)


class NoteVisualizationTests(unittest.TestCase):
    def test_applies_chord_optimization_to_range_and_piano_roll(self) -> None:
        note_on = MidiEvent(1.0, "note_on", 0, 96, 90, track=0)
        note_off = MidiEvent(2.0, "note_off", 0, 96, 0, track=0)
        plan = ChordOptimizationPlan(
            event_targets={id(note_on): 72, id(note_off): 72},
            event_timing_offsets={id(note_on): 0.01, id(note_off): 0.01},
        )

        note_range = build_output_note_range(
            (note_on, note_off),
            enabled_sources={(0, 0)},
            chord_optimization_plan=plan,
        )
        notes = build_piano_roll_notes(
            (note_on, note_off),
            enabled_sources={(0, 0)},
            chord_optimization_plan=plan,
            chord_strum=True,
        )

        self.assertEqual(note_range, (72, 72))
        self.assertEqual(
            notes,
            (PianoRollNote(1.01, 2.01, 72, source=(0, 0)),),
        )

    def test_preserves_track_channel_source_for_each_note(self) -> None:
        events = [
            MidiEvent(0.0, "note_on", 0, 48, 70, track=0),
            MidiEvent(0.0, "note_on", 0, 52, 70, track=0),
            MidiEvent(0.0, "note_on", 1, 72, 95, track=1),
            MidiEvent(0.5, "note_off", 0, 48, 0, track=0),
            MidiEvent(0.5, "note_off", 0, 52, 0, track=0),
            MidiEvent(0.5, "note_off", 1, 72, 0, track=1),
            MidiEvent(1.0, "note_on", 0, 50, 70, track=0),
            MidiEvent(1.0, "note_on", 0, 53, 70, track=0),
            MidiEvent(1.0, "note_on", 1, 74, 95, track=1),
            MidiEvent(1.5, "note_off", 0, 50, 0, track=0),
            MidiEvent(1.5, "note_off", 0, 53, 0, track=0),
            MidiEvent(1.5, "note_off", 1, 74, 0, track=1),
        ]

        notes = build_piano_roll_notes(events)

        self.assertEqual(
            {(note.note, note.source) for note in notes},
            {
                (48, (0, 0)),
                (52, (0, 0)),
                (72, (1, 1)),
                (50, (0, 0)),
                (53, (0, 0)),
                (74, (1, 1)),
            },
        )

    def test_builds_full_piano_note_spans(self) -> None:
        events = [
            MidiEvent(0.5, "note_on", channel=0, note=21, velocity=90, track=0),
            MidiEvent(1.5, "note_off", channel=0, note=21, velocity=0, track=0),
            MidiEvent(2.0, "note_on", channel=0, note=108, velocity=90, track=0),
            MidiEvent(2.5, "note_off", channel=0, note=108, velocity=0, track=0),
        ]

        notes = build_piano_roll_notes(events, enabled_sources={(0, 0)})

        self.assertEqual(
            [(note.start, note.end, note.note) for note in notes],
            [(0.5, 1.5, 21), (2.0, 2.5, 108)],
        )

    def test_applies_pitch_shift_and_three_octave_fit(self) -> None:
        events = [
            MidiEvent(0.0, "note_on", channel=0, note=24, velocity=90, track=0),
            MidiEvent(1.0, "note_off", channel=0, note=24, velocity=0, track=0),
        ]

        notes = build_piano_roll_notes(
            events,
            enabled_sources={(0, 0)},
            auto_fit_note_range=True,
            transpose_semitones=2,
            octave_shift=1,
        )

        self.assertEqual([note.note for note in notes], [50])

    def test_applies_selected_fit_range_to_visual_notes(self) -> None:
        events = [
            MidiEvent(0.0, "note_on", channel=0, note=72, velocity=90, track=0),
            MidiEvent(1.0, "note_off", channel=0, note=72, velocity=0, track=0),
        ]

        notes = build_piano_roll_notes(
            events,
            enabled_sources={(0, 0)},
            auto_fit_note_range=True,
            fit_note_range=(60, 71),
        )
        note_range = build_output_note_range(
            events,
            enabled_sources={(0, 0)},
            auto_fit_note_range=True,
            fit_note_range=(60, 71),
        )

        self.assertEqual([note.note for note in notes], [60])
        self.assertEqual(note_range, (60, 60))

    def test_output_range_uses_final_transformed_notes(self) -> None:
        events = [
            MidiEvent(0.0, "note_on", channel=0, note=24, velocity=90, track=0),
            MidiEvent(1.0, "note_on", channel=0, note=83, velocity=90, track=0),
            MidiEvent(2.0, "note_on", channel=1, note=96, velocity=90, track=1),
        ]

        note_range = build_output_note_range(
            events,
            enabled_sources={(0, 0)},
            auto_fit_note_range=True,
            transpose_semitones=2,
            octave_shift=1,
        )

        self.assertEqual(note_range, (50, 73))

    def test_excludes_disabled_sources_and_notes_outside_full_piano(self) -> None:
        events = [
            MidiEvent(0.0, "note_on", channel=0, note=20, velocity=90, track=0),
            MidiEvent(0.5, "note_off", channel=0, note=20, velocity=0, track=0),
            MidiEvent(1.0, "note_on", channel=1, note=60, velocity=90, track=1),
            MidiEvent(1.5, "note_off", channel=1, note=60, velocity=0, track=1),
        ]

        notes = build_piano_roll_notes(events, enabled_sources={(0, 0)})

        self.assertEqual(notes, ())

    def test_overlapping_same_notes_are_paired_in_order(self) -> None:
        events = [
            MidiEvent(0.0, "note_on", channel=0, note=60, velocity=90, track=0),
            MidiEvent(0.2, "note_on", channel=0, note=60, velocity=90, track=0),
            MidiEvent(0.8, "note_off", channel=0, note=60, velocity=0, track=0),
            MidiEvent(1.0, "note_off", channel=0, note=60, velocity=0, track=0),
        ]

        notes = build_piano_roll_notes(events, enabled_sources={(0, 0)})

        self.assertEqual(
            [(note.start, note.end) for note in notes],
            [(0.0, 0.8), (0.2, 1.0)],
        )

    def test_short_note_keeps_its_actual_output_duration(self) -> None:
        events = [
            MidiEvent(0.0, "note_on", channel=0, note=60, velocity=90, track=0),
            MidiEvent(0.01, "note_off", channel=0, note=60, velocity=0, track=0),
        ]

        notes = build_piano_roll_notes(events, enabled_sources={(0, 0)})

        self.assertEqual(
            notes,
            (PianoRollNote(0.0, 0.01, 60, source=(0, 0)),),
        )

    def test_applies_timing_corrections_to_the_visual_sequence(self) -> None:
        events = [
            MidiEvent(1.0, "note_on", channel=0, note=60, velocity=90, track=0),
            MidiEvent(1.0, "note_on", channel=0, note=64, velocity=90, track=0),
            MidiEvent(2.0, "note_off", channel=0, note=60, velocity=0, track=0),
            MidiEvent(2.0, "note_off", channel=0, note=64, velocity=0, track=0),
        ]

        plain = build_piano_roll_notes(events, enabled_sources={(0, 0)})
        corrected = build_piano_roll_notes(
            events,
            enabled_sources={(0, 0)},
            humanize_timing=True,
            chord_strum=True,
        )

        self.assertNotEqual(corrected, plain)
        self.assertNotEqual(corrected[0].start, corrected[1].start)

    def test_auto_sustain_extends_visual_notes_until_pedal_release(self) -> None:
        events = [
            MidiEvent(0.0, "note_on", channel=0, note=60, velocity=90, track=0),
            MidiEvent(0.5, "note_off", channel=0, note=60, velocity=0, track=0),
            MidiEvent(2.0, "end"),
        ]

        plain = build_piano_roll_notes(events, enabled_sources={(0, 0)})
        sustained = build_piano_roll_notes(
            events,
            enabled_sources={(0, 0)},
            auto_sustain=True,
        )

        self.assertEqual(plain[0].end, 0.5)
        self.assertGreater(sustained[0].end, plain[0].end)

    def test_repeat_prevention_uses_the_selected_playback_speed(self) -> None:
        events = [
            MidiEvent(0.00, "note_on", channel=0, note=60, velocity=90, track=0),
            MidiEvent(0.01, "note_off", channel=0, note=60, velocity=0, track=0),
            MidiEvent(0.06, "note_on", channel=0, note=60, velocity=90, track=0),
            MidiEvent(0.07, "note_off", channel=0, note=60, velocity=0, track=0),
        ]

        normal = build_piano_roll_notes(
            events,
            enabled_sources={(0, 0)},
            repeat_prevention=True,
            playback_speed_percent=100,
        )
        fast = build_piano_roll_notes(
            events,
            enabled_sources={(0, 0)},
            repeat_prevention=True,
            playback_speed_percent=200,
        )

        self.assertEqual(len(normal), 2)
        self.assertEqual(len(fast), 1)


if __name__ == "__main__":
    unittest.main()
