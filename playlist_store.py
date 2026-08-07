from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app_database import ApplicationDatabase
from settings import database_path


MAX_PLAYLISTS = 500
MAX_TRACKS_PER_PLAYLIST = 5000


@dataclass(frozen=True)
class PlaylistTrack:
    path: Path
    name: str
    duration: str = "--:--"


@dataclass(frozen=True)
class Playlist:
    playlist_id: str
    name: str
    tracks: tuple[PlaylistTrack, ...] = ()

    @classmethod
    def create(cls, name: str) -> Playlist:
        return cls(playlist_id=uuid4().hex, name=name.strip())


def playlist_total_duration(tracks: Iterable[PlaylistTrack]) -> str:
    total_seconds = 0
    for track in tracks:
        duration_seconds = _duration_seconds(track.duration)
        if duration_seconds is None:
            return "--:--"
        total_seconds += duration_seconds
    return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"


def _duration_seconds(value: str) -> int | None:
    parts = value.strip().split(":")
    if len(parts) not in (2, 3) or any(not part.isdecimal() for part in parts):
        return None
    numbers = [int(part) for part in parts]
    if numbers[-1] >= 60:
        return None
    if len(numbers) == 2:
        minutes, seconds = numbers
        return minutes * 60 + seconds
    hours, minutes, seconds = numbers
    if minutes >= 60:
        return None
    return hours * 3600 + minutes * 60 + seconds


class PlaylistStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else database_path()
        self.database = ApplicationDatabase(self.path)

    def load(self) -> list[Playlist]:
        try:
            rows = self.database.load_playlists()
        except Exception:
            return []
        playlists: list[Playlist] = []
        used_ids: set[str] = set()
        for raw_id, raw_name, raw_tracks in rows[:MAX_PLAYLISTS]:
            name = raw_name.strip()
            if not name:
                continue
            playlist_id = (
                raw_id.strip()
                if raw_id.strip() and raw_id.strip() not in used_ids
                else uuid4().hex
            )
            tracks = tuple(
                PlaylistTrack(
                    path=Path(path).expanduser(),
                    name=(track_name.strip() or Path(path).name),
                    duration=(duration.strip() or "--:--"),
                )
                for path, track_name, duration in raw_tracks[
                    :MAX_TRACKS_PER_PLAYLIST
                ]
                if path.strip()
            )
            playlists.append(
                Playlist(
                    playlist_id=playlist_id,
                    name=name,
                    tracks=tracks,
                )
            )
            used_ids.add(playlist_id)
        return playlists

    def save(self, playlists: object) -> None:
        normalized = normalize_playlists(playlists)
        self.database.save_playlists(
            (
                (
                    playlist.playlist_id,
                    playlist.name,
                    (
                        (
                            str(track.path),
                            track.name,
                            track.duration,
                        )
                        for track in playlist.tracks
                    ),
                )
                for playlist in normalized
            )
        )


def normalize_playlists(value: object) -> list[Playlist]:
    if not isinstance(value, (list, tuple)):
        return []
    playlists: list[Playlist] = []
    used_ids: set[str] = set()
    for item in value[:MAX_PLAYLISTS]:
        if not isinstance(item, Playlist):
            continue
        name = item.name.strip()
        if not name:
            continue
        playlist_id = item.playlist_id.strip()
        if not playlist_id or playlist_id in used_ids:
            playlist_id = uuid4().hex
        tracks = tuple(
            PlaylistTrack(
                path=Path(track.path),
                name=(track.name.strip() or Path(track.path).name),
                duration=(track.duration.strip() or "--:--"),
            )
            for track in item.tracks[:MAX_TRACKS_PER_PLAYLIST]
            if isinstance(track, PlaylistTrack)
        )
        playlists.append(
            Playlist(
                playlist_id=playlist_id,
                name=name,
                tracks=tracks,
            )
        )
        used_ids.add(playlist_id)
    return playlists
