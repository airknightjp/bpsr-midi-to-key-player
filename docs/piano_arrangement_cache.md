# Piano Solo Arrangement Cache

The piano-solo arranger analyzes a selected MIDI file in a worker process. It
does not create or export another MIDI file. The result is a versioned JSON
execution plan under:

```text
cache/piano_arrangements/<MIDI SHA-256>/<configuration SHA-256>.json
```

The configuration hash includes the algorithm version, analysis profile,
difficulty, style, target playability profile, pedal policy, generation flags,
overrides, and provider settings. A stale or mismatched cache is ignored.

## Runtime Flow

1. Parse and normalize source notes without changing the source MIDI.
2. Analyze sections, voices, roles, texture, harmony, and note importance.
3. Generate source-reduction, lead-sheet, texture-pattern, and polyphonic
   candidates.
4. Optimize candidates in bounded four-bar windows with beam and dominance
   pruning.
5. Assign hands and explicit fingering, then repair only violating passages.
6. Store the final note, pedal, hand, fingering, provenance, and report data.
7. Rebuild the existing `MidiEvent` sequence directly from JSON for sound
   playback and MIDI-to-key conversion.

The source file is used when no matching cache exists. A completed cache is
activated only when its MIDI hash and arrangement configuration still match
the selected file. When analysis finishes during playback or MIDI-to-key
conversion, the completed plan is applied immediately if `Use analysis` is
enabled.

## Analysis Profile

`Analysis beta` is the only profile. It runs all deterministic generators,
explicit fingering, the full beam, and all extension points. No external model
is bundled or downloaded.

The profile uses the Standard Piano range (MIDI notes 21 through 108), enforces
per-hand note and span limits, exclude channel 10 percussion from pitched
output, and preserve source-note provenance.

## Extension Points

The rule-based implementation exposes provider protocols for note affinity,
role probabilities, note importance, arrangement proposals, and piano
naturalness. A future model provider can propose candidates, but proposals
must still pass hand assignment, fingering, repair, and final validation.
