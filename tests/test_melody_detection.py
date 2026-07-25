from __future__ import annotations

import unittest

from melody_detection import detect_melody_source
from midi_parser import MidiEvent


def note_on(
    time: float,
    note: int,
    *,
    track: int,
    channel: int,
    velocity: int = 80,
) -> MidiEvent:
    return MidiEvent(
        time=time,
        kind="note_on",
        track=track,
        channel=channel,
        note=note,
        velocity=velocity,
    )


def note_off(
    time: float,
    note: int,
    *,
    track: int,
    channel: int,
) -> MidiEvent:
    return MidiEvent(
        time=time,
        kind="note_off",
        track=track,
        channel=channel,
        note=note,
        velocity=0,
    )


class MelodyDetectionTests(unittest.TestCase):
    def test_prefers_continuous_monophonic_melody_over_chords_and_sparse_accents(
        self,
    ) -> None:
        events: list[MidiEvent] = []
        melody_notes = (72, 74, 76, 77, 79, 77, 76, 74)
        for index, melody_note in enumerate(melody_notes):
            time_value = index * 0.5
            for chord_note in (48, 52, 55):
                events.extend(
                    (
                        note_on(
                            time_value,
                            chord_note,
                            track=0,
                            channel=0,
                            velocity=68,
                        ),
                        note_off(
                            time_value + 0.4,
                            chord_note,
                            track=0,
                            channel=0,
                        ),
                    )
                )
            events.extend(
                (
                    note_on(
                        time_value,
                        melody_note,
                        track=1,
                        channel=1,
                        velocity=92,
                    ),
                    note_off(
                        time_value + 0.35,
                        melody_note,
                        track=1,
                        channel=1,
                    ),
                )
            )
        for time_value, note in ((0.25, 96), (3.25, 98)):
            events.extend(
                (
                    note_on(
                        time_value,
                        note,
                        track=2,
                        channel=2,
                        velocity=110,
                    ),
                    note_off(
                        time_value + 0.05,
                        note,
                        track=2,
                        channel=2,
                    ),
                )
            )

        self.assertEqual(detect_melody_source(events), (1, 1))

    def test_excludes_midi_channel_ten_percussion(self) -> None:
        events = [
            note_on(index * 0.25, 100, track=0, channel=9, velocity=120)
            for index in range(16)
        ]
        events.extend(
            note_on(index * 0.5, 60 + index, track=1, channel=0)
            for index in range(8)
        )

        self.assertEqual(detect_melody_source(events), (1, 0))

    def test_uses_stable_track_channel_order_for_an_exact_tie(self) -> None:
        events = [
            note_on(0.0, 60, track=2, channel=3),
            note_on(0.0, 60, track=1, channel=4),
        ]

        self.assertEqual(detect_melody_source(events), (1, 4))


if __name__ == "__main__":
    unittest.main()
