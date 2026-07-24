from __future__ import annotations

import time
import unittest

from auto_sustain import (
    AUTO_SUSTAIN_EVENT_KIND,
    PEDAL_DEPRESSION_DELAY_SECONDS,
    RealtimeAutoSustain,
    plan_auto_sustain,
)
from midi_parser import MidiEvent


class AutoSustainPlanTests(unittest.TestCase):
    def test_plan_repedals_before_a_semitone_harmony_change(self) -> None:
        events = [
            MidiEvent(0.0, "note_on", channel=0, note=60, velocity=90, track=0),
            MidiEvent(0.5, "note_off", channel=0, note=60, track=0),
            MidiEvent(0.8, "note_on", channel=0, note=61, velocity=90, track=0),
            MidiEvent(1.2, "note_off", channel=0, note=61, track=0),
            MidiEvent(1.3, "end"),
        ]

        planned = plan_auto_sustain(events)
        pedal = [event for event in planned if event.kind == AUTO_SUSTAIN_EVENT_KIND]

        self.assertEqual([event.value for event in pedal], [127, 0, 127, 0])
        self.assertAlmostEqual(pedal[0].time, 0.075)
        self.assertAlmostEqual(pedal[1].time, 0.775)
        self.assertAlmostEqual(pedal[2].time, 0.875)
        self.assertAlmostEqual(pedal[3].time, 1.55)

    def test_plan_keeps_pedal_for_a_repeated_pitch(self) -> None:
        events = [
            MidiEvent(0.0, "note_on", channel=0, note=60, velocity=90, track=0),
            MidiEvent(0.4, "note_off", channel=0, note=60, track=0),
            MidiEvent(0.6, "note_on", channel=0, note=60, velocity=90, track=0),
            MidiEvent(1.0, "note_off", channel=0, note=60, track=0),
        ]

        pedal = [
            event
            for event in plan_auto_sustain(events)
            if event.kind == AUTO_SUSTAIN_EVENT_KIND
        ]

        self.assertEqual([event.value for event in pedal], [127, 0])
        self.assertAlmostEqual(pedal[0].time, 0.075)
        self.assertAlmostEqual(pedal[1].time, 1.325)

    def test_plan_preserves_short_staccato(self) -> None:
        events = [
            MidiEvent(0.0, "note_on", channel=0, note=60, velocity=90, track=0),
            MidiEvent(0.05, "note_off", channel=0, note=60, track=0),
        ]

        self.assertFalse(
            any(
                event.kind == AUTO_SUSTAIN_EVENT_KIND
                for event in plan_auto_sustain(events)
            )
        )

    def test_plan_defers_to_explicit_cc64_for_the_same_source(self) -> None:
        events = [
            MidiEvent(0.0, "note_on", channel=0, note=60, velocity=90, track=0),
            MidiEvent(0.1, "sustain", channel=0, value=127, track=0),
            MidiEvent(0.5, "note_off", channel=0, note=60, track=0),
            MidiEvent(0.7, "sustain", channel=0, value=0, track=0),
        ]

        self.assertFalse(
            any(
                event.kind == AUTO_SUSTAIN_EVENT_KIND
                for event in plan_auto_sustain(events)
            )
        )

    def test_explicit_cc64_takes_priority_across_tracks_on_the_same_channel(self) -> None:
        events = [
            MidiEvent(0.0, "note_on", channel=0, note=60, velocity=90, track=1),
            MidiEvent(0.1, "sustain", channel=0, value=127, track=0),
            MidiEvent(0.5, "note_off", channel=0, note=60, track=1),
            MidiEvent(0.7, "sustain", channel=0, value=0, track=0),
        ]

        self.assertFalse(
            any(
                event.kind == AUTO_SUSTAIN_EVENT_KIND
                for event in plan_auto_sustain(events)
            )
        )

    def test_plan_does_not_pedal_the_percussion_channel(self) -> None:
        events = [
            MidiEvent(0.0, "note_on", channel=9, note=36, velocity=90, track=0),
            MidiEvent(0.5, "note_off", channel=9, note=36, track=0),
        ]

        self.assertFalse(
            any(
                event.kind == AUTO_SUSTAIN_EVENT_KIND
                for event in plan_auto_sustain(events)
            )
        )


class RealtimeAutoSustainTests(unittest.TestCase):
    def test_long_note_is_pedalled_and_semitone_change_clears_it(self) -> None:
        changes: list[tuple[int, bool]] = []
        controller = RealtimeAutoSustain(
            lambda channel, enabled: changes.append((channel, enabled)),
            enabled=True,
        )
        try:
            controller.note_on(0, 60)
            time.sleep(PEDAL_DEPRESSION_DELAY_SECONDS + 0.04)
            controller.note_on(0, 61)

            self.assertGreaterEqual(len(changes), 2)
            self.assertEqual(changes[:2], [(0, True), (0, False)])
        finally:
            controller.reset()

    def test_short_note_finishes_before_pedal_depression(self) -> None:
        changes: list[tuple[int, bool]] = []
        controller = RealtimeAutoSustain(
            lambda channel, enabled: changes.append((channel, enabled)),
            enabled=True,
        )
        try:
            controller.note_on(0, 60)
            controller.note_off(0, 60)
            time.sleep(PEDAL_DEPRESSION_DELAY_SECONDS + 0.04)
            self.assertEqual(changes, [])
        finally:
            controller.reset()

    def test_manual_cc64_takes_over_the_channel(self) -> None:
        changes: list[tuple[int, bool]] = []
        controller = RealtimeAutoSustain(
            lambda channel, enabled: changes.append((channel, enabled)),
            enabled=True,
        )
        try:
            controller.note_on(0, 60)
            controller.manual_sustain(0)
            time.sleep(PEDAL_DEPRESSION_DELAY_SECONDS + 0.04)
            controller.note_on(0, 64)
            self.assertEqual(changes, [])
        finally:
            controller.reset()


if __name__ == "__main__":
    unittest.main()
