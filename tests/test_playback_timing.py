from __future__ import annotations

import unittest

from midi_parser import MidiEvent
from playback_timing import (
    CHORD_STRUM_MAX_OFFSET_SECONDS,
    PlaybackClock,
    PlaybackTimeline,
    prepare_playback_events,
)


class FixedRandom:
    def triangular(self, _low: float, _high: float, _mode: float) -> float:
        return 0.0


class SequenceRandom:
    def __init__(self, *values: float):
        self.values = list(values)

    def uniform(self, _low: float, _high: float) -> float:
        return self.values.pop(0)


class PlaybackTimingTests(unittest.TestCase):
    def test_chord_strum_uses_random_short_offsets_and_note_off_keeps_offset(self) -> None:
        events = [
            MidiEvent(time=1.0, kind="note_on", channel=0, note=67, velocity=64),
            MidiEvent(time=1.0, kind="note_on", channel=0, note=60, velocity=64),
            MidiEvent(time=1.0, kind="note_on", channel=0, note=64, velocity=64),
            MidiEvent(time=2.0, kind="note_off", channel=0, note=67, velocity=0),
            MidiEvent(time=2.0, kind="note_off", channel=0, note=60, velocity=0),
            MidiEvent(time=2.0, kind="note_off", channel=0, note=64, velocity=0),
        ]

        prepared = prepare_playback_events(
            events,
            SequenceRandom(0.009, 0.001, 0.006),
        )
        note_ons = [item for item in prepared if item.event.kind == "note_on"]
        note_offs = [item for item in prepared if item.event.kind == "note_off"]

        self.assertEqual([item.event.note for item in note_ons], [64, 67, 60])
        self.assertEqual(
            [round(item.strum_offset, 3) for item in note_ons],
            [0.0, 0.005, 0.008],
        )
        self.assertLessEqual(max(item.strum_offset for item in note_ons), CHORD_STRUM_MAX_OFFSET_SECONDS)
        self.assertEqual(
            {item.event.note: item.strum_offset for item in note_offs},
            {item.event.note: item.strum_offset for item in note_ons},
        )

    def test_current_chord_note_reschedules_when_chord_strum_changes(self) -> None:
        event = MidiEvent(time=1.0, kind="note_on", channel=0, note=67, velocity=64)
        prepared = prepare_playback_events(
            [
                MidiEvent(time=1.0, kind="note_on", channel=0, note=60, velocity=64),
                MidiEvent(time=1.0, kind="note_on", channel=0, note=64, velocity=64),
                event,
            ],
            SequenceRandom(0.0, 0.004, 0.009),
        )
        high_note = next(item for item in prepared if item.event.note == 67)
        timeline = PlaybackTimeline(0.0, FixedRandom())

        self.assertEqual(
            timeline.scheduled_time(high_note, chord_strum=False),
            1.0,
        )
        self.assertEqual(
            timeline.scheduled_time(high_note, chord_strum=True),
            1.009,
        )
        self.assertEqual(
            timeline.scheduled_time(high_note, chord_strum=False),
            1.0,
        )

    def test_two_note_chord_is_strummed(self) -> None:
        prepared = prepare_playback_events(
            [
                MidiEvent(time=1.0, kind="note_on", channel=0, note=60, velocity=64),
                MidiEvent(time=1.0, kind="note_on", channel=0, note=67, velocity=64),
            ],
            SequenceRandom(0.008, 0.002),
        )

        self.assertEqual(
            [item.event.note for item in prepared],
            [67, 60],
        )
        self.assertEqual(
            [round(item.strum_offset, 3) for item in prepared],
            [0.0, 0.006],
        )

    def test_optimized_offsets_replace_random_order_for_simultaneous_chord(self) -> None:
        events = [
            MidiEvent(time=1.0, kind="note_on", channel=0, note=60, velocity=64),
            MidiEvent(time=1.0, kind="note_on", channel=0, note=64, velocity=64),
            MidiEvent(time=1.0, kind="note_on", channel=0, note=67, velocity=64),
        ]
        offsets = {60: 0.002, 64: 0.009, 67: 0.0}

        prepared = prepare_playback_events(
            events,
            SequenceRandom(0.011, 0.001, 0.006),
            lambda event: offsets[event.note],
        )

        self.assertEqual([item.event.note for item in prepared], [67, 60, 64])
        self.assertEqual(
            [item.strum_offset for item in prepared],
            [0.0, 0.002, 0.009],
        )

    def test_optimized_offset_only_applies_while_chord_strum_is_enabled(self) -> None:
        event = MidiEvent(time=1.0, kind="note_on", channel=0, note=60, velocity=64)
        timeline = PlaybackTimeline(0.0, FixedRandom())

        self.assertEqual(
            timeline.scheduled_time(
                event,
                chord_strum=False,
                chord_optimization_offset=0.009,
            ),
            1.0,
        )
        self.assertEqual(
            timeline.scheduled_time(
                event,
                chord_strum=True,
                chord_optimization_offset=0.009,
            ),
            1.009,
        )

    def test_speed_change_preserves_position_and_applies_immediately(self) -> None:
        now = [100.0]
        clock = PlaybackClock(
            start_position=5.0,
            speed_percent=100,
            time_source=lambda: now[0],
        )

        now[0] = 101.0
        self.assertEqual(clock.position(), 6.0)
        clock.set_speed_percent(200)
        self.assertEqual(clock.position(), 6.0)
        now[0] = 101.5
        self.assertEqual(clock.position(), 7.0)
        clock.set_speed_percent(50)
        now[0] = 102.5
        self.assertEqual(clock.position(), 7.5)

    def test_ten_percent_speed_is_supported_and_lower_values_are_clamped(self) -> None:
        now = [100.0]
        clock = PlaybackClock(
            start_position=0.0,
            speed_percent=5,
            time_source=lambda: now[0],
        )

        now[0] = 110.0
        self.assertEqual(clock.position(), 1.0)
        clock.set_speed_percent(10)
        now[0] = 120.0
        self.assertEqual(clock.position(), 2.0)


if __name__ == "__main__":
    unittest.main()
