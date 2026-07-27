from __future__ import annotations

import tempfile
import time
import unittest
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

from midi_parser import (
    MidiEvent,
    MidiSummary,
    MidiTempoChange,
    MidiTimeSignature,
    MidiTrackSummary,
)
from piano_arrangement import analyze_piano_arrangement
from piano_arrangement_cache import (
    load_arrangement_cache,
    save_arrangement_cache,
)
from piano_arrangement_models import (
    ArrangementPlan,
    ArrangementQuality,
    Hand,
    PianoArrangementConfig,
)


def _fixture() -> tuple[list[MidiEvent], MidiSummary]:
    events: list[MidiEvent] = []
    note_id = 0

    def add_note(
        beat: float,
        duration: float,
        pitch: int,
        velocity: int,
        track: int,
        channel: int,
    ) -> None:
        nonlocal note_id
        events.extend(
            (
                MidiEvent(
                    time=beat * 0.5,
                    kind="note_on",
                    channel=channel,
                    note=pitch,
                    velocity=velocity,
                    track=track,
                    tick=round(beat * 480),
                    beat=beat,
                    note_id=note_id,
                ),
                MidiEvent(
                    time=(beat + duration) * 0.5,
                    kind="note_off",
                    channel=channel,
                    note=pitch,
                    velocity=0,
                    track=track,
                    tick=round((beat + duration) * 480),
                    beat=beat + duration,
                    note_id=note_id,
                ),
            )
        )
        note_id += 1

    melody = (64, 67, 69, 67, 65, 64, 62, 64)
    for index, pitch in enumerate(melody):
        add_note(index, 0.82, pitch, 104, 0, 0)
    for beat, root in ((0, 48), (2, 53), (4, 55), (6, 48)):
        for interval in (0, 4, 7, 12):
            add_note(beat, 1.8, root + interval, 68, 1, 1)
        add_note(beat, 1.6, root - 12, 84, 2, 2)
    for beat in range(8):
        add_note(float(beat), 0.1, 36 if beat % 2 == 0 else 42, 90, 3, 9)
    events.sort(
        key=lambda event: (
            event.time,
            0 if event.kind == "note_off" else 1,
            event.track or 0,
            event.note or 0,
        )
    )
    events.append(MidiEvent(time=4.0, kind="end", tick=3840, beat=8.0))
    summary = MidiSummary(
        path=Path("fixture.mid"),
        duration=4.0,
        channels=(0, 1, 2, 9),
        event_count=len(events) - 1,
        tracks=(
            MidiTrackSummary(0, (0,), "Lead", "Flute"),
            MidiTrackSummary(1, (1,), "Chords", "Strings"),
            MidiTrackSummary(2, (2,), "Bass", "Bass"),
            MidiTrackSummary(3, (9,), "Drums", "Drums"),
        ),
        note_range=(36, 76),
        midi_format=1,
        ticks_per_beat=480,
        tempo_changes=(MidiTempoChange(0, 0.0, 0.0, 500_000),),
        time_signatures=(MidiTimeSignature(0, 0.0, 4, 4),),
        file_hash="a" * 64,
    )
    return events, summary


class PianoArrangementTests(unittest.TestCase):
    def _analyze(
        self,
        config: PianoArrangementConfig | None = None,
    ) -> ArrangementPlan:
        events, summary = _fixture()
        with patch("piano_arrangement.save_arrangement_cache"):
            return analyze_piano_arrangement(
                (events, summary),
                config,
                use_cache=False,
            )

    def test_balanced_plan_is_playable_and_excludes_drum_notes(self) -> None:
        plan = self._analyze()
        events, _summary = _fixture()
        drum_ids = {
            event.note_id
            for event in events
            if event.kind == "note_on" and event.channel == 9
        }
        grouped: dict[tuple[int, Hand], list[int]] = defaultdict(list)
        for note in plan.notes:
            self.assertGreaterEqual(note.pitch, 21)
            self.assertLessEqual(note.pitch, 108)
            self.assertGreater(note.end_second, note.start_second)
            self.assertTrue(drum_ids.isdisjoint(note.source_note_ids))
            self.assertIsNotNone(note.finger)
            grouped[(round(note.start_beat * 96), note.hand)].append(note.pitch)
        for pitches in grouped.values():
            self.assertLessEqual(len(pitches), 5)
            self.assertLessEqual(max(pitches) - min(pitches), 16)
        self.assertEqual(plan.report.hard_violation_count, 0)
        self.assertGreater(plan.report.weighted_source_coverage, 0.35)

    def test_same_input_and_config_are_deterministic(self) -> None:
        first = self._analyze()
        second = self._analyze()
        self.assertEqual(first.notes, second.notes)
        self.assertEqual(first.pedal_events, second.pedal_events)
        self.assertEqual(first.sections, second.sections)
        self.assertEqual(first.chords, second.chords)

    def test_plan_restores_directly_playable_events_without_writing_midi(self) -> None:
        plan = self._analyze()
        events = plan.to_midi_events()
        self.assertEqual(events[-1].kind, "end")
        self.assertEqual(
            events,
            sorted(
                events[:-1],
                key=lambda event: (
                    event.time,
                    0 if event.kind == "note_off" else 1,
                    event.track if event.track is not None else -1,
                    event.channel if event.channel is not None else -1,
                    event.note if event.note is not None else -1,
                ),
            )
            + [events[-1]],
        )
        note_ons = {
            event.note_id for event in events if event.kind == "note_on"
        }
        note_offs = {
            event.note_id for event in events if event.kind == "note_off"
        }
        self.assertEqual(note_ons, note_offs)

    def test_cache_round_trip_contains_the_runtime_arrangement_plan(self) -> None:
        plan = self._analyze()
        config = PianoArrangementConfig()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch(
                "piano_arrangement_models.arrangement_cache_root",
                return_value=root,
            ):
                path = save_arrangement_cache(plan, config)
                restored = load_arrangement_cache(plan.source_file_hash, config)
        self.assertEqual(path.suffix, ".json")
        self.assertEqual(restored, plan)
        self.assertFalse(any(root.glob("*.mid")))

    def test_beta_is_the_only_arrangement_quality(self) -> None:
        self.assertEqual(list(ArrangementQuality), [ArrangementQuality.BETA])
        self.assertEqual(
            PianoArrangementConfig().normalized().quality,
            ArrangementQuality.BETA,
        )

    def test_beta_fixture_finishes_within_a_practical_budget(self) -> None:
        started = time.perf_counter()
        plan = self._analyze(
            PianoArrangementConfig(quality=ArrangementQuality.BETA)
        )
        self.assertTrue(plan.notes)
        self.assertLess(time.perf_counter() - started, 2.0)


if __name__ == "__main__":
    unittest.main()
