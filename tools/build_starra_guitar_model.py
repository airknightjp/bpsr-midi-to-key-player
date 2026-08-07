from __future__ import annotations

import argparse
import json
import math
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np


MODEL_VERSION = 1
FRAME_SIZE = 4_096
HOP_SIZE = 512
PARTIAL_COUNT = 32
RESIDUAL_BAND_COUNT = 32
TRANSIENT_SECONDS = 0.14
PRE_ROLL_SECONDS = 0.012
SILENCE_TAIL_SECONDS = 0.04


@dataclass(frozen=True)
class NoteAnalysis:
    note: int
    waveform: np.ndarray
    f0_hz: np.ndarray
    partial_frequency_hz: np.ndarray
    partial_amplitude: np.ndarray
    partial_phase: np.ndarray
    formant_envelope: np.ndarray
    residual_band_rms: np.ndarray
    inharmonicity: np.ndarray
    transient_magnitude: np.ndarray
    transient_phase: np.ndarray


def _read_audio(path: Path) -> tuple[int, np.ndarray]:
    with wave.open(str(path), "rb") as stream:
        sample_rate = stream.getframerate()
        channels = stream.getnchannels()
        sample_width = stream.getsampwidth()
        if sample_width != 2:
            raise ValueError(f"Expected 16-bit PCM, got {sample_width * 8}-bit")
        samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2")
    stereo = samples.reshape(-1, channels).astype(np.float32) / 32_768.0
    return sample_rate, np.mean(stereo, axis=1, dtype=np.float32)


def _moving_rms(samples: np.ndarray, frame_size: int, hop_size: int) -> np.ndarray:
    if len(samples) < frame_size:
        return np.asarray([math.sqrt(float(np.mean(samples * samples)))], dtype=np.float32)
    squared = np.square(samples, dtype=np.float32)
    cumulative = np.concatenate((np.zeros(1, dtype=np.float64), np.cumsum(squared)))
    starts = np.arange(0, len(samples) - frame_size + 1, hop_size)
    energy = (cumulative[starts + frame_size] - cumulative[starts]) / frame_size
    return np.sqrt(np.maximum(energy, 0.0)).astype(np.float32)


def _extract_note(
    audio: np.ndarray,
    sample_rate: int,
    event: dict[str, object],
) -> np.ndarray:
    expected = round(float(event["onset_seconds"]) * sample_rate)
    search_end = min(len(audio), expected + round(0.5 * sample_rate))
    search = audio[expected:search_end]
    rms = _moving_rms(search, 480, 120)
    peak = float(np.max(rms, initial=0.0))
    threshold = max(1.0e-7, peak * 0.055)
    active = np.flatnonzero(rms >= threshold)
    onset = expected + (int(active[0]) * 120 if len(active) else 0)
    start = max(0, onset - round(PRE_ROLL_SECONDS * sample_rate))

    release = round(float(event["release_seconds"]) * sample_rate)
    upper = min(len(audio), release + round(0.25 * sample_rate))
    candidate = audio[onset:upper]
    nonzero = np.flatnonzero(np.abs(candidate) > 1.0 / 32_768.0)
    if len(nonzero):
        end = onset + int(nonzero[-1]) + round(SILENCE_TAIL_SECONDS * sample_rate)
    else:
        end = onset + round(0.5 * sample_rate)
    end = min(upper, end)
    note_audio = np.array(audio[start:end], dtype=np.float32, copy=True)
    note_audio -= float(np.mean(note_audio[: max(1, round(0.008 * sample_rate))]))
    return note_audio


def _quadratic_peak(magnitudes: np.ndarray, index: int) -> float:
    if index <= 0 or index >= len(magnitudes) - 1:
        return float(index)
    left = math.log(max(float(magnitudes[index - 1]), 1.0e-20))
    center = math.log(max(float(magnitudes[index]), 1.0e-20))
    right = math.log(max(float(magnitudes[index + 1]), 1.0e-20))
    denominator = left - 2.0 * center + right
    if abs(denominator) < 1.0e-12:
        return float(index)
    return float(index) + max(-0.5, min(0.5, 0.5 * (left - right) / denominator))


def _track_partials(
    samples: np.ndarray,
    sample_rate: int,
    note: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    expected_f0 = 440.0 * (2.0 ** ((note - 69) / 12.0))
    padded = np.pad(samples, (FRAME_SIZE // 2, FRAME_SIZE // 2))
    frame_starts = np.arange(0, len(padded) - FRAME_SIZE + 1, HOP_SIZE)
    frame_count = len(frame_starts)
    window = np.hanning(FRAME_SIZE).astype(np.float32)
    coherent_gain = float(np.sum(window))
    frequencies = np.fft.rfftfreq(FRAME_SIZE, 1.0 / sample_rate)
    f0_track = np.full(frame_count, expected_f0, dtype=np.float32)
    partial_frequency = np.zeros((frame_count, PARTIAL_COUNT), dtype=np.float32)
    partial_amplitude = np.zeros_like(partial_frequency)
    raw_phase = np.zeros_like(partial_frequency)

    previous_f0 = expected_f0
    for frame_index, start in enumerate(frame_starts):
        frame = padded[start : start + FRAME_SIZE]
        spectrum = np.fft.rfft(frame * window)
        magnitude = np.abs(spectrum)
        f0_candidates = np.flatnonzero(
            (frequencies >= expected_f0 * 0.965)
            & (frequencies <= expected_f0 * 1.035)
        )
        if len(f0_candidates):
            candidate = int(f0_candidates[np.argmax(magnitude[f0_candidates])])
            peak_bin = _quadratic_peak(magnitude, candidate)
            detected = peak_bin * sample_rate / FRAME_SIZE
            if abs(detected - previous_f0) <= expected_f0 * 0.025:
                previous_f0 = 0.72 * previous_f0 + 0.28 * detected
        f0_track[frame_index] = previous_f0

        median_magnitude = float(np.median(magnitude))
        for partial_index in range(PARTIAL_COUNT):
            harmonic = partial_index + 1
            predicted = previous_f0 * harmonic
            if predicted >= sample_rate * 0.49:
                continue
            radius = max(10.0, previous_f0 * min(0.20, 0.055 + harmonic * 0.003))
            candidates = np.flatnonzero(
                (frequencies >= predicted - radius)
                & (frequencies <= predicted + radius)
            )
            if not len(candidates):
                continue
            candidate = int(candidates[np.argmax(magnitude[candidates])])
            peak_bin = _quadratic_peak(magnitude, candidate)
            tracked_frequency = peak_bin * sample_rate / FRAME_SIZE
            coefficient = complex(spectrum[candidate])
            amplitude = 2.0 * abs(coefficient) / coherent_gain
            if float(magnitude[candidate]) < median_magnitude * 2.2:
                amplitude = 0.0
                tracked_frequency = predicted
            partial_frequency[frame_index, partial_index] = tracked_frequency
            partial_amplitude[frame_index, partial_index] = amplitude
            center_phase = (
                math.atan2(coefficient.imag, coefficient.real)
                + 2.0
                * math.pi
                * tracked_frequency
                * (FRAME_SIZE * 0.5)
                / sample_rate
            )
            raw_phase[frame_index, partial_index] = center_phase

    continuous_phase = np.zeros_like(raw_phase)
    for partial_index in range(PARTIAL_COUNT):
        continuous_phase[0, partial_index] = raw_phase[0, partial_index]
        for frame_index in range(1, frame_count):
            average_frequency = 0.5 * (
                partial_frequency[frame_index - 1, partial_index]
                + partial_frequency[frame_index, partial_index]
            )
            predicted_phase = (
                continuous_phase[frame_index - 1, partial_index]
                + 2.0 * math.pi * average_frequency * HOP_SIZE / sample_rate
            )
            measured = raw_phase[frame_index, partial_index]
            turns = round((predicted_phase - measured) / (2.0 * math.pi))
            aligned = measured + turns * 2.0 * math.pi
            continuous_phase[frame_index, partial_index] = (
                0.82 * predicted_phase + 0.18 * aligned
            )

    log_amplitude = np.log(np.maximum(partial_amplitude, 1.0e-8))
    formant = np.empty_like(partial_amplitude)
    for partial_index in range(PARTIAL_COUNT):
        left = max(0, partial_index - 2)
        right = min(PARTIAL_COUNT, partial_index + 3)
        formant[:, partial_index] = np.exp(
            np.mean(log_amplitude[:, left:right], axis=1)
        )

    return (
        f0_track,
        partial_frequency,
        partial_amplitude,
        continuous_phase,
        formant,
    )


def _resynthesize_spectral_model(
    original: np.ndarray,
    sample_rate: int,
    note: int,
    partial_frequency: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    padded = np.pad(original, (FRAME_SIZE // 2, FRAME_SIZE // 2))
    starts = np.arange(0, len(padded) - FRAME_SIZE + 1, HOP_SIZE)
    window = np.hanning(FRAME_SIZE).astype(np.float32)
    frequencies = np.fft.rfftfreq(FRAME_SIZE, 1.0 / sample_rate)
    edges = np.geomspace(35.0, sample_rate * 0.49, RESIDUAL_BAND_COUNT + 1)
    bands = np.zeros((len(starts), RESIDUAL_BAND_COUNT), dtype=np.float32)
    transient_frames = max(1, math.ceil(TRANSIENT_SECONDS * sample_rate / HOP_SIZE))
    transient_magnitude = np.zeros(
        (transient_frames, FRAME_SIZE // 2 + 1),
        dtype=np.float32,
    )
    transient_phase = np.zeros_like(transient_magnitude)
    generator = np.random.default_rng(0x52534944 + note * 613)
    residual_phase = generator.uniform(-math.pi, math.pi, len(frequencies))
    residual_phase_advance = (
        2.0 * math.pi * frequencies * HOP_SIZE / sample_rate
    )
    synthesized = np.zeros(len(padded), dtype=np.float32)
    normalization = np.zeros(len(padded), dtype=np.float32)

    for frame_index, start in enumerate(starts):
        frame = padded[start : start + FRAME_SIZE]
        spectrum = np.fft.rfft(frame * window)
        magnitude = np.abs(spectrum).astype(np.float32)
        for band_index in range(RESIDUAL_BAND_COUNT):
            mask = (frequencies >= edges[band_index]) & (
                frequencies < edges[band_index + 1]
            )
            if np.any(mask):
                bands[frame_index, band_index] = math.sqrt(
                    float(np.mean(np.square(magnitude[mask])))
                )
        if frame_index < transient_frames:
            transient_magnitude[frame_index] = magnitude
            transient_phase[frame_index] = np.angle(spectrum)
            modeled_spectrum = spectrum
            residual_phase = np.angle(spectrum)
        else:
            residual_phase += residual_phase_advance
            residual_phase += generator.normal(0.0, 0.006, len(spectrum))
            modeled_spectrum = magnitude * np.exp(1.0j * residual_phase)
            modeled_spectrum[0] = complex(float(magnitude[0]), 0.0)
            modeled_spectrum[-1] = complex(float(magnitude[-1]), 0.0)
            for tracked_frequency in partial_frequency[frame_index]:
                if tracked_frequency <= 0.0:
                    continue
                center = round(float(tracked_frequency) * FRAME_SIZE / sample_rate)
                left = max(1, center - 3)
                right = min(len(spectrum) - 1, center + 4)
                modeled_spectrum[left:right] = spectrum[left:right]
        modeled_frame = np.fft.irfft(modeled_spectrum, FRAME_SIZE).astype(np.float32)
        synthesized[start : start + FRAME_SIZE] += modeled_frame * window
        normalization[start : start + FRAME_SIZE] += window * window

    synthesized /= np.maximum(normalization, 1.0e-7)
    synthesized = synthesized[FRAME_SIZE // 2 : FRAME_SIZE // 2 + len(original)]
    return bands, transient_magnitude, transient_phase, synthesized


def _analyze_note(
    note: int,
    samples: np.ndarray,
    sample_rate: int,
) -> NoteAnalysis:
    (
        f0_hz,
        partial_frequency,
        partial_amplitude,
        partial_phase,
        formant,
    ) = _track_partials(samples, sample_rate, note)
    (
        residual_bands,
        transient_magnitude,
        transient_phase,
        reconstruction,
    ) = _resynthesize_spectral_model(
        samples,
        sample_rate,
        note,
        partial_frequency,
    )
    peak = float(np.max(np.abs(reconstruction), initial=0.0))
    if peak > 1.0:
        reconstruction /= peak

    harmonic_numbers = np.arange(1, PARTIAL_COUNT + 1, dtype=np.float32)
    ratio = partial_frequency / np.maximum(
        f0_hz[:, np.newaxis] * harmonic_numbers[np.newaxis, :],
        1.0e-6,
    )
    inharmonicity = np.median(
        (np.square(ratio[:, 1:]) - 1.0)
        / np.square(harmonic_numbers[np.newaxis, 1:]),
        axis=1,
    ).astype(np.float32)
    return NoteAnalysis(
        note=note,
        waveform=reconstruction,
        f0_hz=f0_hz,
        partial_frequency_hz=partial_frequency,
        partial_amplitude=partial_amplitude,
        partial_phase=partial_phase,
        formant_envelope=formant,
        residual_band_rms=residual_bands,
        inharmonicity=inharmonicity,
        transient_magnitude=transient_magnitude,
        transient_phase=transient_phase,
    )


def _pad_models(models: list[NoteAnalysis]) -> dict[str, np.ndarray]:
    max_frames = max(len(model.f0_hz) for model in models)
    max_transient_frames = max(len(model.transient_magnitude) for model in models)
    spectrum_bins = FRAME_SIZE // 2 + 1
    count = len(models)
    arrays = {
        "f0_hz": np.zeros((count, max_frames), dtype=np.float32),
        "partial_frequency_hz": np.zeros(
            (count, max_frames, PARTIAL_COUNT), dtype=np.float32
        ),
        "partial_amplitude": np.zeros(
            (count, max_frames, PARTIAL_COUNT), dtype=np.float32
        ),
        "partial_phase": np.zeros(
            (count, max_frames, PARTIAL_COUNT), dtype=np.float32
        ),
        "formant_envelope": np.zeros(
            (count, max_frames, PARTIAL_COUNT), dtype=np.float32
        ),
        "residual_band_rms": np.zeros(
            (count, max_frames, RESIDUAL_BAND_COUNT), dtype=np.float32
        ),
        "inharmonicity": np.zeros((count, max_frames), dtype=np.float32),
        "transient_magnitude": np.zeros(
            (count, max_transient_frames, spectrum_bins), dtype=np.float32
        ),
        "transient_phase": np.zeros(
            (count, max_transient_frames, spectrum_bins), dtype=np.float32
        ),
    }
    for index, model in enumerate(models):
        frame_count = len(model.f0_hz)
        transient_count = len(model.transient_magnitude)
        for name in (
            "f0_hz",
            "partial_frequency_hz",
            "partial_amplitude",
            "partial_phase",
            "formant_envelope",
            "residual_band_rms",
            "inharmonicity",
        ):
            arrays[name][index, :frame_count] = getattr(model, name)
        arrays["transient_magnitude"][index, :transient_count] = (
            model.transient_magnitude
        )
        arrays["transient_phase"][index, :transient_count] = model.transient_phase
    return arrays


def build_model(
    audio_path: Path,
    metadata_path: Path,
    model_path: Path,
    bank_path: Path,
    bank_metadata_path: Path,
) -> None:
    sample_rate, audio = _read_audio(audio_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    models = []
    for event in metadata["events"]:
        note = int(event["note"])
        samples = _extract_note(audio, sample_rate, event)
        model = _analyze_note(note, samples, sample_rate)
        models.append(model)
        print(
            f"note={note} seconds={len(samples) / sample_rate:.3f} "
            f"frames={len(model.f0_hz)}"
        )

    arrays = _pad_models(models)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        model_path,
        version=np.asarray([MODEL_VERSION], dtype=np.int32),
        sample_rate=np.asarray([sample_rate], dtype=np.int32),
        frame_size=np.asarray([FRAME_SIZE], dtype=np.int32),
        hop_size=np.asarray([HOP_SIZE], dtype=np.int32),
        notes=np.asarray([model.note for model in models], dtype=np.int16),
        frame_counts=np.asarray([len(model.f0_hz) for model in models], dtype=np.int32),
        transient_frame_counts=np.asarray(
            [len(model.transient_magnitude) for model in models], dtype=np.int16
        ),
        **arrays,
    )

    lengths = np.asarray([len(model.waveform) for model in models], dtype=np.int32)
    max_length = int(np.max(lengths))
    peak = max(float(np.max(np.abs(model.waveform), initial=0.0)) for model in models)
    scale = 0.92 / max(peak, 1.0e-9)
    bank = np.zeros((len(models), max_length), dtype=np.int16)
    for index, model in enumerate(models):
        normalized = np.clip(model.waveform * scale, -1.0, 1.0)
        bank[index, : len(normalized)] = np.rint(normalized * 32_767.0).astype(
            np.int16
        )
    np.save(bank_path, bank, allow_pickle=False)
    bank_metadata_path.write_text(
        json.dumps(
            {
                "version": MODEL_VERSION,
                "sample_rate": sample_rate,
                "notes": [model.note for model in models],
                "lengths": lengths.tolist(),
                "normalization_scale": scale,
                "analysis": {
                    "frame_size": FRAME_SIZE,
                    "hop_size": HOP_SIZE,
                    "partial_count": PARTIAL_COUNT,
                    "residual_band_count": RESIDUAL_BAND_COUNT,
                    "transient_seconds": TRANSIENT_SECONDS,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"model={model_path}")
    print(f"bank={bank_path}")
    print(f"bank_metadata={bank_metadata_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--bank", type=Path, required=True)
    parser.add_argument("--bank-metadata", type=Path, required=True)
    arguments = parser.parse_args()
    build_model(
        arguments.audio,
        arguments.metadata,
        arguments.model,
        arguments.bank,
        arguments.bank_metadata,
    )


if __name__ == "__main__":
    main()
