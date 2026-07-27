from __future__ import annotations

import math
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from itertools import combinations
from typing import Protocol

from midi_parser import MidiEvent, MidiSummary
from piano_arrangement_analysis import (
    AnalysisBundle,
    ArrangementCancelled,
    CancelCallback,
    ProgressCallback,
)
from piano_arrangement_models import (
    ARRANGEMENT_ALGORITHM_VERSION,
    ArrangementNote,
    ArrangementPlan,
    ArrangementReport,
    ChordEvent,
    Hand,
    KeyboardGeometry,
    NoteAnalysis,
    NormalizedNote,
    OriginType,
    PedalEvent,
    PedalPolicy,
    PianoArrangementConfig,
    PianoNaturalnessScorer,
    RoleProbabilities,
    SectionAnalysis,
    TextureType,
)


@dataclass(frozen=True)
class DraftNote:
    source: NormalizedNote
    pitch: int
    hand: Hand
    role: str
    origin_type: OriginType
    source_note_ids: tuple[int, ...]
    activation_difficulty: float
    importance: float
    start_offset_beat: float = 0.0
    duration_scale: float = 1.0


@dataclass(frozen=True)
class ArrangementDraft:
    generator: str
    texture: TextureType
    notes: tuple[DraftNote, ...]
    fidelity: float
    harmonic_similarity: float
    rhythmic_similarity: float
    generated_count: int


class CandidateGenerator(Protocol):
    name: str

    def generate(
        self,
        notes: tuple[NormalizedNote, ...],
        context: GeneratorContext,
    ) -> tuple[ArrangementDraft, ...]: ...


@dataclass(frozen=True)
class GeneratorContext:
    analyses: dict[int, NoteAnalysis]
    roles: dict[int, RoleProbabilities]
    chords: tuple[ChordEvent, ...]
    section: SectionAnalysis
    config: PianoArrangementConfig


class SourceReductionGenerator:
    name = "source_reduction"

    def generate(
        self,
        notes: tuple[NormalizedNote, ...],
        context: GeneratorContext,
    ) -> tuple[ArrangementDraft, ...]:
        candidates: list[DraftNote] = []
        for note in notes:
            analysis = context.analyses[note.note_id]
            if note.channel == 9 or (note.track, note.channel) in context.config.excluded_parts:
                continue
            activation = _activation_difficulty(note.note_id, analysis)
            protected = (
                analysis.anchor
                or (note.track, note.channel) in context.config.protected_parts
            )
            if not protected and activation > context.config.difficulty:
                continue
            role = _role_for_note(note, context)
            hand = Hand.RIGHT if role in {"melody", "countermelody"} else (
                Hand.LEFT if role == "bass" else Hand.RIGHT if note.pitch >= 60 else Hand.LEFT
            )
            pitch, shifted = _fit_pitch_for_hand(
                note.pitch,
                hand,
                context.config,
            )
            candidates.append(
                DraftNote(
                    source=note,
                    pitch=pitch,
                    hand=hand,
                    role=role,
                    origin_type=(
                        OriginType.OCTAVE_SHIFTED if shifted else OriginType.SOURCE
                    ),
                    source_note_ids=note.source_note_ids,
                    activation_difficulty=activation,
                    importance=analysis.importance,
                )
            )
        reduced = _merge_and_limit(candidates, context.config)
        if not reduced:
            essential = sorted(
                (
                    note
                    for note in notes
                    if note.channel != 9
                    and (note.track, note.channel)
                    not in context.config.excluded_parts
                ),
                key=lambda note: (
                    context.analyses[note.note_id].anchor,
                    context.analyses[note.note_id].importance,
                ),
                reverse=True,
            )[:2]
            fallback_notes: list[DraftNote] = []
            split = _dynamic_split_pitch(essential)
            for note in essential:
                analysis = context.analyses[note.note_id]
                role = _role_for_note(note, context)
                hand = Hand.RIGHT if note.pitch >= split else Hand.LEFT
                pitch, shifted = _fit_pitch_for_hand(
                    note.pitch,
                    hand,
                    context.config,
                )
                fallback_notes.append(
                    DraftNote(
                        source=note,
                        pitch=pitch,
                        hand=hand,
                        role=role,
                        origin_type=(
                            OriginType.OCTAVE_SHIFTED
                            if shifted
                            else OriginType.SOURCE
                        ),
                        source_note_ids=note.source_note_ids,
                        activation_difficulty=_activation_difficulty(
                            note.note_id,
                            analysis,
                        ),
                        importance=analysis.importance,
                    )
                )
            reduced = _merge_and_limit(fallback_notes, context.config)
        if not reduced:
            return ()
        base = ArrangementDraft(
            generator=self.name,
            texture=context.section.texture,
            notes=reduced,
            fidelity=_source_fidelity(reduced, notes, context.analyses),
            harmonic_similarity=_harmony_similarity(reduced, context.chords),
            rhythmic_similarity=1.0,
            generated_count=0,
        )
        variants = [base]
        if len(reduced) >= 4:
            sparse = tuple(
                note
                for note in reduced
                if note.role in {"melody", "bass", "countermelody"}
                or note.importance >= 0.58
            )
            if sparse and sparse != reduced:
                variants.append(
                    replace(
                        base,
                        notes=sparse,
                        fidelity=_source_fidelity(
                            sparse, notes, context.analyses
                        ),
                    )
                )
        return tuple(variants)


class LeadSheetGenerator:
    name = "lead_sheet"

    def generate(
        self,
        notes: tuple[NormalizedNote, ...],
        context: GeneratorContext,
    ) -> tuple[ArrangementDraft, ...]:
        if not notes:
            return ()
        anchors: list[DraftNote] = []
        for note in notes:
            if note.channel == 9:
                continue
            analysis = context.analyses[note.note_id]
            role = _role_for_note(note, context)
            if role not in {"melody", "bass"} and not analysis.anchor:
                continue
            hand = Hand.RIGHT if role != "bass" else Hand.LEFT
            pitch, shifted = _fit_pitch_for_hand(note.pitch, hand, context.config)
            anchors.append(
                DraftNote(
                    source=note,
                    pitch=pitch,
                    hand=hand,
                    role=role,
                    origin_type=(
                        OriginType.OCTAVE_SHIFTED if shifted else OriginType.SOURCE
                    ),
                    source_note_ids=note.source_note_ids,
                    activation_difficulty=_activation_difficulty(
                        note.note_id, analysis
                    ),
                    importance=analysis.importance,
                )
            )
        chord = _chord_at(context.chords, notes[0].onset_beat)
        if (
            chord is not None
            and chord.confidence >= context.config.chord_confidence_threshold
            and context.config.allow_generated_notes
        ):
            anchors.extend(_generated_chord_shell(notes, anchors, chord, context))
        reduced = _merge_and_limit(anchors, context.config)
        if not reduced:
            return ()
        return (
            ArrangementDraft(
                generator=self.name,
                texture=TextureType.HOMOPHONIC,
                notes=reduced,
                fidelity=_source_fidelity(reduced, notes, context.analyses),
                harmonic_similarity=_harmony_similarity(reduced, context.chords),
                rhythmic_similarity=0.92,
                generated_count=sum(
                    note.origin_type == OriginType.GENERATED_CHORD_TONE
                    for note in reduced
                ),
            ),
        )


class TexturePatternGenerator:
    name = "texture_pattern"

    def generate(
        self,
        notes: tuple[NormalizedNote, ...],
        context: GeneratorContext,
    ) -> tuple[ArrangementDraft, ...]:
        if not context.config.allow_generated_notes or not notes:
            return ()
        chord = _chord_at(context.chords, notes[0].onset_beat)
        if (
            chord is None
            or chord.root is None
            or chord.confidence < context.config.chord_confidence_threshold
        ):
            return ()
        lead = LeadSheetGenerator().generate(notes, context)
        if not lead:
            return ()
        base = list(lead[0].notes)
        source = max(
            (note for note in notes if note.channel != 9),
            key=lambda note: context.analyses[note.note_id].importance,
            default=None,
        )
        if source is None:
            return ()
        generated: list[DraftNote] = []
        root_pitch = _nearest_pitch_class(43, chord.root, 33, 55)
        pattern = _texture_pattern_pitches(
            context.section.texture,
            root_pitch,
            chord.pitch_classes,
        )
        for pattern_index, pitch in enumerate(pattern):
            if context.section.texture == TextureType.BLOCK_CHORD:
                offset = 0.0
            elif context.section.texture == TextureType.OSTINATO:
                offset = pattern_index * 0.5
            else:
                offset = pattern_index * 0.25
            generated.append(
                DraftNote(
                    source=source,
                    pitch=pitch,
                    hand=Hand.LEFT,
                    role="accompaniment",
                    origin_type=OriginType.GENERATED_PATTERN,
                    source_note_ids=(),
                    activation_difficulty=0.62,
                    importance=0.34,
                    start_offset_beat=offset,
                    duration_scale=0.22,
                )
            )
        combined = _merge_and_limit((*base, *generated), context.config)
        return (
            ArrangementDraft(
                generator=self.name,
                texture=(
                    context.section.texture
                    if context.section.texture
                    in {TextureType.ARPEGGIO, TextureType.OSTINATO}
                    else TextureType.ARPEGGIO
                ),
                notes=combined,
                fidelity=_source_fidelity(combined, notes, context.analyses),
                harmonic_similarity=_harmony_similarity(
                    combined, context.chords
                ),
                rhythmic_similarity=0.96,
                generated_count=len(generated),
            ),
        )


class PolyphonicReductionGenerator:
    name = "polyphonic_reduction"

    def generate(
        self,
        notes: tuple[NormalizedNote, ...],
        context: GeneratorContext,
    ) -> tuple[ArrangementDraft, ...]:
        if context.section.texture not in {
            TextureType.POLYPHONIC,
            TextureType.MIXED,
        }:
            return ()
        ranked = sorted(
            (
                note
                for note in notes
                if note.channel != 9
                and (note.track, note.channel)
                not in context.config.excluded_parts
            ),
            key=lambda note: (
                context.analyses[note.note_id].anchor,
                context.analyses[note.note_id].importance,
                context.roles.get(
                    note.note_id,
                    RoleProbabilities(0, 0, 0, 0, 0, 0, 0),
                ).countermelody,
            ),
            reverse=True,
        )
        selected = ranked[:8]
        draft_notes: list[DraftNote] = []
        split = _dynamic_split_pitch(selected)
        for note in selected:
            analysis = context.analyses[note.note_id]
            role = _role_for_note(note, context)
            hand = Hand.RIGHT if note.pitch >= split else Hand.LEFT
            pitch, shifted = _fit_pitch_for_hand(note.pitch, hand, context.config)
            draft_notes.append(
                DraftNote(
                    source=note,
                    pitch=pitch,
                    hand=hand,
                    role=role,
                    origin_type=(
                        OriginType.OCTAVE_SHIFTED if shifted else OriginType.SOURCE
                    ),
                    source_note_ids=note.source_note_ids,
                    activation_difficulty=_activation_difficulty(
                        note.note_id, analysis
                    ),
                    importance=analysis.importance,
                )
            )
        reduced = _merge_and_limit(draft_notes, context.config)
        if not reduced:
            return ()
        return (
            ArrangementDraft(
                generator=self.name,
                texture=TextureType.POLYPHONIC,
                notes=reduced,
                fidelity=_source_fidelity(reduced, notes, context.analyses),
                harmonic_similarity=_harmony_similarity(reduced, context.chords),
                rhythmic_similarity=1.0,
                generated_count=0,
            ),
        )


class ExternalModelProposalGenerator:
    name = "external_model"
    version = "disabled-1"

    def generate(
        self,
        notes: tuple[NormalizedNote, ...],
        context: GeneratorContext,
    ) -> tuple[ArrangementDraft, ...]:
        # External providers are explicit opt-in extension points. No model is
        # bundled or downloaded by the application.
        return ()


class RuleBasedPianoNaturalnessScorer:
    version = "rule-naturalness-1"

    def score(self, notes: tuple[ArrangementNote, ...]) -> float:
        if not notes:
            return 0.0
        spans: list[int] = []
        grouped: dict[tuple[int, Hand], list[int]] = defaultdict(list)
        for note in notes:
            grouped[(round(note.start_beat * 96), note.hand)].append(note.pitch)
        for pitches in grouped.values():
            spans.append(max(pitches) - min(pitches))
        muddy = sum(
            1
            for pitches in grouped.values()
            if max(pitches) < 52 and len(pitches) >= 3 and max(pitches) - min(pitches) < 7
        )
        return _clamp01(
            1.0
            - statistics.fmean(max(0, span - 12) / 12 for span in spans)
            - muddy / max(1, len(grouped)) * 0.5
        )


@dataclass(frozen=True)
class _BeamState:
    score: float
    right_center: float
    left_center: float
    last_melody_pitch: int | None
    last_bass_pitch: int | None
    texture: TextureType | None
    drafts: tuple[ArrangementDraft, ...]


@dataclass(frozen=True)
class _FingeringState:
    cost: float
    previous: _FingeringState | None
    assignments: tuple[tuple[int, int], ...]
    notes: tuple[ArrangementNote, ...]
    fingers: tuple[int, ...]
    time: float


def optimize_piano_arrangement(
    events: list[MidiEvent],
    summary: MidiSummary,
    analysis: AnalysisBundle,
    config: PianoArrangementConfig,
    *,
    started_at: float,
    stage_timings: dict[str, float],
    progress_callback: ProgressCallback | None = None,
    cancel_callback: CancelCallback | None = None,
) -> ArrangementPlan:
    config = config.normalized()
    analyses = {item.note_id: item for item in analysis.note_analysis}
    role_by_voice = dict(analysis.roles)
    roles = {
        note_id: role_by_voice[voice.voice_id]
        for voice in analysis.voices
        for note_id in voice.note_ids
    }
    generators: tuple[CandidateGenerator, ...] = (
        SourceReductionGenerator(),
        LeadSheetGenerator(),
        TexturePatternGenerator(),
        PolyphonicReductionGenerator(),
        ExternalModelProposalGenerator(),
    )
    groups = _group_notes_by_onset(analysis.notes)
    window_beats = max(4.0, config.window_bars * 4.0)
    result_drafts: list[ArrangementDraft] = []
    boundary = _BeamState(0.0, 72.0, 48.0, None, None, None, ())
    window_start = groups[0][0].onset_beat if groups else 0.0
    window: list[tuple[NormalizedNote, ...]] = []
    processed = 0
    optimization_started = time.perf_counter()

    for group in groups:
        if group[0].onset_beat >= window_start + window_beats and window:
            boundary, chosen = _optimize_window(
                tuple(window),
                boundary,
                analysis,
                analyses,
                roles,
                generators,
                config,
                cancel_callback,
            )
            result_drafts.extend(chosen)
            processed += len(window)
            _report_progress(progress_callback, 80, 95, processed, len(groups))
            window_start = group[0].onset_beat
            window = []
        window.append(group)
    if window:
        boundary, chosen = _optimize_window(
            tuple(window),
            boundary,
            analysis,
            analyses,
            roles,
            generators,
            config,
            cancel_callback,
        )
        result_drafts.extend(chosen)
        processed += len(window)
        _report_progress(progress_callback, 80, 95, processed, len(groups))
    stage_timings["optimization"] = time.perf_counter() - optimization_started

    conversion_started = time.perf_counter()
    arranged = _drafts_to_arrangement_notes(result_drafts, summary, config)
    arranged, repair_iterations, fallback_usage = _repair_arrangement(
        arranged,
        analysis,
        config,
    )
    arranged = _assign_fingering(arranged, config)
    pedal_events = _build_pedal_events(events, analysis.chords, summary, config)
    stage_timings["repair_and_fingering"] = time.perf_counter() - conversion_started
    stage_timings["total"] = time.perf_counter() - started_at
    report = _build_report(
        analysis,
        arranged,
        config,
        repair_iterations,
        fallback_usage,
        stage_timings,
    )
    duration = max(
        summary.duration,
        max((note.end_second for note in arranged), default=0.0),
        max((pedal.time for pedal in pedal_events), default=0.0),
    )
    _report_progress(progress_callback, 95, 100, 1, 1)
    return ArrangementPlan(
        algorithm_version=ARRANGEMENT_ALGORITHM_VERSION,
        source_file_hash=summary.file_hash,
        config_key=config.cache_key(),
        duration=duration,
        notes=arranged,
        pedal_events=pedal_events,
        sections=analysis.sections,
        voices=analysis.voices,
        roles=analysis.roles,
        chords=analysis.chords,
        note_analysis=analysis.note_analysis,
        report=report,
    )


def _optimize_window(
    groups: tuple[tuple[NormalizedNote, ...], ...],
    boundary: _BeamState,
    analysis: AnalysisBundle,
    analyses: dict[int, NoteAnalysis],
    roles: dict[int, RoleProbabilities],
    generators: tuple[CandidateGenerator, ...],
    config: PianoArrangementConfig,
    cancel_callback: CancelCallback | None,
) -> tuple[_BeamState, tuple[ArrangementDraft, ...]]:
    beam = (
        replace(boundary, score=0.0, drafts=()),
    )
    for group in groups:
        if cancel_callback is not None and cancel_callback():
            raise ArrangementCancelled("Piano arrangement was cancelled")
        section = _section_at(analysis.sections, group[0].onset_beat)
        generator_context = GeneratorContext(
            analyses=analyses,
            roles=roles,
            chords=analysis.chords,
            section=section,
            config=config,
        )
        drafts: list[ArrangementDraft] = []
        for generator in generators:
            drafts.extend(generator.generate(group, generator_context))
        if not drafts:
            drafts.extend(
                SourceReductionGenerator().generate(
                    group,
                    generator_context,
                )
            )
        next_states: list[_BeamState] = []
        for state in beam:
            for draft in drafts[:64]:
                state_score, right_center, left_center, melody, bass = _score_transition(
                    state,
                    draft,
                    group,
                    analyses,
                    config,
                )
                if math.isinf(state_score) and state_score < 0:
                    continue
                next_states.append(
                    _BeamState(
                        score=state.score + state_score,
                        right_center=right_center,
                        left_center=left_center,
                        last_melody_pitch=melody,
                        last_bass_pitch=bass,
                        texture=draft.texture,
                        drafts=(*state.drafts, draft),
                    )
                )
        if not next_states:
            continue
        dominated: dict[tuple[int, int, str], _BeamState] = {}
        for state in next_states:
            signature = (
                round(state.right_center / 3),
                round(state.left_center / 3),
                state.texture.value if state.texture else "",
            )
            previous = dominated.get(signature)
            if previous is None or state.score > previous.score:
                dominated[signature] = state
        beam = tuple(
            sorted(
                dominated.values(),
                key=lambda state: state.score,
                reverse=True,
            )[:config.beam_width]
        )
    if not beam:
        return boundary, ()
    best = max(beam, key=lambda state: state.score)
    final_boundary = replace(best, drafts=())
    return final_boundary, best.drafts


def _score_transition(
    state: _BeamState,
    draft: ArrangementDraft,
    source_group: tuple[NormalizedNote, ...],
    analyses: dict[int, NoteAnalysis],
    config: PianoArrangementConfig,
) -> tuple[float, float, float, int | None, int | None]:
    right = [note.pitch for note in draft.notes if note.hand == Hand.RIGHT]
    left = [note.pitch for note in draft.notes if note.hand == Hand.LEFT]
    profile = config.target_profile
    if any(not profile.pitch_min <= note.pitch <= profile.pitch_max for note in draft.notes):
        return -math.inf, state.right_center, state.left_center, None, None
    if len(right) > profile.max_simultaneous_notes_per_hand:
        return -math.inf, state.right_center, state.left_center, None, None
    if len(left) > profile.max_simultaneous_notes_per_hand:
        return -math.inf, state.right_center, state.left_center, None, None
    right_span = max(right) - min(right) if right else 0
    left_span = max(left) - min(left) if left else 0
    if max(right_span, left_span) > profile.absolute_max_span:
        return -math.inf, state.right_center, state.left_center, None, None
    right_center = statistics.fmean(right) if right else state.right_center
    left_center = statistics.fmean(left) if left else state.left_center
    elapsed = max(
        0.04,
        source_group[0].onset_second
        - min((note.source.onset_second for note in draft.notes), default=0.0)
        + 0.04,
    )
    movement = (
        abs(right_center - state.right_center)
        + abs(left_center - state.left_center)
    ) / elapsed
    span_cost = (
        max(0, right_span - profile.comfortable_span)
        + max(0, left_span - profile.comfortable_span)
    ) / 12.0
    crossing = (
        1.0 if right and left and min(right) < max(left) - 3 else 0.0
    )
    muddy = sum(
        1
        for notes in (right, left)
        if len(notes) >= 3 and max(notes) < 52 and max(notes) - min(notes) < 7
    )
    melody = next(
        (note.pitch for note in draft.notes if note.role == "melody"),
        state.last_melody_pitch,
    )
    bass = next(
        (note.pitch for note in draft.notes if note.role == "bass"),
        state.last_bass_pitch,
    )
    voice_leading = 0.0
    if melody is not None and state.last_melody_pitch is not None:
        voice_leading += math.exp(-abs(melody - state.last_melody_pitch) / 7.0)
    if bass is not None and state.last_bass_pitch is not None:
        voice_leading += math.exp(-abs(bass - state.last_bass_pitch) / 9.0)
    texture_continuity = (
        1.0 if state.texture is None or state.texture == draft.texture else -0.25
    )
    unnecessary_edits = sum(
        note.origin_type != OriginType.SOURCE for note in draft.notes
    ) / max(1, len(draft.notes))
    generated_penalty = draft.generated_count / max(1, len(draft.notes))
    fidelity_weight, harmony_weight, edit_weight = {
        "faithful": (2.70, 1.05, 0.48),
        "pianistic": (1.85, 1.65, 0.18),
        "balanced": (2.20, 1.35, 0.30),
    }[config.style]
    score = (
        fidelity_weight * draft.fidelity
        + harmony_weight * draft.harmonic_similarity
        + 1.05 * draft.rhythmic_similarity
        + 0.58 * voice_leading
        + 0.35 * texture_continuity
        - profile.movement_cost_per_second * movement
        - 0.75 * span_cost
        - 1.20 * crossing
        - 0.90 * muddy
        - edit_weight * unnecessary_edits
        - 0.24 * generated_penalty
    )
    return score, right_center, left_center, melody, bass


def _drafts_to_arrangement_notes(
    drafts: list[ArrangementDraft],
    summary: MidiSummary,
    config: PianoArrangementConfig,
) -> tuple[ArrangementNote, ...]:
    result: list[ArrangementNote] = []
    next_id = 0
    for draft in drafts:
        for note in draft.notes:
            start_beat = (
                note.source.quantized_onset
                + note.source.microtiming_residual
                if config.preserve_microtiming
                else note.source.quantized_onset
            )
            start_beat += note.start_offset_beat
            duration_beat = (
                note.source.offset_beat - note.source.onset_beat
                if note.origin_type
                in {OriginType.SOURCE, OriginType.OCTAVE_SHIFTED, OriginType.REVOICED}
                else note.source.quantized_duration
            )
            duration_beat *= note.duration_scale
            end_beat = max(start_beat + 1 / 64, start_beat + duration_beat)
            start_second = _beat_to_seconds(start_beat, summary)
            end_second = max(
                start_second + 0.025,
                _beat_to_seconds(end_beat, summary),
            )
            result.append(
                ArrangementNote(
                    arrangement_note_id=next_id,
                    pitch=note.pitch,
                    velocity=_arranged_velocity(note),
                    start_tick=round(start_beat * summary.ticks_per_beat),
                    end_tick=round(end_beat * summary.ticks_per_beat),
                    start_beat=start_beat,
                    end_beat=end_beat,
                    start_second=start_second,
                    end_second=end_second,
                    hand=note.hand,
                    finger=None,
                    source_track=note.source.track,
                    source_channel=note.source.channel,
                    source_note_ids=note.source_note_ids,
                    origin_type=note.origin_type,
                    activation_difficulty=note.activation_difficulty,
                    role=note.role,
                )
            )
            next_id += 1
    return tuple(
        sorted(
            result,
            key=lambda note: (
                note.start_second,
                note.pitch,
                note.end_second,
                note.arrangement_note_id,
            ),
        )
    )


def _repair_arrangement(
    notes: tuple[ArrangementNote, ...],
    analysis: AnalysisBundle,
    config: PianoArrangementConfig,
) -> tuple[tuple[ArrangementNote, ...], int, tuple[str, ...]]:
    current = list(notes)
    profile = config.target_profile
    fallbacks: list[str] = []
    iterations = 0
    for iterations in range(config.max_repair_iterations + 1):
        violations = _find_violations(current, profile)
        if not violations:
            break
        if iterations >= config.max_repair_iterations:
            break
        for onset, hand in violations:
            indexes = [
                index
                for index, note in enumerate(current)
                if round(note.start_beat * 96) == onset and note.hand == hand
            ]
            hand_notes = [current[index] for index in indexes]
            if not hand_notes:
                continue
            pitches = [note.pitch for note in hand_notes]
            if max(pitches) - min(pitches) > profile.absolute_max_span:
                outside = min(
                    hand_notes,
                    key=lambda note: (
                        note.role in {"melody", "bass"},
                        -note.activation_difficulty,
                    ),
                )
                shifted_pitch = _best_octave_inside_span(
                    outside.pitch,
                    pitches,
                    profile,
                )
                if shifted_pitch != outside.pitch:
                    target = current.index(outside)
                    current[target] = replace(
                        outside,
                        pitch=shifted_pitch,
                        origin_type=OriginType.REVOICED,
                    )
                    continue
            removable = [
                note
                for note in hand_notes
                if note.role not in {"melody", "bass"}
            ]
            if removable:
                remove = max(
                    removable,
                    key=lambda note: note.activation_difficulty,
                )
                current.remove(remove)
    remaining = _find_violations(current, profile)
    if remaining:
        fallbacks.append("melody_structural_bass_minimum_shell")
        current = [
            note
            for note in current
            if note.role in {"melody", "bass"}
            or note.activation_difficulty <= 0.30
        ]
    if _find_violations(current, profile):
        fallbacks.append("melody_sparse_bass")
        current = [
            note for note in current if note.role in {"melody", "bass"}
        ]
    return tuple(current), iterations, tuple(fallbacks)


def _assign_fingering(
    notes: tuple[ArrangementNote, ...],
    config: PianoArrangementConfig,
) -> tuple[ArrangementNote, ...]:
    grouped: dict[tuple[int, Hand], list[ArrangementNote]] = defaultdict(list)
    for note in notes:
        grouped[(round(note.start_beat * 96), note.hand)].append(note)
    assigned: dict[int, int] = {}
    geometry = KeyboardGeometry()
    for hand in (Hand.LEFT, Hand.RIGHT):
        hand_groups = [
            tuple(sorted(group, key=lambda note: note.pitch))
            for (onset, group_hand), group in sorted(grouped.items())
            if group_hand == hand
        ]
        if not hand_groups:
            continue
        states: tuple[_FingeringState, ...] = ()
        for group in hand_groups:
            candidates = _fingering_candidates(len(group), hand)
            next_states: list[_FingeringState] = []
            if not states:
                for fingers in candidates:
                    next_states.append(
                        _FingeringState(
                            cost=_fingering_intrinsic_cost(
                                group,
                                fingers,
                                geometry,
                                config,
                            ),
                            previous=None,
                            assignments=tuple(
                                (note.arrangement_note_id, finger)
                                for note, finger in zip(group, fingers)
                            ),
                            notes=group,
                            fingers=fingers,
                            time=group[0].start_second,
                        )
                    )
            else:
                for previous in states:
                    for fingers in candidates:
                        next_states.append(
                            _FingeringState(
                                cost=(
                                    previous.cost
                                    + _fingering_intrinsic_cost(
                                        group,
                                        fingers,
                                        geometry,
                                        config,
                                    )
                                    + _fingering_transition_cost(
                                        previous,
                                        group,
                                        fingers,
                                        geometry,
                                    )
                                ),
                                previous=previous,
                                assignments=tuple(
                                    (note.arrangement_note_id, finger)
                                    for note, finger in zip(group, fingers)
                                ),
                                notes=group,
                                fingers=fingers,
                                time=group[0].start_second,
                            )
                        )
            states = tuple(
                sorted(next_states, key=lambda state: state.cost)[:16]
            )
        cursor = min(states, key=lambda state: state.cost)
        while cursor is not None:
            for note_id, finger in cursor.assignments:
                assigned[note_id] = finger
            cursor = cursor.previous
    return tuple(
        replace(note, finger=assigned.get(note.arrangement_note_id))
        for note in notes
    )


def _build_pedal_events(
    events: list[MidiEvent],
    chords: tuple[ChordEvent, ...],
    summary: MidiSummary,
    config: PianoArrangementConfig,
) -> tuple[PedalEvent, ...]:
    if config.pedal_policy == PedalPolicy.IGNORE:
        return ()
    if config.pedal_policy == PedalPolicy.PRESERVE:
        return tuple(
            PedalEvent(
                time=event.time,
                tick=int(event.tick or 0),
                beat=float(event.beat or 0.0),
                enabled=bool((event.value or 0) >= 64),
                source_track=int(event.track or 0),
                source_channel=int(event.channel or 0),
            )
            for event in events
            if event.kind == "sustain"
            and event.channel is not None
            and event.value is not None
        )
    if config.pedal_policy == PedalPolicy.BAKE:
        return ()
    result: list[PedalEvent] = []
    for chord in chords:
        if chord.root is None or chord.confidence < 0.60:
            continue
        start = chord.start_beat
        end = max(start, chord.end_beat - 1 / 32)
        result.extend(
            (
                PedalEvent(
                    time=_beat_to_seconds(start, summary),
                    tick=round(start * summary.ticks_per_beat),
                    beat=start,
                    enabled=True,
                ),
                PedalEvent(
                    time=_beat_to_seconds(end, summary),
                    tick=round(end * summary.ticks_per_beat),
                    beat=end,
                    enabled=False,
                ),
            )
        )
    return tuple(result)


def _build_report(
    analysis: AnalysisBundle,
    output: tuple[ArrangementNote, ...],
    config: PianoArrangementConfig,
    repair_iterations: int,
    fallback_usage: tuple[str, ...],
    stage_timings: dict[str, float],
) -> ArrangementReport:
    source_ids = {
        source_id for note in output for source_id in note.source_note_ids
    }
    input_ids = {note.note_id for note in analysis.notes if note.channel != 9}
    source_notes = [note for note in output if note.source_note_ids]
    melody_anchors = {
        item.note_id
        for item in analysis.note_analysis
        if item.anchor and item.melody_probability >= item.bass_probability
    }
    bass_anchors = {
        item.note_id
        for item in analysis.note_analysis
        if item.anchor and item.bass_probability > item.melody_probability
    }
    spans, movements, simultaneous = _playability_metrics(output)
    chord_confidences = [chord.confidence for chord in analysis.chords]
    output_pcs = Counter(note.pitch % 12 for note in output)
    input_pcs = Counter(note.pitch_class for note in analysis.notes if note.channel != 9)
    source_weights = {
        item.note_id: item.importance for item in analysis.note_analysis
    }
    total_weight = sum(source_weights.get(note_id, 0.0) for note_id in input_ids)
    kept_weight = sum(source_weights.get(note_id, 0.0) for note_id in source_ids)
    hard_violations = len(_find_violations(list(output), config.target_profile))
    naturalness: PianoNaturalnessScorer = RuleBasedPianoNaturalnessScorer()
    _naturalness_score = naturalness.score(output)
    warnings = list(analysis.warnings)
    if hard_violations:
        warnings.append("hard_playability_violation")
    if not melody_anchors:
        warnings.append("no_clear_melody")
    return ArrangementReport(
        input_note_count=len(input_ids),
        output_note_count=len(output),
        kept_source_notes=len(source_ids.intersection(input_ids)),
        deleted_source_notes=len(input_ids.difference(source_ids)),
        octave_shifted_notes=sum(
            note.origin_type
            in {OriginType.OCTAVE_SHIFTED, OriginType.REVOICED}
            for note in output
        ),
        generated_notes=sum(not note.source_note_ids for note in output),
        merged_duplicate_notes=sum(
            note.origin_type == OriginType.MERGED_DUPLICATE for note in output
        ),
        duration_adjusted_notes=0,
        melody_anchor_recall=_recall(melody_anchors, source_ids),
        bass_anchor_recall=_recall(bass_anchors, source_ids),
        weighted_source_coverage=kept_weight / total_weight if total_weight else 1.0,
        harmonic_similarity=_counter_similarity(input_pcs, output_pcs),
        rhythmic_similarity=_rhythmic_output_similarity(analysis.notes, output),
        pitch_class_similarity=_counter_similarity(input_pcs, output_pcs),
        maximum_hand_span=max(spans, default=0),
        percentile_hand_span=_percentile(spans, 0.95),
        maximum_hand_movement=max(movements, default=0.0),
        percentile_hand_movement=_percentile(movements, 0.95),
        maximum_simultaneous_notes_per_hand=simultaneous,
        fingering_infeasible_count=sum(note.finger is None for note in output),
        hard_violation_count=hard_violations,
        repair_iteration_count=repair_iterations,
        detected_sections=len(analysis.sections),
        detected_textures=tuple(section.texture.value for section in analysis.sections),
        melody_confidence=max(
            (item.melody_probability for item in analysis.note_analysis),
            default=0.0,
        ),
        bass_confidence=max(
            (item.bass_probability for item in analysis.note_analysis),
            default=0.0,
        ),
        chord_confidence_statistics=(
            min(chord_confidences, default=0.0),
            statistics.fmean(chord_confidences) if chord_confidences else 0.0,
            max(chord_confidences, default=0.0),
        ),
        fallback_usage=fallback_usage,
        warnings=tuple(dict.fromkeys(warnings)),
        processing_time_per_stage=tuple(sorted(stage_timings.items())),
        config_snapshot=tuple(
            sorted(
                (str(key), str(value))
                for key, value in config.cache_payload().items()
            )
        ),
        model_provider_versions=(
            ("affinity", "rule-affinity-1"),
            ("roles", "rule-role-1"),
            ("importance", "rule-importance-1"),
            ("naturalness", naturalness.version),
        ),
    )


def _group_notes_by_onset(
    notes: tuple[NormalizedNote, ...],
) -> tuple[tuple[NormalizedNote, ...], ...]:
    groups: list[list[NormalizedNote]] = []
    for note in notes:
        if note.channel == 9:
            continue
        if groups and abs(note.quantized_onset - groups[-1][0].quantized_onset) <= 1 / 64:
            groups[-1].append(note)
        else:
            groups.append([note])
    return tuple(tuple(group) for group in groups)


def _merge_and_limit(
    notes: tuple[DraftNote, ...] | list[DraftNote],
    config: PianoArrangementConfig,
) -> tuple[DraftNote, ...]:
    merged: dict[tuple[int, Hand], DraftNote] = {}
    for note in notes:
        key = (note.pitch, note.hand)
        previous = merged.get(key)
        if previous is None or (
            note.importance,
            bool(note.source_note_ids),
        ) > (
            previous.importance,
            bool(previous.source_note_ids),
        ):
            if previous is not None:
                note = replace(
                    note,
                    source_note_ids=tuple(
                        sorted(
                            set(previous.source_note_ids).union(note.source_note_ids)
                        )
                    ),
                    origin_type=OriginType.MERGED_DUPLICATE,
                )
            merged[key] = note
        elif previous is not None:
            merged[key] = replace(
                previous,
                source_note_ids=tuple(
                    sorted(set(previous.source_note_ids).union(note.source_note_ids))
                ),
                origin_type=OriginType.MERGED_DUPLICATE,
            )
    result: list[DraftNote] = []
    maximum = config.target_profile.max_simultaneous_notes_per_hand
    for hand in (Hand.LEFT, Hand.RIGHT):
        hand_notes = sorted(
            (note for note in merged.values() if note.hand == hand),
            key=lambda note: (
                note.role in {"melody", "bass"},
                note.importance,
                -note.activation_difficulty,
            ),
            reverse=True,
        )[:maximum]
        hand_notes = _trim_span(hand_notes, config.target_profile.absolute_max_span)
        result.extend(hand_notes)
    return tuple(sorted(result, key=lambda note: (note.hand.value, note.pitch)))


def _trim_span(notes: list[DraftNote], max_span: int) -> list[DraftNote]:
    result = list(notes)
    while result and max(note.pitch for note in result) - min(note.pitch for note in result) > max_span:
        removable = [
            note for note in result if note.role not in {"melody", "bass"}
        ] or result
        result.remove(min(removable, key=lambda note: note.importance))
    return result


def _generated_chord_shell(
    notes: tuple[NormalizedNote, ...],
    anchors: list[DraftNote],
    chord: ChordEvent,
    context: GeneratorContext,
) -> tuple[DraftNote, ...]:
    if chord.root is None:
        return ()
    source = max(
        (note for note in notes if note.channel != 9),
        key=lambda note: context.analyses[note.note_id].importance,
        default=None,
    )
    if source is None:
        return ()
    existing = {note.pitch % 12 for note in anchors}
    ordered_pcs = [chord.root]
    quality_intervals = {
        "minor": (3, 10, 7),
        "minor7": (3, 10, 7),
        "major7": (4, 11, 7),
        "7": (4, 10, 7),
        "half-diminished": (3, 10, 6),
        "diminished7": (3, 9, 6),
    }
    ordered_pcs.extend(
        (chord.root + interval) % 12
        for interval in quality_intervals.get(chord.quality, (4, 7))
    )
    generated: list[DraftNote] = []
    melody_pitch = max(
        (note.pitch for note in anchors if note.role == "melody"),
        default=84,
    )
    for pitch_class in ordered_pcs:
        if pitch_class in existing:
            continue
        hand = Hand.RIGHT if len(generated) >= 2 else Hand.LEFT
        center = 60 if hand == Hand.RIGHT else 45
        pitch = _nearest_pitch_class(
            center,
            pitch_class,
            context.config.target_profile.pitch_min,
            min(
                context.config.target_profile.pitch_max,
                melody_pitch - 1 if hand == Hand.RIGHT else 60,
            ),
        )
        if pitch is None:
            continue
        generated.append(
            DraftNote(
                source=source,
                pitch=pitch,
                hand=hand,
                role="inner_harmony",
                origin_type=OriginType.GENERATED_CHORD_TONE,
                source_note_ids=(),
                activation_difficulty=0.56,
                importance=0.36,
            )
        )
        if len(generated) >= 3:
            break
    return tuple(generated)


def _texture_pattern_pitches(
    texture: TextureType,
    root_pitch: int | None,
    pitch_classes: tuple[int, ...],
) -> tuple[int, ...]:
    if root_pitch is None:
        return ()
    chord_pitches = [
        _nearest_pitch_class(root_pitch + 5, pitch_class, 33, 58)
        for pitch_class in pitch_classes
    ]
    chord_pitches = [pitch for pitch in chord_pitches if pitch is not None]
    if texture == TextureType.BLOCK_CHORD:
        return tuple(chord_pitches[:3])
    if texture == TextureType.OSTINATO:
        return tuple((root_pitch, root_pitch + 7))
    if texture == TextureType.BASS_RIFF:
        return (root_pitch,)
    return tuple((root_pitch, *chord_pitches[:2]))


def _source_fidelity(
    output: tuple[DraftNote, ...],
    source: tuple[NormalizedNote, ...],
    analyses: dict[int, NoteAnalysis],
) -> float:
    source_weight = sum(analyses[note.note_id].importance for note in source)
    kept = {
        note_id for note in output for note_id in note.source_note_ids
    }
    kept_weight = sum(
        analyses[note.note_id].importance
        for note in source
        if note.note_id in kept
    )
    return kept_weight / source_weight if source_weight else 1.0


def _harmony_similarity(
    output: tuple[DraftNote, ...],
    chords: tuple[ChordEvent, ...],
) -> float:
    if not output:
        return 0.0
    beat = output[0].source.onset_beat
    chord = _chord_at(chords, beat)
    if chord is None or not chord.pitch_classes:
        return 0.75
    return sum(note.pitch % 12 in chord.pitch_classes for note in output) / len(output)


def _primary_role(
    roles: RoleProbabilities | None,
    pitch: int,
) -> str:
    if roles is None:
        return "inner_harmony"
    values = {
        "melody": roles.melody,
        "bass": roles.bass,
        "countermelody": roles.countermelody,
        "inner_harmony": roles.inner_harmony,
        "rhythmic_accompaniment": roles.rhythmic_accompaniment,
        "pad": roles.pad,
        "ostinato": roles.ostinato,
    }
    role = max(values, key=values.get)
    if role == "inner_harmony" and pitch < 45:
        return "bass"
    return role


def _role_for_note(
    note: NormalizedNote,
    context: GeneratorContext,
) -> str:
    source = (note.track, note.channel)
    if context.config.melody_override == source:
        return "melody"
    if context.config.bass_override == source:
        return "bass"
    return _primary_role(context.roles.get(note.note_id), note.pitch)


def _activation_difficulty(note_id: int, analysis: NoteAnalysis) -> float:
    stable_tie_break = (note_id * 2654435761 % 997) / 9970.0
    return _clamp01(
        0.92
        - 0.72 * analysis.importance
        - (0.18 if analysis.anchor else 0.0)
        + stable_tie_break
    )


def _fit_pitch_for_hand(
    pitch: int,
    hand: Hand,
    config: PianoArrangementConfig,
) -> tuple[int, bool]:
    profile = config.target_profile
    target_low, target_high = (
        (48, min(profile.pitch_max, 88))
        if hand == Hand.RIGHT
        else (max(profile.pitch_min, 28), 64)
    )
    candidates = [
        pitch + shift
        for shift in (-24, -12, 0, 12, 24)
        if profile.pitch_min <= pitch + shift <= profile.pitch_max
    ]
    if not candidates:
        return max(profile.pitch_min, min(profile.pitch_max, pitch)), True
    center = (target_low + target_high) / 2.0
    selected = min(
        candidates,
        key=lambda candidate: (
            0 if target_low <= candidate <= target_high else 1,
            abs(candidate - center),
            abs(candidate - pitch),
        ),
    )
    return selected, selected != pitch


def _dynamic_split_pitch(notes: list[NormalizedNote]) -> float:
    pitches = sorted(note.pitch for note in notes)
    if len(pitches) < 2:
        return 60.0
    gaps = [
        (pitches[index + 1] - pitches[index], index)
        for index in range(len(pitches) - 1)
    ]
    _gap, index = max(gaps, key=lambda item: (item[0], -abs(pitches[item[1]] - 60)))
    return (pitches[index] + pitches[index + 1]) / 2.0


def _section_at(
    sections: tuple[SectionAnalysis, ...],
    beat: float,
) -> SectionAnalysis:
    for section in sections:
        if section.start_beat <= beat < section.end_beat:
            return section
    if sections:
        return sections[-1]
    return SectionAnalysis(
        0,
        0.0,
        max(4.0, beat + 1.0),
        TextureType.MIXED,
        (0.0,) * 12,
        (0.0,) * 16,
        None,
        0.0,
        0.0,
        0.0,
        0.0,
    )


def _chord_at(
    chords: tuple[ChordEvent, ...],
    beat: float,
) -> ChordEvent | None:
    return next(
        (
            chord
            for chord in chords
            if chord.start_beat <= beat < chord.end_beat
        ),
        None,
    )


def _nearest_pitch_class(
    center: int,
    pitch_class: int,
    minimum: int,
    maximum: int,
) -> int | None:
    candidates = [
        pitch
        for pitch in range(max(0, minimum), min(127, maximum) + 1)
        if pitch % 12 == pitch_class
    ]
    return min(candidates, key=lambda pitch: abs(pitch - center)) if candidates else None


def _arranged_velocity(note: DraftNote) -> int:
    role_gain = {
        "melody": 1.10,
        "bass": 0.96,
        "countermelody": 0.91,
        "inner_harmony": 0.78,
        "rhythmic_accompaniment": 0.82,
        "accompaniment": 0.78,
        "pad": 0.72,
        "ostinato": 0.82,
    }.get(note.role, 0.82)
    source = note.source.velocity
    normalized = 42 + source / 127.0 * 58
    return max(1, min(127, round(normalized * role_gain)))


def _beat_to_seconds(beat: float, summary: MidiSummary) -> float:
    changes = summary.tempo_changes
    if not changes:
        return max(0.0, beat * 0.5)
    current = changes[0]
    seconds = current.second
    previous_beat = current.beat
    tempo = current.microseconds_per_beat
    for change in changes[1:]:
        if beat < change.beat:
            break
        seconds += (change.beat - previous_beat) * tempo / 1_000_000.0
        previous_beat = change.beat
        tempo = change.microseconds_per_beat
    return max(0.0, seconds + (beat - previous_beat) * tempo / 1_000_000.0)


def _find_violations(
    notes: list[ArrangementNote],
    profile: object,
) -> list[tuple[int, Hand]]:
    grouped: dict[tuple[int, Hand], list[int]] = defaultdict(list)
    for note in notes:
        grouped[(round(note.start_beat * 96), note.hand)].append(note.pitch)
    violations: list[tuple[int, Hand]] = []
    for key, pitches in grouped.items():
        if (
            len(pitches) > profile.max_simultaneous_notes_per_hand
            or max(pitches) - min(pitches) > profile.absolute_max_span
            or any(
                pitch < profile.pitch_min or pitch > profile.pitch_max
                for pitch in pitches
            )
        ):
            violations.append(key)
    return violations


def _best_octave_inside_span(
    pitch: int,
    peers: list[int],
    profile: object,
) -> int:
    candidates = [
        pitch + shift
        for shift in (-24, -12, 12, 24)
        if profile.pitch_min <= pitch + shift <= profile.pitch_max
    ]
    return min(
        candidates,
        key=lambda candidate: (
            max((*peers, candidate)) - min((*peers, candidate)),
            abs(candidate - pitch),
        ),
        default=pitch,
    )


def _fingering_candidates(count: int, hand: Hand) -> tuple[tuple[int, ...], ...]:
    count = max(1, min(5, int(count)))
    values = tuple(combinations(range(1, 6), count))
    if hand == Hand.LEFT:
        return tuple(tuple(reversed(value)) for value in values)
    return values


def _fingering_intrinsic_cost(
    notes: tuple[ArrangementNote, ...],
    fingers: tuple[int, ...],
    geometry: KeyboardGeometry,
    config: PianoArrangementConfig,
) -> float:
    if not notes:
        return 0.0
    physical_span = geometry.distance(notes[0].pitch, notes[-1].pitch)
    comfortable = config.target_profile.comfortable_span * 7.0 / 12.0
    stretch = max(0.0, physical_span - comfortable)
    thumb_on_black = sum(
        finger == 1 and note.pitch % 12 in {1, 3, 6, 8, 10}
        for note, finger in zip(notes, fingers)
    )
    finger_stretch = sum(
        max(
            0.0,
            geometry.distance(first.pitch, second.pitch)
            - abs(second_finger - first_finger) * 1.35,
        )
        for first, second, first_finger, second_finger in zip(
            notes,
            notes[1:],
            fingers,
            fingers[1:],
        )
    )
    return stretch * 0.35 + thumb_on_black * 0.18 + finger_stretch * 0.24


def _fingering_transition_cost(
    previous: _FingeringState,
    notes: tuple[ArrangementNote, ...],
    fingers: tuple[int, ...],
    geometry: KeyboardGeometry,
) -> float:
    elapsed = max(0.03, notes[0].start_second - previous.time)
    old_center = statistics.fmean(
        geometry.position(note.pitch) for note in previous.notes
    )
    new_center = statistics.fmean(
        geometry.position(note.pitch) for note in notes
    )
    movement = abs(new_center - old_center) / elapsed
    repetition = 0.0
    collision = 0.0
    crossing = 0.0
    for note, finger in zip(notes, fingers):
        old_index = min(
            range(len(previous.notes)),
            key=lambda index: abs(previous.notes[index].pitch - note.pitch),
        )
        old_note = previous.notes[old_index]
        old_finger = previous.fingers[old_index]
        if old_finger == finger:
            repetition += 0.08 if old_note.pitch == note.pitch else 0.42
            if old_note.end_second > note.start_second and old_note.pitch != note.pitch:
                collision += 3.0
        pitch_direction = note.pitch - old_note.pitch
        finger_direction = finger - old_finger
        if pitch_direction * finger_direction < 0:
            crossing += 0.16
    return movement * 0.025 + repetition + collision + crossing


def _playability_metrics(
    notes: tuple[ArrangementNote, ...],
) -> tuple[list[int], list[float], int]:
    grouped: dict[tuple[int, Hand], list[int]] = defaultdict(list)
    for note in notes:
        grouped[(round(note.start_beat * 96), note.hand)].append(note.pitch)
    spans = [max(pitches) - min(pitches) for pitches in grouped.values()]
    centers_by_hand: dict[Hand, list[tuple[float, float]]] = defaultdict(list)
    for (onset, hand), pitches in sorted(grouped.items()):
        centers_by_hand[hand].append((onset / 96.0, statistics.fmean(pitches)))
    movements: list[float] = []
    for values in centers_by_hand.values():
        for previous, current in zip(values, values[1:]):
            movements.append(
                abs(current[1] - previous[1]) / max(0.03, current[0] - previous[0])
            )
    return spans, movements, max((len(pitches) for pitches in grouped.values()), default=0)


def _rhythmic_output_similarity(
    source: tuple[NormalizedNote, ...],
    output: tuple[ArrangementNote, ...],
) -> float:
    source_hist = Counter(round(note.onset_beat * 4) % 16 for note in source)
    output_hist = Counter(round(note.start_beat * 4) % 16 for note in output)
    return _counter_similarity(source_hist, output_hist)


def _counter_similarity(first: Counter[int], second: Counter[int]) -> float:
    keys = set(first).union(second)
    if not keys:
        return 1.0
    numerator = sum(first[key] * second[key] for key in keys)
    denominator = math.sqrt(
        sum(first[key] ** 2 for key in keys)
        * sum(second[key] ** 2 for key in keys)
    )
    return numerator / denominator if denominator else 0.0


def _recall(expected: set[int], actual: set[int]) -> float:
    return len(expected.intersection(actual)) / len(expected) if expected else 1.0


def _percentile(values: list[float] | list[int], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
    return float(ordered[index])


def _report_progress(
    callback: ProgressCallback | None,
    minimum: int,
    maximum: int,
    current: int,
    total: int,
) -> None:
    if callback is None:
        return
    ratio = current / max(1, total)
    callback(round(minimum + (maximum - minimum) * ratio))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
