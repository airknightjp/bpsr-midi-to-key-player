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
        self.assertAlmostEqual(pedal[1].time, 0.675)
        self.assertAlmostEqual(pedal[2].time, 0.875)
        self.assertAlmostEqual(pedal[3].time, 1.7)

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
        self.assertAlmostEqual(pedal[1].time, 1.5)

    def test_plan_repedals_when_a_chord_changes_with_common_tones(self) -> None:
        events = [
            MidiEvent(0.0, "note_on", channel=0, note=60, velocity=90, track=0),
            MidiEvent(0.0, "note_on", channel=0, note=64, velocity=90, track=0),
            MidiEvent(0.0, "note_on", channel=0, note=67, velocity=90, track=0),
            MidiEvent(0.35, "note_off", channel=0, note=60, track=0),
            MidiEvent(0.35, "note_off", channel=0, note=64, track=0),
            MidiEvent(0.35, "note_off", channel=0, note=67, track=0),
            MidiEvent(0.45, "note_on", channel=0, note=60, velocity=90, track=0),
            MidiEvent(0.45, "note_on", channel=0, note=64, velocity=90, track=0),
            MidiEvent(0.45, "note_on", channel=0, note=69, velocity=90, track=0),
            MidiEvent(0.85, "note_off", channel=0, note=60, track=0),
            MidiEvent(0.85, "note_off", channel=0, note=64, track=0),
            MidiEvent(0.85, "note_off", channel=0, note=69, track=0),
        ]

        pedal = [
            event
            for event in plan_auto_sustain(events)
            if event.kind == AUTO_SUSTAIN_EVENT_KIND
        ]

        self.assertEqual([event.value for event in pedal], [127, 0, 127, 0])
        self.assertAlmostEqual(pedal[0].time, 0.075)
        self.assertAlmostEqual(pedal[1].time, 0.425)
        self.assertAlmostEqual(pedal[2].time, 0.525)
        self.assertAlmostEqual(pedal[3].time, 1.35)

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

    def test_plan_does_not_pedal_a_dense_five_note_chord(self) -> None:
        events = [
            MidiEvent(0.0, "note_on", channel=0, note=note, velocity=90, track=0)
            for note in (48, 55, 60, 64, 67)
        ]
        events.extend(
            MidiEvent(0.5, "note_off", channel=0, note=note, track=0)
            for note in (48, 55, 60, 64, 67)
        )

        self.assertFalse(
            any(
                event.kind == AUTO_SUSTAIN_EVENT_KIND
                for event in plan_auto_sustain(events)
            )
        )

    def test_plan_shortens_the_pedal_for_a_dense_four_note_chord(self) -> None:
        events = [
            MidiEvent(0.0, "note_on", channel=0, note=note, velocity=90, track=0)
            for note in (48, 55, 60, 64)
        ]
        events.extend(
            MidiEvent(0.8, "note_off", channel=0, note=note, track=0)
            for note in (48, 55, 60, 64)
        )
        events.extend(
            (
                MidiEvent(0.5, "note_on", channel=0, note=72, velocity=90, track=0),
                MidiEvent(0.9, "note_off", channel=0, note=72, track=0),
            )
        )

        pedal = [
            event
            for event in plan_auto_sustain(events)
            if event.kind == AUTO_SUSTAIN_EVENT_KIND
        ]

        self.assertEqual([event.value for event in pedal], [127, 0, 127, 0])
        self.assertAlmostEqual(pedal[1].time - pedal[0].time, 0.28)

    def test_plan_holds_the_final_pedal_for_half_a_second_after_the_last_note(self) -> None:
        events = [
            MidiEvent(0.0, "note_on", channel=0, note=60, velocity=90, track=0),
            MidiEvent(0.5, "note_off", channel=0, note=60, track=0),
        ]

        pedal = [
            event
            for event in plan_auto_sustain(events)
            if event.kind == AUTO_SUSTAIN_EVENT_KIND
        ]

        self.assertEqual([event.value for event in pedal], [127, 0])
        self.assertAlmostEqual(pedal[-1].time, 1.0)


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

    def test_dense_realtime_chord_does_not_depress_the_pedal(self) -> None:
        changes: list[tuple[int, bool]] = []
        controller = RealtimeAutoSustain(
            lambda channel, enabled: changes.append((channel, enabled)),
            enabled=True,
        )
        try:
            for note in (48, 55, 60, 64, 67):
                controller.note_on(0, note)
            time.sleep(PEDAL_DEPRESSION_DELAY_SECONDS + 0.04)

            self.assertEqual(changes, [])
        finally:
            controller.reset()


if __name__ == "__main__":
    unittest.main()
