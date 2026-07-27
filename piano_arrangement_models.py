from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol

from config import PIANO_NOTE_MAX, PIANO_NOTE_MIN
from midi_parser import MidiEvent


ARRANGEMENT_ALGORITHM_VERSION = "1"
CACHE_DIRECTORY_NAME = "cache"
ARRANGEMENT_CACHE_DIRECTORY_NAME = "piano_arrangements"


class ArrangementQuality(str, Enum):
    BETA = "beta"


class OriginType(str, Enum):
    SOURCE = "SOURCE"
    OCTAVE_SHIFTED = "OCTAVE_SHIFTED"
    GENERATED_CHORD_TONE = "GENERATED_CHORD_TONE"
    GENERATED_PATTERN = "GENERATED_PATTERN"
    MERGED_DUPLICATE = "MERGED_DUPLICATE"
    REVOICED = "REVOICED"


class Hand(str, Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class TextureType(str, Enum):
    HOMOPHONIC = "HOMOPHONIC"
    POLYPHONIC = "POLYPHONIC"
    BLOCK_CHORD = "BLOCK_CHORD"
    ARPEGGIO = "ARPEGGIO"
    OSTINATO = "OSTINATO"
    PAD = "PAD"
    RHYTHMIC_HITS = "RHYTHMIC_HITS"
    BASS_RIFF = "BASS_RIFF"
    MIXED = "MIXED"


class PedalPolicy(str, Enum):
    PRESERVE = "PRESERVE"
    BAKE = "BAKE"
    IGNORE = "IGNORE"
    REGENERATE = "REGENERATE"


@dataclass(frozen=True)
class PlayabilityProfile:
    name: str = "standard_piano"
    pitch_min: int = PIANO_NOTE_MIN
    pitch_max: int = PIANO_NOTE_MAX
    max_simultaneous_notes_per_hand: int = 5
    max_active_notes_per_hand: int = 5
    comfortable_span: int = 12
    absolute_max_span: int = 16
    movement_cost_per_second: float = 0.08
    repeated_note_limit: int = 8
    hand_crossing_policy: str = "penalize"
    pedal_policy: PedalPolicy = PedalPolicy.PRESERVE
    strict_fingering: bool = True
    custom_target_constraints: tuple[str, ...] = ()


@dataclass(frozen=True)
class KeyboardGeometry:
    white_key_width: float = 1.0
    black_key_offset: float = 0.58

    def position(self, midi_note: int) -> float:
        octave, pitch_class = divmod(int(midi_note), 12)
        white_index = (0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6)[pitch_class]
        base = (octave * 7 + white_index) * self.white_key_width
        if pitch_class in {1, 3, 6, 8, 10}:
            return base + self.black_key_offset * self.white_key_width
        return base

    def distance(self, first_note: int, second_note: int) -> float:
        return abs(self.position(first_note) - self.position(second_note))


@dataclass(frozen=True)
class PianoArrangementConfig:
    style: str = "balanced"
    difficulty: float = 0.55
    quality: ArrangementQuality = ArrangementQuality.BETA
    beam_width: int = 256
    window_bars: int = 4
    overlap_bars: int = 1
    max_repair_iterations: int = 8
    chord_confidence_threshold: float = 0.70
    seed: int = 0
    allow_generated_notes: bool = True
    preserve_microtiming: bool = True
    use_external_model: bool = False
    melody_override: tuple[int, int] | None = None
    bass_override: tuple[int, int] | None = None
    excluded_parts: tuple[tuple[int, int], ...] = ()
    protected_parts: tuple[tuple[int, int], ...] = ()
    pedal_policy: PedalPolicy = PedalPolicy.PRESERVE
    target_profile: PlayabilityProfile = field(default_factory=PlayabilityProfile)

    def normalized(self) -> PianoArrangementConfig:
        quality = normalize_arrangement_quality(self.quality)
        return PianoArrangementConfig(
            style=(
                self.style
                if self.style in {"faithful", "balanced", "pianistic"}
                else "balanced"
            ),
            difficulty=max(0.0, min(1.0, float(self.difficulty))),
            quality=quality,
            beam_width=max(192, min(512, int(self.beam_width or 256))),
            window_bars=max(1, min(16, int(self.window_bars))),
            overlap_bars=max(0, min(8, int(self.overlap_bars))),
            max_repair_iterations=max(
                0, min(32, int(self.max_repair_iterations))
            ),
            chord_confidence_threshold=max(
                0.0, min(1.0, float(self.chord_confidence_threshold))
            ),
            seed=int(self.seed),
            allow_generated_notes=bool(self.allow_generated_notes),
            preserve_microtiming=bool(self.preserve_microtiming),
            use_external_model=bool(self.use_external_model),
            melody_override=self.melody_override,
            bass_override=self.bass_override,
            excluded_parts=tuple(sorted(set(self.excluded_parts))),
            protected_parts=tuple(sorted(set(self.protected_parts))),
            pedal_policy=PedalPolicy(self.pedal_policy),
            target_profile=self.target_profile,
        )

    def cache_payload(self) -> dict[str, object]:
        payload = asdict(self.normalized())
        payload["quality"] = self.normalized().quality.value
        payload["pedal_policy"] = self.normalized().pedal_policy.value
        target = dict(payload["target_profile"])
        target["pedal_policy"] = self.target_profile.pedal_policy.value
        payload["target_profile"] = target
        payload["algorithm_version"] = ARRANGEMENT_ALGORITHM_VERSION
        return payload

    def cache_key(self) -> str:
        encoded = json.dumps(
            self.cache_payload(),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def normalize_arrangement_quality(value: object) -> ArrangementQuality:
    return ArrangementQuality.BETA


@dataclass(frozen=True)
class NormalizedNote:
    note_id: int
    track: int
    channel: int
    program: int
    program_epoch: int
    pitch: int
    pitch_class: int
    velocity: int
    onset_tick: int
    offset_tick: int
    onset_beat: float
    offset_beat: float
    onset_second: float
    offset_second: float
    sounding_offset_second: float
    quantized_onset: float
    quantized_duration: float
    microtiming_residual: float
    source_note_ids: tuple[int, ...]
    origin_type: OriginType = OriginType.SOURCE

    @property
    def source_id(self) -> tuple[int, int, int]:
        return self.track, self.channel, self.program_epoch

    @property
    def duration(self) -> float:
        return max(0.0, self.offset_second - self.onset_second)


@dataclass(frozen=True)
class SectionAnalysis:
    index: int
    start_beat: float
    end_beat: float
    texture: TextureType
    chroma: tuple[float, ...]
    onset_histogram: tuple[float, ...]
    pitch_range: tuple[int, int] | None
    note_density: float
    polyphony: float
    sustain_ratio: float
    intensity: float
    repetition_of: int | None = None


@dataclass(frozen=True)
class VoiceSegment:
    voice_id: int
    source_id: tuple[int, int, int]
    note_ids: tuple[int, ...]
    start_beat: float
    end_beat: float


@dataclass(frozen=True)
class RoleProbabilities:
    melody: float
    bass: float
    countermelody: float
    inner_harmony: float
    rhythmic_accompaniment: float
    pad: float
    ostinato: float


@dataclass(frozen=True)
class ChordEvent:
    start_beat: float
    end_beat: float
    root: int | None
    quality: str
    bass_pitch_class: int | None
    pitch_classes: tuple[int, ...]
    confidence: float


@dataclass(frozen=True)
class NoteAnalysis:
    note_id: int
    importance: float
    melody_probability: float
    bass_probability: float
    countermelody_probability: float
    anchor: bool
    duplicate_probability: float
    ornament_probability: float
    feature_contributions: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class ArrangementNote:
    arrangement_note_id: int
    pitch: int
    velocity: int
    start_tick: int
    end_tick: int
    start_beat: float
    end_beat: float
    start_second: float
    end_second: float
    hand: Hand
    finger: int | None
    source_track: int
    source_channel: int
    source_note_ids: tuple[int, ...]
    origin_type: OriginType
    activation_difficulty: float
    role: str


@dataclass(frozen=True)
class PedalEvent:
    time: float
    tick: int
    beat: float
    enabled: bool
    source_track: int = 0
    source_channel: int = 0


@dataclass(frozen=True)
class ArrangementReport:
    input_note_count: int
    output_note_count: int
    kept_source_notes: int
    deleted_source_notes: int
    octave_shifted_notes: int
    generated_notes: int
    merged_duplicate_notes: int
    duration_adjusted_notes: int
    melody_anchor_recall: float
    bass_anchor_recall: float
    weighted_source_coverage: float
    harmonic_similarity: float
    rhythmic_similarity: float
    pitch_class_similarity: float
    maximum_hand_span: int
    percentile_hand_span: float
    maximum_hand_movement: float
    percentile_hand_movement: float
    maximum_simultaneous_notes_per_hand: int
    fingering_infeasible_count: int
    hard_violation_count: int
    repair_iteration_count: int
    detected_sections: int
    detected_textures: tuple[str, ...]
    melody_confidence: float
    bass_confidence: float
    chord_confidence_statistics: tuple[float, float, float]
    fallback_usage: tuple[str, ...]
    warnings: tuple[str, ...]
    processing_time_per_stage: tuple[tuple[str, float], ...]
    config_snapshot: tuple[tuple[str, str], ...]
    model_provider_versions: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ArrangementPlan:
    algorithm_version: str
    source_file_hash: str
    config_key: str
    duration: float
    notes: tuple[ArrangementNote, ...]
    pedal_events: tuple[PedalEvent, ...]
    sections: tuple[SectionAnalysis, ...]
    voices: tuple[VoiceSegment, ...]
    roles: tuple[tuple[int, RoleProbabilities], ...]
    chords: tuple[ChordEvent, ...]
    note_analysis: tuple[NoteAnalysis, ...]
    report: ArrangementReport

    def to_midi_events(self) -> list[MidiEvent]:
        events: list[MidiEvent] = []
        for note in self.notes:
            events.append(
                MidiEvent(
                    time=note.start_second,
                    kind="note_on",
                    channel=note.source_channel,
                    note=note.pitch,
                    velocity=note.velocity,
                    track=note.source_track,
                    tick=note.start_tick,
                    beat=note.start_beat,
                    program=0,
                    program_epoch=0,
                    note_id=note.arrangement_note_id,
                )
            )
            events.append(
                MidiEvent(
                    time=note.end_second,
                    kind="note_off",
                    channel=note.source_channel,
                    note=note.pitch,
                    velocity=0,
                    track=note.source_track,
                    tick=note.end_tick,
                    beat=note.end_beat,
                    program=0,
                    program_epoch=0,
                    note_id=note.arrangement_note_id,
                )
            )
        for pedal in self.pedal_events:
            events.append(
                MidiEvent(
                    time=pedal.time,
                    kind="sustain",
                    channel=pedal.source_channel,
                    value=127 if pedal.enabled else 0,
                    track=pedal.source_track,
                    tick=pedal.tick,
                    beat=pedal.beat,
                )
            )
        events.sort(
            key=lambda event: (
                event.time,
                0 if event.kind == "note_off" else 1,
                event.track if event.track is not None else -1,
                event.channel if event.channel is not None else -1,
                event.note if event.note is not None else -1,
            )
        )
        events.append(MidiEvent(time=self.duration, kind="end"))
        return events

    def to_dict(self) -> dict[str, object]:
        return _encode(asdict(self))

    @classmethod
    def from_dict(cls, payload: object) -> ArrangementPlan:
        if not isinstance(payload, dict):
            raise ValueError("Invalid arrangement cache")
        report_payload = _required_dict(payload, "report")
        return cls(
            algorithm_version=str(payload["algorithm_version"]),
            source_file_hash=str(payload["source_file_hash"]),
            config_key=str(payload["config_key"]),
            duration=float(payload["duration"]),
            notes=tuple(
                ArrangementNote(
                    **{
                        **item,
                        "hand": Hand(item["hand"]),
                        "origin_type": OriginType(item["origin_type"]),
                        "source_note_ids": tuple(item["source_note_ids"]),
                    }
                )
                for item in _required_list(payload, "notes")
            ),
            pedal_events=tuple(
                PedalEvent(**item)
                for item in _required_list(payload, "pedal_events")
            ),
            sections=tuple(
                SectionAnalysis(
                    **{
                        **item,
                        "texture": TextureType(item["texture"]),
                        "chroma": tuple(item["chroma"]),
                        "onset_histogram": tuple(item["onset_histogram"]),
                        "pitch_range": (
                            tuple(item["pitch_range"])
                            if item["pitch_range"] is not None
                            else None
                        ),
                    }
                )
                for item in _required_list(payload, "sections")
            ),
            voices=tuple(
                VoiceSegment(
                    **{
                        **item,
                        "source_id": tuple(item["source_id"]),
                        "note_ids": tuple(item["note_ids"]),
                    }
                )
                for item in _required_list(payload, "voices")
            ),
            roles=tuple(
                (int(item[0]), RoleProbabilities(**item[1]))
                for item in _required_list(payload, "roles")
            ),
            chords=tuple(
                ChordEvent(
                    **{
                        **item,
                        "pitch_classes": tuple(item["pitch_classes"]),
                    }
                )
                for item in _required_list(payload, "chords")
            ),
            note_analysis=tuple(
                NoteAnalysis(
                    **{
                        **item,
                        "feature_contributions": tuple(
                            (str(name), float(value))
                            for name, value in item["feature_contributions"]
                        ),
                    }
                )
                for item in _required_list(payload, "note_analysis")
            ),
            report=ArrangementReport(
                **{
                    **report_payload,
                    "detected_textures": tuple(
                        report_payload["detected_textures"]
                    ),
                    "fallback_usage": tuple(report_payload["fallback_usage"]),
                    "warnings": tuple(report_payload["warnings"]),
                    "chord_confidence_statistics": tuple(
                        float(value)
                        for value in report_payload[
                            "chord_confidence_statistics"
                        ]
                    ),
                    "processing_time_per_stage": tuple(
                        (str(name), float(value))
                        for name, value in report_payload[
                            "processing_time_per_stage"
                        ]
                    ),
                    "config_snapshot": tuple(
                        (str(name), str(value))
                        for name, value in report_payload["config_snapshot"]
                    ),
                    "model_provider_versions": tuple(
                        (str(name), str(value))
                        for name, value in report_payload[
                            "model_provider_versions"
                        ]
                    ),
                }
            ),
        )


class NoteAffinityProvider(Protocol):
    version: str

    def score(self, first: NormalizedNote, second: NormalizedNote) -> float: ...


class RoleProbabilityProvider(Protocol):
    version: str

    def probabilities(
        self,
        voice: VoiceSegment,
        notes: tuple[NormalizedNote, ...],
    ) -> RoleProbabilities: ...


class NoteImportanceProvider(Protocol):
    version: str

    def score(
        self,
        note: NormalizedNote,
        roles: RoleProbabilities,
    ) -> NoteAnalysis: ...


class ArrangementProposalProvider(Protocol):
    version: str

    def propose(self, *args: object, **kwargs: object) -> tuple[object, ...]: ...


class PianoNaturalnessScorer(Protocol):
    version: str

    def score(self, notes: tuple[ArrangementNote, ...]) -> float: ...


def arrangement_cache_root() -> Path:
    override = os.environ.get("BPSR_ARRANGEMENT_CACHE_DIR", "").strip()
    if override:
        return Path(override)
    base = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )
    return base / CACHE_DIRECTORY_NAME / ARRANGEMENT_CACHE_DIRECTORY_NAME


def arrangement_cache_path(
    source_file_hash: str,
    config: PianoArrangementConfig,
) -> Path:
    return (
        arrangement_cache_root()
        / source_file_hash
        / f"{config.cache_key()}.json"
    )


def _encode(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    return value


def _required_list(payload: dict[str, object], key: str) -> list[dict[str, object]]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"Invalid arrangement cache field: {key}")
    return value


def _required_dict(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Invalid arrangement cache field: {key}")
    return value
