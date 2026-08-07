from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app_database import (
    ApplicationDatabase,
    DATABASE_FILE_NAME,
    MidiIndividualSettings,
)
from midi_parser import MidiSummary, MidiTrackSummary


class ApplicationDatabaseTests(unittest.TestCase):
    def test_existing_individual_settings_table_is_extended_with_note_range(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            database_path = root / DATABASE_FILE_NAME
            path = root / "song.mid"
            with sqlite3.connect(database_path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE midi_individual_settings (
                        path TEXT PRIMARY KEY,
                        play_sound INTEGER NOT NULL,
                        auto_fit_note_range INTEGER NOT NULL,
                        repeat_prevention INTEGER NOT NULL,
                        auto_sustain INTEGER NOT NULL,
                        humanize_timing INTEGER NOT NULL,
                        chord_strum INTEGER NOT NULL,
                        chord_optimization INTEGER NOT NULL,
                        use_piano_arrangement INTEGER NOT NULL,
                        playback_speed_percent INTEGER NOT NULL,
                        transpose_semitones INTEGER NOT NULL,
                        octave_shift INTEGER NOT NULL
                    );
                    """
                )
                connection.execute(
                    "INSERT INTO midi_individual_settings VALUES "
                    "(?, 1, 1, 0, 0, 0, 0, 0, 0, 100, 0, 0)",
                    (ApplicationDatabase._path_key(path),),
                )
            connection.close()

            database = ApplicationDatabase(database_path)
            loaded = database.load_midi_individual_settings((path,))[path]
            with sqlite3.connect(database_path) as connection:
                column_names = {
                    str(row[1])
                    for row in connection.execute(
                        "PRAGMA table_info(midi_individual_settings)"
                    )
                }
            connection.close()

            self.assertIsNone(loaded.fit_note_range)
            self.assertIn("fit_note_min", column_names)
            self.assertIn("fit_note_max", column_names)

    def test_midi_individual_settings_round_trip_includes_track_channels(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            path = root / "song.mid"
            path.write_bytes(b"midi")
            stat = path.stat()
            database = ApplicationDatabase(root / DATABASE_FILE_NAME)
            database.save_midi_metadata(
                path,
                (stat.st_size, stat.st_mtime_ns),
                MidiSummary(
                    path=path,
                    duration=1.0,
                    channels=(0, 1),
                    event_count=2,
                ),
            )
            expected = MidiIndividualSettings(
                play_sound=False,
                auto_fit_note_range=True,
                repeat_prevention=True,
                auto_sustain=True,
                humanize_timing=True,
                chord_strum=False,
                chord_optimization=True,
                use_piano_arrangement=False,
                playback_speed_percent=135,
                transpose_semitones=-3,
                octave_shift=1,
                fit_note_range=(40, 76),
                track_channels=((0, 0, True), (1, 1, False)),
            )

            database.save_midi_individual_settings(path, expected)

            self.assertEqual(
                database.load_midi_individual_settings((path,))[path],
                expected,
            )
            self.assertTrue(database.delete_midi_individual_settings(path))
            self.assertEqual(
                database.load_midi_individual_settings((path,)),
                {},
            )

    def test_midi_metadata_round_trip_keeps_only_analysis_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            path = root / "song.mid"
            path.write_bytes(b"midi")
            stat = path.stat()
            database = ApplicationDatabase(root / DATABASE_FILE_NAME)
            summary = MidiSummary(
                path=path,
                duration=123.5,
                channels=(0, 2),
                event_count=987,
                tracks=(
                    MidiTrackSummary(
                        index=0,
                        channels=(0,),
                        name="Lead",
                        instrument_name="Piano",
                    ),
                    MidiTrackSummary(
                        index=1,
                        channels=(2,),
                        name="Strings",
                        instrument_name="Strings",
                    ),
                ),
                note_range=(48, 84),
                midi_format=1,
                file_hash="a" * 64,
            )

            database.save_midi_metadata(
                path,
                (stat.st_size, stat.st_mtime_ns),
                summary,
            )
            loaded = database.load_valid_midi_metadata(
                {path: (stat.st_size, stat.st_mtime_ns)}
            )[path]

            self.assertEqual(loaded.duration, 123.5)
            self.assertEqual(loaded.channels, (0, 2))
            self.assertEqual(loaded.note_range, (48, 84))
            self.assertEqual(loaded.midi_format, 1)
            self.assertEqual(loaded.tracks, summary.tracks)
            connection = sqlite3.connect(database.path)
            try:
                table_names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            finally:
                connection.close()
            self.assertNotIn("midi_events", table_names)
            self.assertNotIn("events", table_names)

    def test_changed_file_stat_invalidates_cached_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            path = root / "song.mid"
            path.write_bytes(b"midi")
            stat = path.stat()
            database = ApplicationDatabase(root / DATABASE_FILE_NAME)
            database.save_midi_metadata(
                path,
                (stat.st_size, stat.st_mtime_ns),
                MidiSummary(
                    path=path,
                    duration=1.0,
                    channels=(0,),
                    event_count=1,
                ),
            )

            loaded = database.load_valid_midi_metadata(
                {path: (stat.st_size + 1, stat.st_mtime_ns)}
            )

            self.assertEqual(loaded, {})

    def test_prune_removes_only_missing_metadata_under_selected_folder(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            selected_folder = root / "selected"
            other_folder = root / "other"
            selected_folder.mkdir()
            other_folder.mkdir()
            current_path = selected_folder / "current.mid"
            removed_path = selected_folder / "removed.mid"
            other_path = other_folder / "other.mid"
            for path in (current_path, removed_path, other_path):
                path.write_bytes(path.name.encode("ascii"))
            database = ApplicationDatabase(root / DATABASE_FILE_NAME)
            file_stats: dict[Path, tuple[int, int]] = {}
            for path in (current_path, removed_path, other_path):
                stat = path.stat()
                file_stat = (stat.st_size, stat.st_mtime_ns)
                file_stats[path] = file_stat
                database.save_midi_metadata(
                    path,
                    file_stat,
                    MidiSummary(
                        path=path,
                        duration=1.0,
                        channels=(0,),
                        event_count=1,
                    ),
                )
            removed_path.unlink()

            removed_count = database.prune_missing_midi_metadata(
                selected_folder,
                (current_path,),
            )
            loaded = database.load_valid_midi_metadata(file_stats)

            self.assertEqual(removed_count, 1)
            self.assertIn(current_path, loaded)
            self.assertNotIn(removed_path, loaded)
            self.assertIn(other_path, loaded)


if __name__ == "__main__":
    unittest.main()
