from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from midi_parser import MidiTrackSummary, parse_midi


def _midi_file(track: bytes, division: int = 480) -> bytes:
    header = (
        b"MThd"
        + (6).to_bytes(4, "big")
        + (0).to_bytes(2, "big")
        + (1).to_bytes(2, "big")
        + division.to_bytes(2, "big")
    )
    return header + b"MTrk" + len(track).to_bytes(4, "big") + track


def _midi_file_with_tracks(*tracks: bytes, division: int = 480) -> bytes:
    midi_format = 0 if len(tracks) == 1 else 1
    header = (
        b"MThd"
        + (6).to_bytes(4, "big")
        + midi_format.to_bytes(2, "big")
        + len(tracks).to_bytes(2, "big")
        + division.to_bytes(2, "big")
    )
    chunks = [
        b"MTrk" + len(track).to_bytes(4, "big") + track
        for track in tracks
    ]
    return header + b"".join(chunks)


class MidiParserTests(unittest.TestCase):
    def test_duration_includes_silence_until_end_of_track(self) -> None:
        track = (
            b"\x00\x90\x3c\x40"
            + b"\x83\x60\x80\x3c\x00"
            + b"\x83\x60\xff\x2f\x00"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "trailing-silence.mid"
            path.write_bytes(_midi_file(track))

            events, summary = parse_midi(path)

        self.assertAlmostEqual(summary.duration, 1.0, places=3)
        self.assertEqual(events[-1].kind, "end")
        self.assertAlmostEqual(events[-1].time, summary.duration, places=3)
        self.assertEqual(summary.event_count, 2)
        self.assertEqual(summary.note_range, (60, 60))

    def test_truncated_track_is_reported_as_invalid(self) -> None:
        malformed = (
            b"MThd"
            + (6).to_bytes(4, "big")
            + (0).to_bytes(2, "big")
            + (1).to_bytes(2, "big")
            + (480).to_bytes(2, "big")
            + b"MTrk"
            + (10).to_bytes(4, "big")
            + b"\x00"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "truncated.mid"
            path.write_bytes(malformed)

            with self.assertRaisesRegex(ValueError, "truncated track"):
                parse_midi(path)

    def test_events_and_summary_keep_track_channel_hierarchy(self) -> None:
        first_track = (
            b"\x00\x90\x3c\x40"
            + b"\x00\x91\x40\x40"
            + b"\x60\x80\x3c\x00"
            + b"\x00\x81\x40\x00"
            + b"\x00\xff\x2f\x00"
        )
        second_track = (
            b"\x00\x91\x43\x40"
            + b"\x60\x81\x43\x00"
            + b"\x00\xff\x2f\x00"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "tracks.mid"
            path.write_bytes(_midi_file_with_tracks(first_track, second_track))

            events, summary = parse_midi(path)

        self.assertEqual(
            summary.tracks,
            (
                MidiTrackSummary(index=0, channels=(0, 1)),
                MidiTrackSummary(index=1, channels=(1,)),
            ),
        )
        self.assertEqual(summary.channels, (0, 1))
        self.assertEqual(summary.note_range, (60, 67))
        self.assertEqual(
            {
                (event.track, event.channel)
                for event in events
                if event.channel is not None
            },
            {(0, 0), (0, 1), (1, 1)},
        )


if __name__ == "__main__":
    unittest.main()
