from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
import os
from pathlib import Path
from uuid import uuid4

from settings import application_directory


PLAYLISTS_FILE_NAME = "playlists.json"
PLAYLISTS_FORMAT_VERSION = 1
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
        self.path = path or (application_directory() / PLAYLISTS_FILE_NAME)

    def load(self) -> list[Playlist]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return []
        if not isinstance(payload, dict):
            return []
        raw_playlists = payload.get("playlists")
        if not isinstance(raw_playlists, list):
            return []

        playlists: list[Playlist] = []
        used_ids: set[str] = set()
        for raw_playlist in raw_playlists[:MAX_PLAYLISTS]:
            playlist = self._parse_playlist(raw_playlist, used_ids)
            if playlist is not None:
                playlists.append(playlist)
                used_ids.add(playlist.playlist_id)
        return playlists

    def save(self, playlists: object) -> None:
        normalized = normalize_playlists(playlists)
        payload = json.dumps(
            {
                "version": PLAYLISTS_FORMAT_VERSION,
                "playlists": [
                    {
                        "id": playlist.playlist_id,
                        "name": playlist.name,
                        "tracks": [
                            {
                                "path": str(track.path),
                                "name": track.name,
                                "duration": track.duration,
                            }
                            for track in playlist.tracks
                        ],
                    }
                    for playlist in normalized
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f"{self.path.name}.tmp")
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
        except Exception:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    @staticmethod
    def _parse_playlist(
        value: object,
        used_ids: set[str],
    ) -> Playlist | None:
        if not isinstance(value, dict):
            return None
        name = value.get("name")
        if not isinstance(name, str) or not name.strip():
            return None
        raw_id = value.get("id")
        playlist_id = (
            raw_id.strip()
            if isinstance(raw_id, str) and raw_id.strip() not in used_ids
            else uuid4().hex
        )
        raw_tracks = value.get("tracks")
        tracks: list[PlaylistTrack] = []
        if isinstance(raw_tracks, list):
            for raw_track in raw_tracks[:MAX_TRACKS_PER_PLAYLIST]:
                track = PlaylistStore._parse_track(raw_track)
                if track is not None:
                    tracks.append(track)
        return Playlist(
            playlist_id=playlist_id,
            name=name.strip(),
            tracks=tuple(tracks),
        )

    @staticmethod
    def _parse_track(value: object) -> PlaylistTrack | None:
        if not isinstance(value, dict):
            return None
        raw_path = value.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return None
        path = Path(raw_path).expanduser()
        raw_name = value.get("name")
        name = (
            raw_name.strip()
            if isinstance(raw_name, str) and raw_name.strip()
            else path.name
        )
        raw_duration = value.get("duration")
        duration = (
            raw_duration.strip()
            if isinstance(raw_duration, str) and raw_duration.strip()
            else "--:--"
        )
        return PlaylistTrack(path=path, name=name, duration=duration)


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
