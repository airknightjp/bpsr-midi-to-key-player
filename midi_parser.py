from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MidiEvent:
    time: float
    kind: str
    channel: int | None = None
    note: int | None = None
    velocity: int | None = None
    value: int | None = None
    track: int | None = None


@dataclass(frozen=True)
class MidiTrackSummary:
    index: int
    channels: tuple[int, ...]


@dataclass(frozen=True)
class MidiSummary:
    path: Path
    duration: float
    channels: tuple[int, ...]
    event_count: int
    tracks: tuple[MidiTrackSummary, ...] = ()
    note_range: tuple[int, int] | None = None


def parse_midi(path: str | Path) -> tuple[list[MidiEvent], MidiSummary]:
    midi_path = Path(path)
    data = midi_path.read_bytes()
    ticks_per_beat, tracks = _read_smf(data)
    tick_events: list[tuple[int, MidiEvent]] = []
    tempo_changes: list[tuple[int, int]] = [(0, 500_000)]
    end_tick = 0

    for track_index, track in enumerate(tracks):
        parsed_events, parsed_tempos, track_end_tick = _parse_track(track, track_index)
        tick_events.extend(parsed_events)
        tempo_changes.extend(parsed_tempos)
        end_tick = max(end_tick, track_end_tick)

    tempo_map = _build_tempo_map(tempo_changes, ticks_per_beat)
    events = [
        MidiEvent(
            time=_tick_to_seconds(tick, tempo_map, ticks_per_beat),
            kind=event.kind,
            channel=event.channel,
            note=event.note,
            velocity=event.velocity,
            value=event.value,
            track=event.track,
        )
        for tick, event in tick_events
    ]
    events.sort(key=lambda event: (event.time, _event_priority(event.kind)))
    source_event_count = len(events)
    duration = max(
        events[-1].time if events else 0.0,
        _tick_to_seconds(end_tick, tempo_map, ticks_per_beat),
    )
    if duration > (events[-1].time if events else 0.0):
        events.append(MidiEvent(time=duration, kind="end"))
    channels = sorted({event.channel for event in events if event.channel is not None})
    played_notes = [
        event.note
        for event in events
        if event.kind == "note_on" and event.note is not None
    ]
    note_range = (
        (min(played_notes), max(played_notes))
        if played_notes
        else None
    )
    track_summaries = tuple(
        MidiTrackSummary(
            index=track_index,
            channels=tuple(
                sorted(
                    {
                        event.channel
                        for event in events
                        if event.track == track_index and event.channel is not None
                    }
                )
            ),
        )
        for track_index in range(len(tracks))
    )
    summary = MidiSummary(
        path=midi_path,
        duration=duration,
        channels=tuple(channels),
        event_count=source_event_count,
        tracks=track_summaries,
        note_range=note_range,
    )
    return events, summary


def _read_smf(data: bytes) -> tuple[int, list[bytes]]:
    offset = 0
    if len(data) < 14:
        raise ValueError("Invalid MIDI file: truncated header")
    if data[offset:offset + 4] != b"MThd":
        raise ValueError("Invalid MIDI file: missing MThd header")
    offset += 4

    header_length = int.from_bytes(data[offset:offset + 4], "big")
    offset += 4
    if header_length < 6:
        raise ValueError("Invalid MIDI file: bad header length")
    if offset + header_length > len(data):
        raise ValueError("Invalid MIDI file: truncated header")

    midi_format = int.from_bytes(data[offset:offset + 2], "big")
    track_count = int.from_bytes(data[offset + 2:offset + 4], "big")
    division = int.from_bytes(data[offset + 4:offset + 6], "big")
    offset += header_length

    if midi_format not in (0, 1):
        raise ValueError(f"Unsupported MIDI format: {midi_format}")
    if track_count == 0:
        raise ValueError("Invalid MIDI file: no tracks")
    if midi_format == 0 and track_count != 1:
        raise ValueError("Invalid MIDI file: format 0 must contain exactly one track")
    if division & 0x8000:
        raise ValueError("SMPTE time division is not supported")
    if division == 0:
        raise ValueError("Invalid MIDI file: zero time division")

    tracks: list[bytes] = []
    for _ in range(track_count):
        if offset + 8 > len(data):
            raise ValueError("Invalid MIDI file: truncated track header")
        if data[offset:offset + 4] != b"MTrk":
            raise ValueError("Invalid MIDI file: missing MTrk chunk")
        offset += 4
        length = int.from_bytes(data[offset:offset + 4], "big")
        offset += 4
        if offset + length > len(data):
            raise ValueError("Invalid MIDI file: truncated track")
        tracks.append(data[offset:offset + length])
        offset += length

    return division, tracks


def _parse_track(
    track: bytes,
    track_index: int,
) -> tuple[list[tuple[int, MidiEvent]], list[tuple[int, int]], int]:
    offset = 0
    tick = 0
    running_status: int | None = None
    events: list[tuple[int, MidiEvent]] = []
    tempos: list[tuple[int, int]] = []

    while offset < len(track):
        delta, offset = _read_var_len(track, offset)
        tick += delta
        if offset >= len(track):
            raise ValueError("Invalid MIDI file: missing event status")
        status = track[offset]
        offset += 1

        if status < 0x80:
            if running_status is None:
                raise ValueError("Invalid MIDI file: running status without status byte")
            offset -= 1
            status = running_status
        elif status < 0xF0:
            running_status = status

        if status == 0xFF:
            if offset >= len(track):
                raise ValueError("Invalid MIDI file: missing meta event type")
            meta_type = track[offset]
            offset += 1
            length, offset = _read_var_len(track, offset)
            payload = track[offset:offset + length]
            offset += length
            if len(payload) != length:
                raise ValueError("Invalid MIDI file: truncated meta event")
            if meta_type == 0x2F:
                if length != 0:
                    raise ValueError("Invalid MIDI file: invalid end-of-track event")
                break
            if meta_type == 0x51 and length == 3:
                tempo = int.from_bytes(payload, "big")
                if tempo <= 0:
                    raise ValueError("Invalid MIDI file: invalid tempo")
                tempos.append((tick, tempo))
            continue

        if status in (0xF0, 0xF7):
            length, offset = _read_var_len(track, offset)
            if offset + length > len(track):
                raise ValueError("Invalid MIDI file: truncated system exclusive event")
            offset += length
            continue
        if status >= 0xF0:
            raise ValueError(f"Unsupported MIDI system event: 0x{status:02X}")

        event_type = status & 0xF0
        channel = status & 0x0F
        data_len = 1 if event_type in (0xC0, 0xD0) else 2
        payload = track[offset:offset + data_len]
        offset += data_len

        if len(payload) != data_len:
            raise ValueError("Invalid MIDI file: truncated event")
        if any(byte >= 0x80 for byte in payload):
            raise ValueError("Invalid MIDI file: invalid event data byte")

        if event_type == 0x90:
            note, velocity = payload
            kind = "note_on" if velocity > 0 else "note_off"
            events.append(
                (
                    tick,
                    MidiEvent(
                        time=0.0,
                        kind=kind,
                        channel=channel,
                        note=note,
                        velocity=velocity,
                        track=track_index,
                    ),
                )
            )
        elif event_type == 0x80:
            note, velocity = payload
            events.append(
                (
                    tick,
                    MidiEvent(
                        time=0.0,
                        kind="note_off",
                        channel=channel,
                        note=note,
                        velocity=velocity,
                        track=track_index,
                    ),
                )
            )
        elif event_type == 0xB0:
            control, value = payload
            if control == 64:
                events.append(
                    (
                        tick,
                        MidiEvent(
                            time=0.0,
                            kind="sustain",
                            channel=channel,
                            value=value,
                            track=track_index,
                        ),
                    )
                )

    return events, tempos, tick


def _read_var_len(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for _ in range(4):
        if offset >= len(data):
            raise ValueError("Invalid MIDI file: truncated variable length value")
        byte = data[offset]
        offset += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, offset
    raise ValueError("Invalid MIDI file: variable length value is too long")


def _build_tempo_map(tempo_changes: list[tuple[int, int]], ticks_per_beat: int) -> list[tuple[int, float, int]]:
    unique_changes = sorted(dict(tempo_changes).items())
    tempo_map: list[tuple[int, float, int]] = []
    current_seconds = 0.0
    previous_tick = 0
    previous_tempo = unique_changes[0][1]

    for tick, tempo in unique_changes:
        current_seconds += (tick - previous_tick) * previous_tempo / ticks_per_beat / 1_000_000
        tempo_map.append((tick, current_seconds, tempo))
        previous_tick = tick
        previous_tempo = tempo

    return tempo_map


def _tick_to_seconds(tick: int, tempo_map: list[tuple[int, float, int]], ticks_per_beat: int) -> float:
    active_tick, active_seconds, active_tempo = tempo_map[0]
    for tempo_tick, seconds_at_tick, tempo in tempo_map:
        if tempo_tick > tick:
            break
        active_tick = tempo_tick
        active_seconds = seconds_at_tick
        active_tempo = tempo
    return active_seconds + (tick - active_tick) * active_tempo / ticks_per_beat / 1_000_000


def _event_priority(kind: str) -> int:
    return {"note_off": 0, "sustain": 1, "note_on": 2}.get(kind, 3)
