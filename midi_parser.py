from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, replace
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
    tick: int | None = None
    beat: float | None = None
    program: int = 0
    program_epoch: int = 0
    note_id: int | None = None


@dataclass(frozen=True)
class MidiTempoChange:
    tick: int
    beat: float
    second: float
    microseconds_per_beat: int


@dataclass(frozen=True)
class MidiTimeSignature:
    tick: int
    beat: float
    numerator: int
    denominator: int
    valid: bool = True


@dataclass(frozen=True)
class MidiProgramChange:
    tick: int
    beat: float
    second: float
    track: int
    channel: int
    program: int
    program_epoch: int


@dataclass(frozen=True)
class MidiTrackSummary:
    index: int
    channels: tuple[int, ...]
    name: str = ""
    instrument_name: str = ""


@dataclass(frozen=True)
class MidiSummary:
    path: Path
    duration: float
    channels: tuple[int, ...]
    event_count: int
    tracks: tuple[MidiTrackSummary, ...] = ()
    note_range: tuple[int, int] | None = None
    midi_format: int = 1
    ticks_per_beat: int = 480
    tempo_changes: tuple[MidiTempoChange, ...] = ()
    time_signatures: tuple[MidiTimeSignature, ...] = ()
    program_changes: tuple[MidiProgramChange, ...] = ()
    file_hash: str = ""


@dataclass(frozen=True)
class _ParsedTrack:
    events: tuple[tuple[int, int, MidiEvent], ...]
    tempos: tuple[tuple[int, int], ...]
    time_signatures: tuple[tuple[int, int, int, bool], ...]
    program_changes: tuple[tuple[int, int, int, int], ...]
    end_tick: int
    name: str
    instrument_name: str


def parse_midi(path: str | Path) -> tuple[list[MidiEvent], MidiSummary]:
    midi_path = Path(path)
    data = midi_path.read_bytes()
    midi_format, ticks_per_beat, tracks = _read_smf(data)
    tick_events: list[tuple[int, int, MidiEvent]] = []
    tempo_changes: list[tuple[int, int]] = [(0, 500_000)]
    time_signatures: list[tuple[int, int, int, bool]] = []
    program_changes: list[tuple[int, int, int, int, int]] = []
    track_metadata: list[tuple[str, str]] = []
    end_tick = 0

    for track_index, track in enumerate(tracks):
        parsed = _parse_track(track, track_index)
        tick_events.extend(parsed.events)
        tempo_changes.extend(parsed.tempos)
        time_signatures.extend(parsed.time_signatures)
        program_changes.extend(
            (tick, track_index, channel, program, epoch)
            for tick, channel, program, epoch in parsed.program_changes
        )
        track_metadata.append((parsed.name, parsed.instrument_name))
        end_tick = max(end_tick, parsed.end_tick)

    tempo_map = _build_tempo_map(tempo_changes, ticks_per_beat)
    ordered_tick_events = sorted(
        tick_events,
        key=lambda item: (
            item[0],
            _event_priority(item[2].kind),
            item[2].track if item[2].track is not None else -1,
            item[1],
        ),
    )
    events = [
        replace(
            event,
            time=_tick_to_seconds(tick, tempo_map, ticks_per_beat),
            tick=tick,
            beat=tick / ticks_per_beat,
        )
        for tick, _sequence, event in ordered_tick_events
    ]
    events = _assign_stable_note_ids(events)
    source_event_count = len(events)
    duration = max(
        events[-1].time if events else 0.0,
        _tick_to_seconds(end_tick, tempo_map, ticks_per_beat),
    )
    if duration > (events[-1].time if events else 0.0):
        events.append(
            MidiEvent(
                time=duration,
                kind="end",
                tick=end_tick,
                beat=end_tick / ticks_per_beat,
            )
        )
    channels = sorted({event.channel for event in events if event.channel is not None})
    played_notes = [
        event.note
        for event in events
        if event.kind == "note_on" and event.note is not None
    ]
    note_range = (min(played_notes), max(played_notes)) if played_notes else None
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
            name=track_metadata[track_index][0],
            instrument_name=track_metadata[track_index][1],
        )
        for track_index in range(len(tracks))
    )
    normalized_tempos = tuple(
        MidiTempoChange(
            tick=tick,
            beat=tick / ticks_per_beat,
            second=_tick_to_seconds(tick, tempo_map, ticks_per_beat),
            microseconds_per_beat=tempo,
        )
        for tick, tempo in sorted(dict(tempo_changes).items())
    )
    normalized_signatures = tuple(
        MidiTimeSignature(
            tick=tick,
            beat=tick / ticks_per_beat,
            numerator=numerator,
            denominator=denominator,
            valid=valid,
        )
        for tick, numerator, denominator, valid in _unique_time_signatures(
            time_signatures
        )
    )
    normalized_programs = tuple(
        MidiProgramChange(
            tick=tick,
            beat=tick / ticks_per_beat,
            second=_tick_to_seconds(tick, tempo_map, ticks_per_beat),
            track=track,
            channel=channel,
            program=program,
            program_epoch=epoch,
        )
        for tick, track, channel, program, epoch in sorted(program_changes)
    )
    summary = MidiSummary(
        path=midi_path,
        duration=duration,
        channels=tuple(channels),
        event_count=source_event_count,
        tracks=track_summaries,
        note_range=note_range,
        midi_format=midi_format,
        ticks_per_beat=ticks_per_beat,
        tempo_changes=normalized_tempos,
        time_signatures=normalized_signatures,
        program_changes=normalized_programs,
        file_hash=hashlib.sha256(data).hexdigest(),
    )
    return events, summary


def _read_smf(data: bytes) -> tuple[int, int, list[bytes]]:
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

    return midi_format, division, tracks


def _parse_track(track: bytes, track_index: int) -> _ParsedTrack:
    offset = 0
    tick = 0
    sequence = 0
    running_status: int | None = None
    events: list[tuple[int, int, MidiEvent]] = []
    tempos: list[tuple[int, int]] = []
    signatures: list[tuple[int, int, int, bool]] = []
    program_changes: list[tuple[int, int, int, int]] = []
    channel_programs = [0] * 16
    channel_program_epochs = [0] * 16
    name = ""
    instrument_name = ""

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
            elif meta_type == 0x58:
                valid = length >= 2 and payload[0] > 0 and payload[1] <= 7
                numerator = payload[0] if length >= 1 else 4
                denominator = 1 << payload[1] if length >= 2 and payload[1] <= 7 else 4
                signatures.append((tick, numerator, denominator, valid))
            elif meta_type == 0x03 and not name:
                name = _decode_midi_text(payload)
            elif meta_type == 0x04 and not instrument_name:
                instrument_name = _decode_midi_text(payload)
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

        if event_type == 0xC0:
            channel_programs[channel] = payload[0]
            channel_program_epochs[channel] += 1
            epoch = channel_program_epochs[channel]
            program_changes.append((tick, channel, payload[0], epoch))
            events.append(
                (
                    tick,
                    sequence,
                    MidiEvent(
                        time=0.0,
                        kind="program_change",
                        channel=channel,
                        value=payload[0],
                        track=track_index,
                        program=payload[0],
                        program_epoch=epoch,
                    ),
                )
            )
            sequence += 1
            continue

        program = channel_programs[channel]
        epoch = channel_program_epochs[channel]
        if event_type == 0x90:
            note, velocity = payload
            kind = "note_on" if velocity > 0 else "note_off"
            events.append(
                (
                    tick,
                    sequence,
                    MidiEvent(
                        time=0.0,
                        kind=kind,
                        channel=channel,
                        note=note,
                        velocity=velocity,
                        track=track_index,
                        program=program,
                        program_epoch=epoch,
                    ),
                )
            )
            sequence += 1
        elif event_type == 0x80:
            note, velocity = payload
            events.append(
                (
                    tick,
                    sequence,
                    MidiEvent(
                        time=0.0,
                        kind="note_off",
                        channel=channel,
                        note=note,
                        velocity=velocity,
                        track=track_index,
                        program=program,
                        program_epoch=epoch,
                    ),
                )
            )
            sequence += 1
        elif event_type == 0xB0:
            control, value = payload
            if control == 64:
                events.append(
                    (
                        tick,
                        sequence,
                        MidiEvent(
                            time=0.0,
                            kind="sustain",
                            channel=channel,
                            value=value,
                            track=track_index,
                            program=program,
                            program_epoch=epoch,
                        ),
                    )
                )
                sequence += 1

    return _ParsedTrack(
        events=tuple(events),
        tempos=tuple(tempos),
        time_signatures=tuple(signatures),
        program_changes=tuple(program_changes),
        end_tick=tick,
        name=name,
        instrument_name=instrument_name,
    )


def _assign_stable_note_ids(events: list[MidiEvent]) -> list[MidiEvent]:
    active: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    next_note_id = 0
    result: list[MidiEvent] = []
    for event in events:
        if event.channel is None or event.note is None:
            result.append(event)
            continue
        owner = (
            event.track if event.track is not None else -1,
            event.channel,
            event.note,
        )
        if event.kind == "note_on":
            note_id = next_note_id
            next_note_id += 1
            active[owner].append(note_id)
            result.append(replace(event, note_id=note_id))
        elif event.kind == "note_off":
            note_id = active[owner].pop() if active.get(owner) else None
            if not active.get(owner):
                active.pop(owner, None)
            result.append(replace(event, note_id=note_id))
        else:
            result.append(event)
    return result


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


def _build_tempo_map(
    tempo_changes: list[tuple[int, int]],
    ticks_per_beat: int,
) -> list[tuple[int, float, int]]:
    unique_changes = sorted(dict(tempo_changes).items())
    tempo_map: list[tuple[int, float, int]] = []
    current_seconds = 0.0
    previous_tick = 0
    previous_tempo = unique_changes[0][1]

    for tick, tempo in unique_changes:
        current_seconds += (
            (tick - previous_tick)
            * previous_tempo
            / ticks_per_beat
            / 1_000_000
        )
        tempo_map.append((tick, current_seconds, tempo))
        previous_tick = tick
        previous_tempo = tempo

    return tempo_map


def _tick_to_seconds(
    tick: int,
    tempo_map: list[tuple[int, float, int]],
    ticks_per_beat: int,
) -> float:
    active_tick, active_seconds, active_tempo = tempo_map[0]
    for tempo_tick, seconds_at_tick, tempo in tempo_map:
        if tempo_tick > tick:
            break
        active_tick = tempo_tick
        active_seconds = seconds_at_tick
        active_tempo = tempo
    return (
        active_seconds
        + (tick - active_tick) * active_tempo / ticks_per_beat / 1_000_000
    )


def _unique_time_signatures(
    signatures: list[tuple[int, int, int, bool]],
) -> tuple[tuple[int, int, int, bool], ...]:
    by_tick: dict[int, tuple[int, int, bool]] = {}
    for tick, numerator, denominator, valid in signatures:
        by_tick[tick] = (numerator, denominator, valid)
    return tuple(
        (tick, *value)
        for tick, value in sorted(by_tick.items())
    )


def _decode_midi_text(payload: bytes) -> str:
    for encoding in ("utf-8", "cp932", "latin-1"):
        try:
            return payload.decode(encoding).strip("\x00 ")
        except UnicodeDecodeError:
            continue
    return ""


def _event_priority(kind: str) -> int:
    return {
        "note_off": 0,
        "sustain": 1,
        "program_change": 2,
        "note_on": 3,
    }.get(kind, 4)
