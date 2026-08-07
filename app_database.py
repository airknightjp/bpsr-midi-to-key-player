from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from midi_parser import MidiSummary, MidiTrackSummary


DATABASE_FILE_NAME = "bpsr_midi_to_key_player.db"
DATABASE_SCHEMA_VERSION = 3
SQLITE_PARAMETER_BATCH_SIZE = 500

_DATABASE_LOCK = threading.RLock()


@dataclass(frozen=True)
class MidiMetadata:
    path: Path
    file_size: int
    modified_ns: int
    duration: float
    channels: tuple[int, ...]
    event_count: int
    tracks: tuple[MidiTrackSummary, ...]
    note_range: tuple[int, int] | None
    midi_format: int
    file_hash: str


@dataclass(frozen=True)
class MidiIndividualSettings:
    play_sound: bool
    auto_fit_note_range: bool
    repeat_prevention: bool
    auto_sustain: bool
    humanize_timing: bool
    chord_strum: bool
    chord_optimization: bool
    use_piano_arrangement: bool
    playback_speed_percent: int
    transpose_semitones: int
    octave_shift: int
    fit_note_range: tuple[int, int] | None = None
    track_channels: tuple[tuple[int, int, bool], ...] = ()


class ApplicationDatabase:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._initialize()

    def load_settings(self) -> dict[str, object]:
        with _DATABASE_LOCK, self._connect() as connection:
            rows = connection.execute(
                "SELECT setting_key, value_json FROM app_settings"
            ).fetchall()
        settings: dict[str, object] = {}
        for key, value_json in rows:
            try:
                settings[str(key)] = json.loads(str(value_json))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return settings

    def save_settings(self, settings: dict[str, object]) -> None:
        rows = [
            (
                str(key),
                json.dumps(
                    value,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
            for key, value in settings.items()
        ]
        with _DATABASE_LOCK, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM app_settings")
            connection.executemany(
                "INSERT INTO app_settings(setting_key, value_json) VALUES (?, ?)",
                rows,
            )
            connection.commit()

    def load_playlists(
        self,
    ) -> list[tuple[str, str, list[tuple[str, str, str]]]]:
        with _DATABASE_LOCK, self._connect() as connection:
            playlist_rows = connection.execute(
                "SELECT playlist_id, name FROM playlists ORDER BY position"
            ).fetchall()
            track_rows = connection.execute(
                "SELECT playlist_id, path, name, duration "
                "FROM playlist_tracks ORDER BY playlist_id, position"
            ).fetchall()
        tracks_by_playlist: dict[str, list[tuple[str, str, str]]] = {}
        for playlist_id, path, name, duration in track_rows:
            tracks_by_playlist.setdefault(str(playlist_id), []).append(
                (str(path), str(name), str(duration))
            )
        return [
            (
                str(playlist_id),
                str(name),
                tracks_by_playlist.get(str(playlist_id), []),
            )
            for playlist_id, name in playlist_rows
        ]

    def save_playlists(
        self,
        playlists: Iterable[
            tuple[str, str, Iterable[tuple[str, str, str]]]
        ],
    ) -> None:
        normalized = [
            (
                str(playlist_id),
                str(name),
                [
                    (str(path), str(track_name), str(duration))
                    for path, track_name, duration in tracks
                ],
            )
            for playlist_id, name, tracks in playlists
        ]
        with _DATABASE_LOCK, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM playlists")
            connection.executemany(
                "INSERT INTO playlists(playlist_id, position, name) "
                "VALUES (?, ?, ?)",
                (
                    (playlist_id, position, name)
                    for position, (playlist_id, name, _tracks) in enumerate(
                        normalized
                    )
                ),
            )
            connection.executemany(
                "INSERT INTO playlist_tracks("
                "playlist_id, position, path, name, duration"
                ") VALUES (?, ?, ?, ?, ?)",
                (
                    (
                        playlist_id,
                        position,
                        path,
                        track_name,
                        duration,
                    )
                    for playlist_id, _name, tracks in normalized
                    for position, (path, track_name, duration) in enumerate(
                        tracks
                    )
                ),
            )
            connection.commit()

    def load_midi_individual_settings(
        self,
        paths: Iterable[Path],
    ) -> dict[Path, MidiIndividualSettings]:
        normalized_paths = tuple(dict.fromkeys(Path(path) for path in paths))
        if not normalized_paths:
            return {}
        key_to_path = {
            self._path_key(path): path
            for path in normalized_paths
        }
        result: dict[Path, MidiIndividualSettings] = {}
        track_channels_by_key: dict[str, list[tuple[int, int, bool]]] = {}
        with _DATABASE_LOCK, self._connect() as connection:
            for key_batch in self._batches(tuple(key_to_path)):
                placeholders = ",".join("?" for _key in key_batch)
                rows = connection.execute(
                    "SELECT path, play_sound, auto_fit_note_range, "
                    "repeat_prevention, auto_sustain, humanize_timing, "
                    "chord_strum, chord_optimization, use_piano_arrangement, "
                    "playback_speed_percent, transpose_semitones, octave_shift, "
                    "fit_note_min, fit_note_max "
                    "FROM midi_individual_settings "
                    f"WHERE path IN ({placeholders})",
                    key_batch,
                ).fetchall()
                for path_key, track_index, channel, enabled in connection.execute(
                    "SELECT path, track_index, channel, enabled "
                    "FROM midi_individual_track_channels "
                    f"WHERE path IN ({placeholders}) "
                    "ORDER BY path, track_index, channel",
                    key_batch,
                ):
                    track_channels_by_key.setdefault(str(path_key), []).append(
                        (int(track_index), int(channel), bool(enabled))
                    )
                for row in rows:
                    path = key_to_path.get(str(row[0]))
                    if path is None:
                        continue
                    result[path] = MidiIndividualSettings(
                        play_sound=bool(row[1]),
                        auto_fit_note_range=bool(row[2]),
                        repeat_prevention=bool(row[3]),
                        auto_sustain=bool(row[4]),
                        humanize_timing=bool(row[5]),
                        chord_strum=bool(row[6]),
                        chord_optimization=bool(row[7]),
                        use_piano_arrangement=bool(row[8]),
                        playback_speed_percent=int(row[9]),
                        transpose_semitones=int(row[10]),
                        octave_shift=int(row[11]),
                        fit_note_range=(
                            (int(row[12]), int(row[13]))
                            if row[12] is not None and row[13] is not None
                            else None
                        ),
                        track_channels=tuple(
                            track_channels_by_key.get(str(row[0]), ())
                        ),
                    )
        return result

    def save_midi_individual_settings(
        self,
        path: Path,
        settings: MidiIndividualSettings,
    ) -> None:
        with _DATABASE_LOCK, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO midi_individual_settings("
                "path, play_sound, auto_fit_note_range, repeat_prevention, "
                "auto_sustain, humanize_timing, chord_strum, "
                "chord_optimization, use_piano_arrangement, "
                "playback_speed_percent, transpose_semitones, octave_shift, "
                "fit_note_min, fit_note_max"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET "
                "play_sound=excluded.play_sound, "
                "auto_fit_note_range=excluded.auto_fit_note_range, "
                "repeat_prevention=excluded.repeat_prevention, "
                "auto_sustain=excluded.auto_sustain, "
                "humanize_timing=excluded.humanize_timing, "
                "chord_strum=excluded.chord_strum, "
                "chord_optimization=excluded.chord_optimization, "
                "use_piano_arrangement=excluded.use_piano_arrangement, "
                "playback_speed_percent=excluded.playback_speed_percent, "
                "transpose_semitones=excluded.transpose_semitones, "
                "octave_shift=excluded.octave_shift, "
                "fit_note_min=excluded.fit_note_min, "
                "fit_note_max=excluded.fit_note_max",
                (
                    self._path_key(path),
                    int(settings.play_sound),
                    int(settings.auto_fit_note_range),
                    int(settings.repeat_prevention),
                    int(settings.auto_sustain),
                    int(settings.humanize_timing),
                    int(settings.chord_strum),
                    int(settings.chord_optimization),
                    int(settings.use_piano_arrangement),
                    int(settings.playback_speed_percent),
                    int(settings.transpose_semitones),
                    int(settings.octave_shift),
                    (
                        int(settings.fit_note_range[0])
                        if settings.fit_note_range is not None
                        else None
                    ),
                    (
                        int(settings.fit_note_range[1])
                        if settings.fit_note_range is not None
                        else None
                    ),
                ),
            )
            connection.execute(
                "DELETE FROM midi_individual_track_channels WHERE path = ?",
                (self._path_key(path),),
            )
            connection.executemany(
                "INSERT INTO midi_individual_track_channels("
                "path, track_index, channel, enabled"
                ") VALUES (?, ?, ?, ?)",
                (
                    (
                        self._path_key(path),
                        int(track),
                        int(channel),
                        int(enabled),
                    )
                    for track, channel, enabled in settings.track_channels
                ),
            )
            connection.commit()

    def delete_midi_individual_settings(self, path: Path) -> bool:
        with _DATABASE_LOCK, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM midi_individual_settings WHERE path = ?",
                (self._path_key(path),),
            )
            connection.commit()
        return cursor.rowcount > 0

    def load_valid_midi_metadata(
        self,
        file_stats: dict[Path, tuple[int, int]],
    ) -> dict[Path, MidiMetadata]:
        if not file_stats:
            return {}
        key_to_path = {
            self._path_key(path): path
            for path in file_stats
        }
        metadata_rows: dict[str, tuple[object, ...]] = {}
        channel_rows: dict[str, list[int]] = {}
        track_rows: dict[str, list[tuple[int, str, str]]] = {}
        track_channel_rows: dict[tuple[str, int], list[int]] = {}
        keys = tuple(key_to_path)
        with _DATABASE_LOCK, self._connect() as connection:
            for key_batch in self._batches(keys):
                placeholders = ",".join("?" for _key in key_batch)
                for row in connection.execute(
                    "SELECT path, file_size, modified_ns, duration, "
                    "event_count, note_min, note_max, midi_format, file_hash "
                    f"FROM midi_metadata WHERE path IN ({placeholders})",
                    key_batch,
                ):
                    metadata_rows[str(row[0])] = tuple(row[1:])
                for path_key, channel in connection.execute(
                    "SELECT path, channel FROM midi_channels "
                    f"WHERE path IN ({placeholders}) ORDER BY path, channel",
                    key_batch,
                ):
                    channel_rows.setdefault(str(path_key), []).append(int(channel))
                for path_key, track_index, name, instrument_name in connection.execute(
                    "SELECT path, track_index, name, instrument_name "
                    "FROM midi_tracks "
                    f"WHERE path IN ({placeholders}) ORDER BY path, track_index",
                    key_batch,
                ):
                    track_rows.setdefault(str(path_key), []).append(
                        (
                            int(track_index),
                            str(name),
                            str(instrument_name),
                        )
                    )
                for path_key, track_index, channel in connection.execute(
                    "SELECT path, track_index, channel "
                    "FROM midi_track_channels "
                    f"WHERE path IN ({placeholders}) "
                    "ORDER BY path, track_index, channel",
                    key_batch,
                ):
                    track_channel_rows.setdefault(
                        (str(path_key), int(track_index)),
                        [],
                    ).append(int(channel))

        result: dict[Path, MidiMetadata] = {}
        for path_key, row in metadata_rows.items():
            path = key_to_path.get(path_key)
            if path is None:
                continue
            file_size, modified_ns = file_stats[path]
            if int(row[0]) != file_size or int(row[1]) != modified_ns:
                continue
            note_min = row[4]
            note_max = row[5]
            note_range = (
                (int(note_min), int(note_max))
                if note_min is not None and note_max is not None
                else None
            )
            tracks = tuple(
                MidiTrackSummary(
                    index=track_index,
                    channels=tuple(
                        track_channel_rows.get((path_key, track_index), ())
                    ),
                    name=name,
                    instrument_name=instrument_name,
                )
                for track_index, name, instrument_name in track_rows.get(
                    path_key,
                    (),
                )
            )
            result[path] = MidiMetadata(
                path=path,
                file_size=file_size,
                modified_ns=modified_ns,
                duration=float(row[2]),
                channels=tuple(channel_rows.get(path_key, ())),
                event_count=int(row[3]),
                tracks=tracks,
                note_range=note_range,
                midi_format=int(row[6]),
                file_hash=str(row[7]),
            )
        return result

    def save_midi_metadata(
        self,
        path: Path,
        file_stat: tuple[int, int],
        summary: MidiSummary,
    ) -> None:
        path_key = self._path_key(path)
        file_size, modified_ns = file_stat
        note_min = summary.note_range[0] if summary.note_range else None
        note_max = summary.note_range[1] if summary.note_range else None
        with _DATABASE_LOCK, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO midi_metadata("
                "path, file_size, modified_ns, duration, event_count, "
                "note_min, note_max, midi_format, file_hash"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET "
                "file_size=excluded.file_size, "
                "modified_ns=excluded.modified_ns, "
                "duration=excluded.duration, "
                "event_count=excluded.event_count, "
                "note_min=excluded.note_min, "
                "note_max=excluded.note_max, "
                "midi_format=excluded.midi_format, "
                "file_hash=excluded.file_hash",
                (
                    path_key,
                    int(file_size),
                    int(modified_ns),
                    float(summary.duration),
                    int(summary.event_count),
                    note_min,
                    note_max,
                    int(summary.midi_format),
                    str(summary.file_hash),
                ),
            )
            connection.execute(
                "DELETE FROM midi_channels WHERE path = ?",
                (path_key,),
            )
            connection.execute(
                "DELETE FROM midi_tracks WHERE path = ?",
                (path_key,),
            )
            connection.executemany(
                "INSERT INTO midi_channels(path, channel) VALUES (?, ?)",
                ((path_key, int(channel)) for channel in summary.channels),
            )
            connection.executemany(
                "INSERT INTO midi_tracks("
                "path, track_index, name, instrument_name"
                ") VALUES (?, ?, ?, ?)",
                (
                    (
                        path_key,
                        int(track.index),
                        str(track.name),
                        str(track.instrument_name),
                    )
                    for track in summary.tracks
                ),
            )
            connection.executemany(
                "INSERT INTO midi_track_channels("
                "path, track_index, channel"
                ") VALUES (?, ?, ?)",
                (
                    (path_key, int(track.index), int(channel))
                    for track in summary.tracks
                    for channel in track.channels
                ),
            )
            connection.commit()

    def prune_missing_midi_metadata(
        self,
        folder: Path,
        existing_paths: Iterable[Path],
    ) -> int:
        folder_key = self._path_key(folder)
        existing_keys = {
            self._path_key(path)
            for path in existing_paths
        }
        with _DATABASE_LOCK, self._connect() as connection:
            stored_keys = tuple(
                str(row[0])
                for row in connection.execute("SELECT path FROM midi_metadata")
            )
            stale_keys = tuple(
                path_key
                for path_key in stored_keys
                if self._is_within_directory(path_key, folder_key)
                and path_key not in existing_keys
            )
            if not stale_keys:
                return 0
            connection.execute("BEGIN IMMEDIATE")
            for key_batch in self._batches(stale_keys):
                placeholders = ",".join("?" for _key in key_batch)
                connection.execute(
                    f"DELETE FROM midi_metadata WHERE path IN ({placeholders})",
                    key_batch,
                )
            connection.commit()
        return len(stale_keys)

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _DATABASE_LOCK, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    setting_key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS midi_metadata (
                    path TEXT PRIMARY KEY,
                    file_size INTEGER NOT NULL,
                    modified_ns INTEGER NOT NULL,
                    duration REAL NOT NULL,
                    event_count INTEGER NOT NULL,
                    note_min INTEGER,
                    note_max INTEGER,
                    midi_format INTEGER NOT NULL,
                    file_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS midi_channels (
                    path TEXT NOT NULL REFERENCES midi_metadata(path)
                        ON DELETE CASCADE,
                    channel INTEGER NOT NULL,
                    PRIMARY KEY(path, channel)
                );
                CREATE TABLE IF NOT EXISTS midi_tracks (
                    path TEXT NOT NULL REFERENCES midi_metadata(path)
                        ON DELETE CASCADE,
                    track_index INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    instrument_name TEXT NOT NULL,
                    PRIMARY KEY(path, track_index)
                );
                CREATE TABLE IF NOT EXISTS midi_track_channels (
                    path TEXT NOT NULL,
                    track_index INTEGER NOT NULL,
                    channel INTEGER NOT NULL,
                    PRIMARY KEY(path, track_index, channel),
                    FOREIGN KEY(path, track_index)
                        REFERENCES midi_tracks(path, track_index)
                        ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS midi_individual_settings (
                    path TEXT PRIMARY KEY REFERENCES midi_metadata(path)
                        ON DELETE CASCADE,
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
                    octave_shift INTEGER NOT NULL,
                    fit_note_min INTEGER,
                    fit_note_max INTEGER
                );
                CREATE TABLE IF NOT EXISTS midi_individual_track_channels (
                    path TEXT NOT NULL REFERENCES midi_individual_settings(path)
                        ON DELETE CASCADE,
                    track_index INTEGER NOT NULL,
                    channel INTEGER NOT NULL,
                    enabled INTEGER NOT NULL,
                    PRIMARY KEY(path, track_index, channel)
                );
                CREATE TABLE IF NOT EXISTS playlists (
                    playlist_id TEXT PRIMARY KEY,
                    position INTEGER NOT NULL UNIQUE,
                    name TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS playlist_tracks (
                    playlist_id TEXT NOT NULL REFERENCES playlists(playlist_id)
                        ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    name TEXT NOT NULL,
                    duration TEXT NOT NULL,
                    PRIMARY KEY(playlist_id, position)
                );
                """
            )
            individual_columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(midi_individual_settings)"
                )
            }
            if "fit_note_min" not in individual_columns:
                connection.execute(
                    "ALTER TABLE midi_individual_settings "
                    "ADD COLUMN fit_note_min INTEGER"
                )
            if "fit_note_max" not in individual_columns:
                connection.execute(
                    "ALTER TABLE midi_individual_settings "
                    "ADD COLUMN fit_note_max INTEGER"
                )
            connection.execute(
                f"PRAGMA user_version = {DATABASE_SCHEMA_VERSION}"
            )
            connection.commit()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5.0)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _path_key(path: Path) -> str:
        return os.path.normcase(str(Path(path).resolve(strict=False)))

    @staticmethod
    def _is_within_directory(path_key: str, folder_key: str) -> bool:
        try:
            return os.path.commonpath((folder_key, path_key)) == folder_key
        except ValueError:
            return False

    @staticmethod
    def _batches(values: tuple[str, ...]) -> Iterable[tuple[str, ...]]:
        for start in range(0, len(values), SQLITE_PARAMETER_BATCH_SIZE):
            yield values[start : start + SQLITE_PARAMETER_BATCH_SIZE]
