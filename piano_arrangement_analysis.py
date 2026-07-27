from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from typing import Callable

from midi_parser import MidiEvent, MidiSummary, MidiTimeSignature
from piano_arrangement_models import (
    ChordEvent,
    NormalizedNote,
    NoteAffinityProvider,
    NoteAnalysis,
    NoteImportanceProvider,
    OriginType,
    PianoArrangementConfig,
    RoleProbabilities,
    RoleProbabilityProvider,
    SectionAnalysis,
    TextureType,
    VoiceSegment,
)


ProgressCallback = Callable[[int], None]
CancelCallback = Callable[[], bool]


@dataclass(frozen=True)
class AnalysisBundle:
    notes: tuple[NormalizedNote, ...]
    sections: tuple[SectionAnalysis, ...]
    voices: tuple[VoiceSegment, ...]
    roles: tuple[tuple[int, RoleProbabilities], ...]
    chords: tuple[ChordEvent, ...]
    note_analysis: tuple[NoteAnalysis, ...]
    warnings: tuple[str, ...]


class ArrangementCancelled(RuntimeError):
    pass


class RuleBasedNoteAffinityProvider:
    version = "rule-affinity-1"

    def score(self, first: NormalizedNote, second: NormalizedNote) -> float:
        if second.onset_beat < first.onset_beat:
            return -1.0
        gap = second.onset_beat - first.offset_beat
        if gap > 2.0 or second.onset_beat - first.onset_beat > 4.0:
            return -1.0
        pitch_distance = abs(second.pitch - first.pitch)
        pitch_score = math.exp(-pitch_distance / 7.0)
        temporal_score = math.exp(-max(0.0, gap) / 0.75)
        overlap = max(0.0, first.offset_beat - second.onset_beat)
        overlap_penalty = min(1.0, overlap / 0.5)
        articulation_delta = abs(
            (first.offset_beat - first.onset_beat)
            - (second.offset_beat - second.onset_beat)
        )
        articulation_score = math.exp(-articulation_delta / 1.0)
        same_part = 1.0 if first.source_id == second.source_id else 0.0
        return (
            0.32 * same_part
            + 0.26 * pitch_score
            + 0.23 * temporal_score
            + 0.12 * articulation_score
            + 0.07 * (1.0 if first.pitch_class == second.pitch_class else 0.0)
            - 0.55 * overlap_penalty
        )


class RuleBasedRoleProbabilityProvider:
    version = "rule-role-1"

    def __init__(self, all_notes: tuple[NormalizedNote, ...]) -> None:
        pitches = [note.pitch for note in all_notes if note.channel != 9]
        self.low = _percentile(pitches, 0.10, 36.0)
        self.median = _percentile(pitches, 0.50, 60.0)
        self.high = _percentile(pitches, 0.90, 84.0)

    def probabilities(
        self,
        voice: VoiceSegment,
        notes: tuple[NormalizedNote, ...],
    ) -> RoleProbabilities:
        if not notes:
            return RoleProbabilities(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        mean_pitch = statistics.fmean(note.pitch for note in notes)
        mean_duration = statistics.fmean(
            max(0.01, note.offset_beat - note.onset_beat) for note in notes
        )
        mean_velocity = statistics.fmean(note.velocity for note in notes) / 127.0
        gaps = [
            max(0.0, current.onset_beat - previous.offset_beat)
            for previous, current in zip(notes, notes[1:])
        ]
        coverage = sum(
            note.offset_beat - note.onset_beat for note in notes
        ) / max(0.25, voice.end_beat - voice.start_beat)
        interval_steps = [
            abs(current.pitch - previous.pitch)
            for previous, current in zip(notes, notes[1:])
        ]
        continuity = (
            statistics.fmean(math.exp(-step / 5.0) for step in interval_steps)
            if interval_steps
            else 0.5
        )
        register = _clamp01(
            (mean_pitch - self.low) / max(1.0, self.high - self.low)
        )
        low_register = 1.0 - register
        density = len(notes) / max(1.0, voice.end_beat - voice.start_beat)
        regularity = _rhythmic_regularity(notes)
        monophony = _monophony(notes)
        melody = _clamp01(
            0.23 * register
            + 0.20 * monophony
            + 0.21 * continuity
            + 0.13 * min(1.0, mean_duration)
            + 0.12 * mean_velocity
            + 0.11 * min(1.0, coverage)
        )
        bass = _clamp01(
            0.48 * low_register
            + 0.19 * continuity
            + 0.17 * _downbeat_ratio(notes)
            + 0.16 * min(1.0, mean_duration)
        )
        countermelody = _clamp01(
            0.35 * continuity
            + 0.25 * monophony
            + 0.20 * (1.0 - abs(register - 0.58))
            + 0.20 * mean_velocity
            - 0.18 * melody
        )
        pad = _clamp01(0.60 * min(1.0, mean_duration / 2.0) + 0.40 * coverage)
        ostinato = _clamp01(0.62 * regularity + 0.38 * min(1.0, density / 4.0))
        rhythmic = _clamp01(
            0.48 * regularity
            + 0.32 * min(1.0, density / 4.0)
            + 0.20 * (1.0 - min(1.0, mean_duration))
        )
        inner = _clamp01(
            0.38 * (1.0 - abs(register - 0.5) * 2.0)
            + 0.32 * (1.0 - monophony)
            + 0.30 * coverage
        )
        values = [melody, bass, countermelody, inner, rhythmic, pad, ostinato]
        total = sum(values) or 1.0
        return RoleProbabilities(*(value / total for value in values))


class RuleBasedNoteImportanceProvider:
    version = "rule-importance-1"

    def __init__(
        self,
        *,
        duration_median: float,
        velocity_median: float,
        pitch_counts: Counter[int],
    ) -> None:
        self.duration_median = max(0.01, duration_median)
        self.velocity_median = max(1.0, velocity_median)
        self.pitch_counts = pitch_counts

    def score(
        self,
        note: NormalizedNote,
        roles: RoleProbabilities,
    ) -> NoteAnalysis:
        duration = _clamp01(
            math.log1p(note.duration)
            / max(0.01, math.log1p(self.duration_median * 3.0))
        )
        velocity = _clamp01(note.velocity / max(1.0, self.velocity_median * 1.4))
        beat = _metrical_strength(note.onset_beat)
        repetition = _clamp01(self.pitch_counts[note.pitch_class] / 16.0)
        ornament = _clamp01(
            (0.18 - min(0.18, note.duration)) / 0.18
            * (1.0 - beat)
        )
        anchor = (
            roles.melody >= 0.34
            or (roles.bass >= 0.34 and beat >= 0.72)
            or (duration >= 0.75 and roles.countermelody >= 0.22)
        )
        contributions = (
            ("melody", 0.32 * roles.melody),
            ("bass", 0.20 * roles.bass),
            ("countermelody", 0.11 * roles.countermelody),
            ("beat", 0.11 * beat),
            ("duration", 0.10 * duration),
            ("velocity", 0.07 * velocity),
            ("motif", 0.09 * repetition),
            ("ornament", -0.12 * ornament),
        )
        raw = sum(value for _name, value in contributions)
        importance = _clamp01(raw + (0.10 if anchor else 0.0))
        return NoteAnalysis(
            note_id=note.note_id,
            importance=importance,
            melody_probability=roles.melody,
            bass_probability=roles.bass,
            countermelody_probability=roles.countermelody,
            anchor=anchor,
            duplicate_probability=0.0,
            ornament_probability=ornament,
            feature_contributions=contributions,
        )


def analyze_midi_for_arrangement(
    events: list[MidiEvent],
    summary: MidiSummary,
    config: PianoArrangementConfig,
    *,
    progress_callback: ProgressCallback | None = None,
    cancel_callback: CancelCallback | None = None,
) -> AnalysisBundle:
    config = config.normalized()
    progress = _Progress(progress_callback, cancel_callback)
    progress.report(0)
    notes, normalization_warnings = normalize_midi_notes(events, summary)
    progress.report(15)
    sections, section_warnings = analyze_sections(notes, summary, config)
    progress.report(28)
    affinity = RuleBasedNoteAffinityProvider()
    voices = separate_voices(notes, affinity)
    progress.report(43)
    role_provider = RuleBasedRoleProbabilityProvider(notes)
    roles = tuple(
        (
            voice.voice_id,
            role_provider.probabilities(
                voice,
                tuple(note for note in notes if note.note_id in voice.note_ids),
            ),
        )
        for voice in voices
    )
    progress.report(55)
    chords = analyze_harmony(notes, summary)
    progress.report(72)
    note_analysis = score_note_importance(notes, voices, roles)
    note_analysis = _mark_duplicates(notes, note_analysis)
    progress.report(80)
    warnings = tuple(dict.fromkeys((*normalization_warnings, *section_warnings)))
    return AnalysisBundle(
        notes=notes,
        sections=sections,
        voices=voices,
        roles=roles,
        chords=chords,
        note_analysis=note_analysis,
        warnings=warnings,
    )


def normalize_midi_notes(
    events: list[MidiEvent],
    summary: MidiSummary,
) -> tuple[tuple[NormalizedNote, ...], tuple[str, ...]]:
    note_ons: dict[int, MidiEvent] = {}
    note_offs: dict[int, MidiEvent] = {}
    fallback_active: dict[tuple[int, int, int], list[MidiEvent]] = defaultdict(list)
    warnings: list[str] = []
    sustain_ranges = _sustain_ranges(events, summary.duration)

    for event in events:
        if (
            event.kind not in {"note_on", "note_off"}
            or event.note is None
            or event.channel is None
        ):
            continue
        owner = (event.track or 0, event.channel, event.note)
        if event.kind == "note_on":
            if event.note_id is not None:
                note_ons[event.note_id] = event
            fallback_active[owner].append(event)
        else:
            matched: MidiEvent | None = None
            if event.note_id is not None:
                note_offs[event.note_id] = event
                matched = note_ons.get(event.note_id)
            if matched is None and fallback_active[owner]:
                matched = fallback_active[owner].pop()
                if matched.note_id is not None:
                    note_offs[matched.note_id] = event
            elif matched is not None:
                active = fallback_active[owner]
                for index in range(len(active) - 1, -1, -1):
                    if active[index].note_id == matched.note_id:
                        active.pop(index)
                        break
            if not fallback_active[owner]:
                fallback_active.pop(owner, None)

    raw_notes: list[tuple[MidiEvent, MidiEvent | None]] = []
    for note_id, note_on in sorted(note_ons.items()):
        note_off = note_offs.get(note_id)
        if note_off is None:
            warnings.append("missing_note_off_repaired")
        raw_notes.append((note_on, note_off))

    grid_by_bar = _select_quantization_grids(raw_notes, summary)
    normalized: list[NormalizedNote] = []
    for note_on, note_off in raw_notes:
        onset_beat = float(note_on.beat or 0.0)
        offset_second = (
            max(note_on.time + 0.03, note_off.time)
            if note_off is not None
            else min(summary.duration, note_on.time + 0.25)
        )
        offset_beat = (
            max(onset_beat + 1 / 64, float(note_off.beat))
            if note_off is not None and note_off.beat is not None
            else onset_beat + max(1 / 64, (offset_second - note_on.time) * 2.0)
        )
        bar_index, _bar_start, _bar_length = _bar_for_beat(
            onset_beat, summary
        )
        grid = grid_by_bar.get(bar_index, 0.25)
        quantized_onset = round(onset_beat / grid) * grid
        quantized_duration = max(
            grid / 2.0,
            round((offset_beat - onset_beat) / grid) * grid,
        )
        source = (note_on.track or 0, note_on.channel)
        sounding_end = _sounding_note_end(
            offset_second,
            sustain_ranges.get(source, ()),
        )
        normalized.append(
            NormalizedNote(
                note_id=int(note_on.note_id or 0),
                track=source[0],
                channel=source[1],
                program=int(note_on.program),
                program_epoch=int(note_on.program_epoch),
                pitch=int(note_on.note or 0),
                pitch_class=int(note_on.note or 0) % 12,
                velocity=max(1, int(note_on.velocity or 1)),
                onset_tick=int(note_on.tick or 0),
                offset_tick=int(
                    note_off.tick
                    if note_off is not None and note_off.tick is not None
                    else round(offset_beat * summary.ticks_per_beat)
                ),
                onset_beat=onset_beat,
                offset_beat=offset_beat,
                onset_second=float(note_on.time),
                offset_second=offset_second,
                sounding_offset_second=max(offset_second, sounding_end),
                quantized_onset=quantized_onset,
                quantized_duration=quantized_duration,
                microtiming_residual=onset_beat - quantized_onset,
                source_note_ids=(int(note_on.note_id or 0),),
                origin_type=OriginType.SOURCE,
            )
        )
    normalized.sort(key=lambda note: (note.onset_beat, note.pitch, note.note_id))
    return tuple(normalized), tuple(dict.fromkeys(warnings))


def analyze_sections(
    notes: tuple[NormalizedNote, ...],
    summary: MidiSummary,
    config: PianoArrangementConfig,
) -> tuple[tuple[SectionAnalysis, ...], tuple[str, ...]]:
    warnings: list[str] = []
    if not notes:
        return (), ("no_notes",)
    invalid_meter = any(not signature.valid for signature in summary.time_signatures)
    if invalid_meter:
        warnings.append("invalid_meter")
    end_beat = max(note.offset_beat for note in notes)
    bar_boundaries = _bar_boundaries(summary, end_beat)
    bars = len(bar_boundaries) - 1
    features: list[SectionAnalysis] = []
    for index in range(bars):
        start = bar_boundaries[index]
        end = bar_boundaries[index + 1]
        bar_notes = tuple(
            note for note in notes if start <= note.onset_beat < end
        )
        features.append(_section_feature(index, start, end, bar_notes))

    boundaries = {0, bars}
    novelty: list[float] = [0.0]
    for previous, current in zip(features, features[1:]):
        novelty.append(_feature_distance(previous, current))
    if len(novelty) > 2:
        threshold = statistics.fmean(novelty) + statistics.pstdev(novelty) * 0.65
        boundaries.update(
            index
            for index, value in enumerate(novelty)
            if index > 0 and value >= threshold
        )
    for index in range(1, bars):
        previous_end = max(
            (
                note.offset_beat
                for note in notes
                if note.onset_beat < bar_boundaries[index]
            ),
            default=0.0,
        )
        next_start = min(
            (
                note.onset_beat
                for note in notes
                if note.onset_beat >= bar_boundaries[index]
            ),
            default=end_beat,
        )
        if (
            next_start - previous_end
            >= bar_boundaries[index + 1] - bar_boundaries[index]
        ):
            boundaries.add(index)

    ordered = sorted(boundaries)
    sections: list[SectionAnalysis] = []
    for section_index, (first_bar, last_bar) in enumerate(
        zip(ordered, ordered[1:])
    ):
        section_notes = tuple(
            note
            for note in notes
            if bar_boundaries[first_bar]
            <= note.onset_beat
            < bar_boundaries[last_bar]
        )
        section = _section_feature(
            section_index,
            bar_boundaries[first_bar],
            bar_boundaries[last_bar],
            section_notes,
        )
        repetition_of = _find_similar_section(section, sections)
        sections.append(replace(section, repetition_of=repetition_of))
    return tuple(sections), tuple(warnings)


def separate_voices(
    notes: tuple[NormalizedNote, ...],
    affinity: NoteAffinityProvider,
) -> tuple[VoiceSegment, ...]:
    voices: list[list[NormalizedNote]] = []
    for source_id in sorted({note.source_id for note in notes if note.channel != 9}):
        source_notes = sorted(
            (note for note in notes if note.source_id == source_id),
            key=lambda note: (note.onset_beat, note.pitch, note.note_id),
        )
        source_voices: list[list[NormalizedNote]] = []
        for note in source_notes:
            candidates: list[tuple[float, int]] = []
            for index, voice in enumerate(source_voices):
                value = affinity.score(voice[-1], note)
                if value >= 0.12:
                    candidates.append((value, index))
            if candidates:
                _value, target = max(candidates, key=lambda item: (item[0], -item[1]))
                source_voices[target].append(note)
            else:
                source_voices.append([note])
        voices.extend(source_voices)
    return tuple(
        VoiceSegment(
            voice_id=index,
            source_id=voice[0].source_id,
            note_ids=tuple(note.note_id for note in voice),
            start_beat=voice[0].onset_beat,
            end_beat=max(note.offset_beat for note in voice),
        )
        for index, voice in enumerate(voices)
        if voice
    )


def analyze_harmony(
    notes: tuple[NormalizedNote, ...],
    summary: MidiSummary,
) -> tuple[ChordEvent, ...]:
    pitched = tuple(note for note in notes if note.channel != 9)
    if not pitched:
        return ()
    end_beat = max(note.offset_beat for note in pitched)
    windows = [
        (start, min(end_beat, start + 1.0))
        for start in _float_range(0.0, end_beat, 1.0)
    ]
    templates = _chord_templates()
    emissions: list[list[float]] = []
    for start, end in windows:
        active = tuple(
            note
            for note in pitched
            if note.onset_beat < end and note.offset_beat > start
        )
        weights = Counter()
        bass_pitch: int | None = None
        for note in active:
            overlap = max(
                0.0,
                min(end, note.offset_beat) - max(start, note.onset_beat),
            )
            weight = overlap * (0.7 + note.velocity / 423.0)
            weights[note.pitch_class] += weight
            bass_pitch = note.pitch if bass_pitch is None else min(bass_pitch, note.pitch)
        emissions.append(
            [
                _chord_emission(weights, bass_pitch, root, quality, pcs)
                for root, quality, pcs in templates
            ]
        )
    if not emissions:
        return ()
    beam: list[tuple[float, tuple[int, ...]]] = [
        (score, (index,))
        for index, score in enumerate(emissions[0])
    ]
    beam = sorted(beam, reverse=True)[:24]
    for window_index in range(1, len(windows)):
        next_beam: list[tuple[float, tuple[int, ...]]] = []
        for score, path in beam:
            previous = templates[path[-1]]
            for candidate_index, emission in enumerate(emissions[window_index]):
                candidate = templates[candidate_index]
                transition = _chord_transition(previous, candidate)
                next_beam.append(
                    (score + emission + transition, (*path, candidate_index))
                )
        beam = sorted(next_beam, reverse=True)[:24]
    best_path = beam[0][1]
    result: list[ChordEvent] = []
    for window_index, template_index in enumerate(best_path):
        start, end = windows[window_index]
        root, quality, pcs = templates[template_index]
        scores = sorted(emissions[window_index], reverse=True)
        margin = scores[0] - scores[1] if len(scores) > 1 else scores[0]
        confidence = _clamp01(0.45 + margin / 4.0)
        if result and (
            result[-1].root,
            result[-1].quality,
        ) == (root, quality):
            previous = result.pop()
            result.append(replace(previous, end_beat=end))
        else:
            active_pitches = [
                note.pitch
                for note in pitched
                if note.onset_beat < end and note.offset_beat > start
            ]
            result.append(
                ChordEvent(
                    start_beat=start,
                    end_beat=end,
                    root=root,
                    quality=quality,
                    bass_pitch_class=(
                        min(active_pitches) % 12 if active_pitches else None
                    ),
                    pitch_classes=tuple(sorted(pcs)),
                    confidence=confidence,
                )
            )
    return tuple(result)


def score_note_importance(
    notes: tuple[NormalizedNote, ...],
    voices: tuple[VoiceSegment, ...],
    roles: tuple[tuple[int, RoleProbabilities], ...],
) -> tuple[NoteAnalysis, ...]:
    role_by_voice = dict(roles)
    voice_by_note = {
        note_id: voice.voice_id
        for voice in voices
        for note_id in voice.note_ids
    }
    durations = [note.duration for note in notes]
    velocities = [note.velocity for note in notes]
    pitch_counts = Counter(note.pitch_class for note in notes)
    provider: NoteImportanceProvider = RuleBasedNoteImportanceProvider(
        duration_median=statistics.median(durations) if durations else 0.25,
        velocity_median=statistics.median(velocities) if velocities else 64.0,
        pitch_counts=pitch_counts,
    )
    empty_roles = RoleProbabilities(0.0, 0.0, 0.0, 0.4, 0.3, 0.2, 0.1)
    return tuple(
        provider.score(
            note,
            role_by_voice.get(voice_by_note.get(note.note_id, -1), empty_roles),
        )
        for note in notes
    )


class _Progress:
    def __init__(
        self,
        callback: ProgressCallback | None,
        cancel: CancelCallback | None,
    ) -> None:
        self.callback = callback
        self.cancel = cancel
        self.last = -1

    def report(self, value: int) -> None:
        if self.cancel is not None and self.cancel():
            raise ArrangementCancelled("Piano arrangement was cancelled")
        value = max(0, min(100, int(value)))
        if value != self.last and self.callback is not None:
            self.callback(value)
        self.last = value


def _sustain_ranges(
    events: list[MidiEvent],
    duration: float,
) -> dict[tuple[int, int], tuple[tuple[float, float], ...]]:
    starts: dict[tuple[int, int], float] = {}
    ranges: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
    for event in events:
        if (
            event.kind != "sustain"
            or event.channel is None
            or event.value is None
        ):
            continue
        source = (event.track or 0, event.channel)
        enabled = event.value >= 64
        if enabled and source not in starts:
            starts[source] = event.time
        elif not enabled and source in starts:
            ranges[source].append((starts.pop(source), event.time))
    for source, start in starts.items():
        ranges[source].append((start, duration))
    return {source: tuple(values) for source, values in ranges.items()}


def _sounding_note_end(
    note_off: float,
    ranges: tuple[tuple[float, float], ...],
) -> float:
    for start, end in ranges:
        if start <= note_off < end:
            return end
    return note_off


def _select_quantization_grids(
    raw_notes: list[tuple[MidiEvent, MidiEvent | None]],
    summary: MidiSummary,
) -> dict[int, float]:
    by_bar: dict[int, list[float]] = defaultdict(list)
    for note_on, _note_off in raw_notes:
        beat = float(note_on.beat or 0.0)
        bar, _start, _length = _bar_for_beat(beat, summary)
        by_bar[bar].append(beat)
    candidates = (0.5, 1 / 3, 0.25, 1 / 6, 0.125, 1 / 12)
    selected: dict[int, float] = {}
    previous: float | None = None
    for bar in sorted(by_bar):
        best = min(
            candidates,
            key=lambda grid: (
                statistics.fmean(
                    abs(beat - round(beat / grid) * grid)
                    for beat in by_bar[bar]
                )
                + 0.0015 / grid
                + (0.015 if previous is not None and grid != previous else 0.0)
            ),
        )
        selected[bar] = best
        previous = best
    return selected


def _bar_for_beat(
    beat: float,
    summary: MidiSummary,
) -> tuple[int, float, float]:
    signatures = tuple(
        signature for signature in summary.time_signatures if signature.valid
    )
    if not signatures:
        length = 4.0
        index = max(0, int(beat // length))
        return index, index * length, length
    current = signatures[0]
    absolute_bar = 0
    current_start = current.beat
    for next_signature in signatures[1:]:
        length = current.numerator * 4.0 / current.denominator
        if beat < next_signature.beat:
            local = max(0, int((beat - current_start) // length))
            return absolute_bar + local, current_start + local * length, length
        absolute_bar += max(
            0, math.ceil((next_signature.beat - current_start) / length)
        )
        current = next_signature
        current_start = next_signature.beat
    length = current.numerator * 4.0 / current.denominator
    local = max(0, int((beat - current_start) // length))
    return absolute_bar + local, current_start + local * length, length


def _bar_boundaries(
    summary: MidiSummary,
    end_beat: float,
) -> tuple[float, ...]:
    valid = sorted(
        (
            signature
            for signature in summary.time_signatures
            if signature.valid
        ),
        key=lambda signature: signature.beat,
    )
    if not valid or valid[0].beat > 0.0:
        valid.insert(0, MidiTimeSignature(0, 0.0, 4, 4))
    boundaries = [0.0]
    beat = 0.0
    signature_index = 0
    while beat < end_beat - 1e-9:
        while (
            signature_index + 1 < len(valid)
            and valid[signature_index + 1].beat <= beat + 1e-9
        ):
            signature_index += 1
        signature = valid[signature_index]
        length = signature.numerator * 4.0 / signature.denominator
        next_change = (
            valid[signature_index + 1].beat
            if signature_index + 1 < len(valid)
            else math.inf
        )
        next_beat = min(beat + max(0.25, length), next_change, end_beat)
        if next_beat <= beat + 1e-9:
            signature_index += 1
            continue
        boundaries.append(next_beat)
        beat = next_beat
    if len(boundaries) == 1:
        boundaries.append(max(0.25, end_beat))
    return tuple(boundaries)


def _section_feature(
    index: int,
    start: float,
    end: float,
    notes: tuple[NormalizedNote, ...],
) -> SectionAnalysis:
    duration = max(0.25, end - start)
    chroma_counts = [0.0] * 12
    onset_counts = [0.0] * 16
    for note in notes:
        weight = max(0.05, min(note.offset_beat, end) - max(note.onset_beat, start))
        chroma_counts[note.pitch_class] += weight * (0.6 + note.velocity / 318.0)
        phase = ((note.quantized_onset - start) % 4.0) / 4.0
        onset_counts[min(15, int(phase * 16))] += 1.0
    chroma = _normalize_vector(chroma_counts)
    onset = _normalize_vector(onset_counts)
    pitches = [note.pitch for note in notes if note.channel != 9]
    density = len(notes) / duration
    polyphony = _mean_polyphony(notes, start, end)
    sustain_ratio = (
        statistics.fmean(
            max(0.0, note.sounding_offset_second - note.offset_second)
            / max(0.03, note.sounding_offset_second - note.onset_second)
            for note in notes
        )
        if notes
        else 0.0
    )
    texture = _classify_texture(notes, density, polyphony, sustain_ratio)
    intensity = _clamp01(
        0.45 * min(1.0, density / 8.0)
        + 0.30 * min(1.0, polyphony / 6.0)
        + 0.25 * (
            statistics.fmean(note.velocity for note in notes) / 127.0
            if notes
            else 0.0
        )
    )
    return SectionAnalysis(
        index=index,
        start_beat=start,
        end_beat=end,
        texture=texture,
        chroma=chroma,
        onset_histogram=onset,
        pitch_range=(min(pitches), max(pitches)) if pitches else None,
        note_density=density,
        polyphony=polyphony,
        sustain_ratio=sustain_ratio,
        intensity=intensity,
    )


def _classify_texture(
    notes: tuple[NormalizedNote, ...],
    density: float,
    polyphony: float,
    sustain_ratio: float,
) -> TextureType:
    if not notes:
        return TextureType.MIXED
    regularity = _rhythmic_regularity(notes)
    short_ratio = sum(note.duration < 0.18 for note in notes) / len(notes)
    onset_groups = _onset_groups(notes)
    chord_ratio = (
        sum(len(group) >= 3 for group in onset_groups) / len(onset_groups)
        if onset_groups
        else 0.0
    )
    low_notes = [note for note in notes if note.pitch < 48]
    if sustain_ratio > 0.55 and polyphony >= 2.0:
        return TextureType.PAD
    if chord_ratio > 0.58:
        return TextureType.BLOCK_CHORD
    if regularity > 0.72 and polyphony < 1.8 and density > 2.5:
        return TextureType.ARPEGGIO
    if regularity > 0.82 and density > 3.0:
        return TextureType.OSTINATO
    if short_ratio > 0.68 and chord_ratio > 0.3:
        return TextureType.RHYTHMIC_HITS
    if low_notes and len(low_notes) / len(notes) > 0.60 and polyphony < 1.6:
        return TextureType.BASS_RIFF
    if polyphony < 1.55:
        return TextureType.HOMOPHONIC
    if polyphony > 3.3 and chord_ratio < 0.45:
        return TextureType.POLYPHONIC
    return TextureType.MIXED


def _feature_distance(first: SectionAnalysis, second: SectionAnalysis) -> float:
    chroma = 1.0 - _cosine(first.chroma, second.chroma)
    rhythm = 1.0 - _cosine(first.onset_histogram, second.onset_histogram)
    density = abs(first.note_density - second.note_density) / max(
        1.0, first.note_density, second.note_density
    )
    polyphony = abs(first.polyphony - second.polyphony) / max(
        1.0, first.polyphony, second.polyphony
    )
    return 0.38 * chroma + 0.30 * rhythm + 0.18 * density + 0.14 * polyphony


def _find_similar_section(
    section: SectionAnalysis,
    previous: list[SectionAnalysis],
) -> int | None:
    matches = [
        (_feature_distance(section, candidate), candidate.index)
        for candidate in previous
        if abs(
            (section.end_beat - section.start_beat)
            - (candidate.end_beat - candidate.start_beat)
        )
        <= 4.0
    ]
    if not matches:
        return None
    distance, index = min(matches)
    return index if distance <= 0.24 else None


def _mark_duplicates(
    notes: tuple[NormalizedNote, ...],
    analyses: tuple[NoteAnalysis, ...],
) -> tuple[NoteAnalysis, ...]:
    groups: dict[tuple[int, int], list[int]] = defaultdict(list)
    for note in notes:
        groups[(round(note.onset_beat * 96), note.pitch)].append(note.note_id)
    duplicates = {
        note_id
        for ids in groups.values()
        if len(ids) > 1
        for note_id in ids
    }
    return tuple(
        replace(
            analysis,
            duplicate_probability=0.90,
            importance=_clamp01(analysis.importance + 0.04),
        )
        if analysis.note_id in duplicates
        else analysis
        for analysis in analyses
    )


def _chord_templates() -> tuple[tuple[int | None, str, frozenset[int]], ...]:
    qualities = {
        "major": (0, 4, 7),
        "minor": (0, 3, 7),
        "diminished": (0, 3, 6),
        "augmented": (0, 4, 8),
        "sus2": (0, 2, 7),
        "sus4": (0, 5, 7),
        "6": (0, 4, 7, 9),
        "minor6": (0, 3, 7, 9),
        "7": (0, 4, 7, 10),
        "major7": (0, 4, 7, 11),
        "minor7": (0, 3, 7, 10),
        "half-diminished": (0, 3, 6, 10),
        "diminished7": (0, 3, 6, 9),
        "add9": (0, 2, 4, 7),
    }
    result = [
        (
            root,
            quality,
            frozenset((root + interval) % 12 for interval in intervals),
        )
        for root in range(12)
        for quality, intervals in qualities.items()
    ]
    result.append((None, "unknown/no-chord", frozenset()))
    return tuple(result)


def _chord_emission(
    weights: Counter[int],
    bass_pitch: int | None,
    root: int | None,
    _quality: str,
    pcs: frozenset[int],
) -> float:
    total = sum(weights.values())
    if root is None:
        return -0.15 if total else 0.35
    if total <= 0:
        return -0.6
    coverage = sum(weights[pitch_class] for pitch_class in pcs) / total
    non_chord = 1.0 - coverage
    root_weight = weights[root] / total
    bass = 1.0 if bass_pitch is not None and bass_pitch % 12 == root else 0.0
    return 2.0 * coverage + 0.35 * root_weight + 0.35 * bass - 1.15 * non_chord


def _chord_transition(
    first: tuple[int | None, str, frozenset[int]],
    second: tuple[int | None, str, frozenset[int]],
) -> float:
    if first[:2] == second[:2]:
        return 0.35
    if first[0] is None or second[0] is None:
        return -0.18
    common = len(first[2].intersection(second[2]))
    root_motion = min((first[0] - second[0]) % 12, (second[0] - first[0]) % 12)
    return 0.08 * common - 0.035 * root_motion - 0.08


def _onset_groups(
    notes: tuple[NormalizedNote, ...],
    tolerance: float = 1 / 32,
) -> tuple[tuple[NormalizedNote, ...], ...]:
    groups: list[list[NormalizedNote]] = []
    for note in sorted(notes, key=lambda item: (item.onset_beat, item.pitch)):
        if groups and note.onset_beat - groups[-1][0].onset_beat <= tolerance:
            groups[-1].append(note)
        else:
            groups.append([note])
    return tuple(tuple(group) for group in groups)


def _mean_polyphony(
    notes: tuple[NormalizedNote, ...],
    start: float,
    end: float,
) -> float:
    if not notes:
        return 0.0
    points = sorted(
        [
            (max(start, note.onset_beat), 1)
            for note in notes
        ]
        + [
            (min(end, note.offset_beat), -1)
            for note in notes
        ],
        key=lambda item: (item[0], item[1]),
    )
    active = 0
    previous = start
    area = 0.0
    for beat, delta in points:
        area += active * max(0.0, beat - previous)
        active += delta
        previous = beat
    return area / max(0.25, end - start)


def _monophony(notes: tuple[NormalizedNote, ...]) -> float:
    if len(notes) < 2:
        return 1.0
    overlap = sum(
        max(0.0, previous.offset_beat - current.onset_beat)
        for previous, current in zip(notes, notes[1:])
    )
    span = max(0.25, notes[-1].offset_beat - notes[0].onset_beat)
    return _clamp01(1.0 - overlap / span)


def _rhythmic_regularity(notes: tuple[NormalizedNote, ...]) -> float:
    if len(notes) < 3:
        return 0.5
    intervals = [
        current.quantized_onset - previous.quantized_onset
        for previous, current in zip(notes, notes[1:])
        if current.quantized_onset > previous.quantized_onset
    ]
    if len(intervals) < 2:
        return 0.5
    mean = statistics.fmean(intervals)
    if mean <= 0:
        return 0.0
    return _clamp01(1.0 - statistics.pstdev(intervals) / mean)


def _downbeat_ratio(notes: tuple[NormalizedNote, ...]) -> float:
    if not notes:
        return 0.0
    return sum(
        1.0 if abs(note.quantized_onset - round(note.quantized_onset)) < 1e-6 else 0.0
        for note in notes
    ) / len(notes)


def _metrical_strength(beat: float) -> float:
    phase = beat % 4.0
    if min(phase, 4.0 - phase) < 1 / 32:
        return 1.0
    if abs(phase - 2.0) < 1 / 32:
        return 0.82
    if abs(phase - round(phase)) < 1 / 32:
        return 0.68
    if abs(phase * 2.0 - round(phase * 2.0)) < 1 / 32:
        return 0.44
    return 0.24


def _normalize_vector(values: list[float]) -> tuple[float, ...]:
    total = sum(values)
    return tuple(value / total for value in values) if total else tuple(values)


def _cosine(first: tuple[float, ...], second: tuple[float, ...]) -> float:
    numerator = sum(a * b for a, b in zip(first, second))
    denominator = math.sqrt(sum(a * a for a in first) * sum(b * b for b in second))
    return numerator / denominator if denominator else 0.0


def _float_range(start: float, end: float, step: float) -> tuple[float, ...]:
    count = max(0, math.ceil((end - start) / step))
    return tuple(start + index * step for index in range(count))


def _percentile(values: list[int], fraction: float, default: float) -> float:
    if not values:
        return default
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
    return float(ordered[index])


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
