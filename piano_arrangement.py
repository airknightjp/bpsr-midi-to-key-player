from __future__ import annotations

import time
from pathlib import Path

from midi_parser import MidiEvent, MidiSummary, parse_midi
from piano_arrangement_analysis import (
    CancelCallback,
    ProgressCallback,
    analyze_midi_for_arrangement,
)
from piano_arrangement_cache import (
    load_arrangement_cache,
    save_arrangement_cache,
)
from piano_arrangement_models import (
    ArrangementPlan,
    PianoArrangementConfig,
)
from piano_arrangement_optimizer import optimize_piano_arrangement


def analyze_piano_arrangement(
    midi_data: str | Path | tuple[list[MidiEvent], MidiSummary],
    config: PianoArrangementConfig | None = None,
    *,
    progress_callback: ProgressCallback | None = None,
    cancel_callback: CancelCallback | None = None,
    use_cache: bool = True,
) -> ArrangementPlan:
    """Analyze MIDI and return a directly playable cached piano-solo plan."""
    normalized_config = (config or PianoArrangementConfig()).normalized()
    if isinstance(midi_data, tuple):
        events, summary = midi_data
    else:
        events, summary = parse_midi(midi_data)
    if use_cache:
        cached = load_arrangement_cache(summary.file_hash, normalized_config)
        if cached is not None:
            if progress_callback is not None:
                progress_callback(100)
            return cached

    started_at = time.perf_counter()
    analysis_started = time.perf_counter()
    analysis = analyze_midi_for_arrangement(
        events,
        summary,
        normalized_config,
        progress_callback=progress_callback,
        cancel_callback=cancel_callback,
    )
    stage_timings = {
        "analysis": time.perf_counter() - analysis_started,
    }
    plan = optimize_piano_arrangement(
        events,
        summary,
        analysis,
        normalized_config,
        started_at=started_at,
        stage_timings=stage_timings,
        progress_callback=progress_callback,
        cancel_callback=cancel_callback,
    )
    save_arrangement_cache(plan, normalized_config)
    return plan


def cached_piano_arrangement(
    source_file_hash: str,
    config: PianoArrangementConfig | None = None,
) -> ArrangementPlan | None:
    return load_arrangement_cache(
        source_file_hash,
        (config or PianoArrangementConfig()).normalized(),
    )
