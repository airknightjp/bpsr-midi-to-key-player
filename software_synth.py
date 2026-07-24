from __future__ import annotations

import math
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from typing import Callable

import numpy as np
from PySide6.QtCore import (
    QCoreApplication,
    QMetaObject,
    QObject,
    QThread,
    QTimer,
    Qt,
    Slot,
)
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices

from audio_buffer import (
    AUDIO_BUFFER_FRAME_OPTIONS,
    DEFAULT_AUDIO_BUFFER_FRAMES,
    DEFAULT_QT_AUDIO_FRAMES,
    normalize_audio_buffer_frames,
)
from sound_sources import DEFAULT_SOUND_SOURCE, normalize_sound_source

SAMPLE_RATE = 44_100
WAVETABLE_SIZE = 2_048
MAX_VOICES = 64
MAX_FADING_VOICES = 16
RETRIGGER_RELEASE_SECONDS = 0.008
STOP_RELEASE_SECONDS = 0.015
LIMITER_THRESHOLD = 0.92
RENDER_CHUNK_FRAMES = 1_024
LOW_LATENCY_AUDIO_FRAMES = 256
PUSH_WRITE_FRAMES = 128
PUSH_TARGET_FRAMES = DEFAULT_QT_AUDIO_FRAMES
PUSH_PUMP_INTERVAL_MS = 1
COMMAND_DEEP_REFILL_GRACE_SECONDS = 0.020
NATURAL_DECAY_SILENCE_ENVELOPE = 0.0001
NATURAL_DECAY_REFERENCE_NOTE = 60
NATURAL_DECAY_PITCH_SPAN = 36.0
NATURAL_DECAY_MIN_SECONDS = 1.8
NATURAL_DECAY_MAX_SECONDS = 8.0
COMMAND_NOTE_ON = 1
COMMAND_NOTE_OFF = 2
COMMAND_SUSTAIN = 3
COMMAND_RELEASE_ALL = 4
AUDIO_METRICS_RETENTION_SECONDS = 130.0
AUDIO_SHORTAGE_DEBOUNCE_SECONDS = 0.05
AUTO_BUFFER_SHORTAGE_WINDOW_SECONDS = 5.0
AUTO_BUFFER_SHORTAGE_THRESHOLD = 3
AUTO_BUFFER_STABILIZATION_SECONDS = 20.0
AUTO_BUFFER_DOWNSHIFT_STABLE_SECONDS = 20.0
AUTO_BUFFER_DOWNSHIFT_MAX_UTILIZATION = 0.25
AUTO_BUFFER_DOWNSHIFT_BLOCK_SECONDS = 60.0


@dataclass(frozen=True)
class Timbre:
    harmonics: tuple[float, ...]
    attack: float
    decay: float
    sustain: float
    release: float
    held_decay: float | None = None


TIMBRES = {
    "piano": Timbre(
        (1.0, 0.58, 0.34, 0.19, 0.11, 0.07),
        0.004,
        0.55,
        0.10,
        0.48,
        held_decay=3.6,
    ),
    "electric_piano": Timbre((1.0, 0.18, 0.30, 0.08, 0.05), 0.008, 1.05, 0.24, 0.62),
    "organ": Timbre((1.0, 0.48, 0.26, 0.14, 0.08), 0.018, 0.10, 0.82, 0.16),
    "synth": Timbre((1.0, 0.50, 0.33, 0.25, 0.20, 0.16, 0.14), 0.010, 0.22, 0.62, 0.34),
}


def _build_wavetable(harmonics: tuple[float, ...]) -> np.ndarray:
    phases = 2.0 * math.pi * np.arange(WAVETABLE_SIZE, dtype=np.float32) / WAVETABLE_SIZE
    samples = np.zeros(WAVETABLE_SIZE, dtype=np.float32)
    for harmonic, amplitude in enumerate(harmonics, start=1):
        samples += amplitude * np.sin(phases * harmonic)
    peak = float(np.max(np.abs(samples))) or 1.0
    samples /= peak
    return samples


WAVETABLES = {
    source: _build_wavetable(timbre.harmonics)
    for source, timbre in TIMBRES.items()
}
SOUND_SOURCE_INDEX = {source: index for index, source in enumerate(WAVETABLES)}
WAVETABLE_MATRIX = np.ascontiguousarray(
    np.stack(tuple(WAVETABLES.values())),
    dtype=np.float32,
)
WAVETABLE_FLAT = WAVETABLE_MATRIX.reshape(-1)


@dataclass
class Voice:
    client_id: int
    channel: int
    note: int
    source: str
    phase: float
    phase_step: float
    amplitude: float
    envelope: float = 0.0
    stage: str = "attack"
    release_step: float = 0.0
    key_released: bool = False
    started_order: int = 0


@dataclass
class SynthRenderState:
    voices: dict[tuple[int, int, int], Voice]
    fading_voices: list[Voice]
    sustain: set[tuple[int, int]]
    voice_order: int
    mix_gain: float
    pending_commands: deque[
        tuple[float, int, tuple[object, ...]]
    ]
    command_origin_time: float | None
    command_rendered_frames: int


@dataclass(frozen=True)
class AudioSupplyMetrics:
    shortages: tuple[float, ...]
    synthesis_utilization: tuple[tuple[float, float], ...]
    synthesis_durations: tuple[tuple[float, float], ...] = ()
    supply_delays: tuple[float, ...] = ()
    ring_buffer_bytes: int = 0
    ring_target_bytes: int = 0


@dataclass(frozen=True)
class AudioBufferDecision:
    frames: int
    reason: str


class AudioBufferAutoPolicy:
    """Selects a stable buffer size from measured audio-supply pressure."""

    def __init__(self, now: float | None = None) -> None:
        started_at = time.monotonic() if now is None else float(now)
        self.enabled_at = started_at
        self.last_change_at = float("-inf")
        self.last_shortage_at = started_at
        self.downshift_at: float | None = None
        self.downshift_restore_frames: int | None = None
        self.downshift_block_until = float("-inf")

    def reset(self, now: float | None = None) -> None:
        started_at = time.monotonic() if now is None else float(now)
        self.enabled_at = started_at
        self.last_change_at = float("-inf")
        self.last_shortage_at = started_at
        self.downshift_at = None
        self.downshift_restore_frames = None
        self.downshift_block_until = float("-inf")

    def evaluate(
        self,
        now: float,
        current_frames: int,
        metrics: AudioSupplyMetrics,
        minimum_frames: int = AUDIO_BUFFER_FRAME_OPTIONS[0],
    ) -> AudioBufferDecision | None:
        now = float(now)
        current_frames = normalize_audio_buffer_frames(current_frames)
        minimum_frames = min(
            (
                frames
                for frames in AUDIO_BUFFER_FRAME_OPTIONS
                if frames >= max(1, int(minimum_frames))
            ),
            default=AUDIO_BUFFER_FRAME_OPTIONS[-1],
        )
        recent_shortages = tuple(
            timestamp
            for timestamp in metrics.shortages
            if timestamp >= self.enabled_at
        )
        recent_supply_delays = tuple(
            timestamp
            for timestamp in metrics.supply_delays
            if timestamp >= self.enabled_at
        )
        recent_pressure = tuple(
            sorted(recent_shortages + recent_supply_delays)
        )
        if recent_pressure:
            self.last_shortage_at = max(
                self.last_shortage_at,
                recent_pressure[-1],
            )

        if (
            self.downshift_at is not None
            and self.downshift_restore_frames is not None
            and any(timestamp >= self.downshift_at for timestamp in recent_pressure)
        ):
            restore_frames = self.downshift_restore_frames
            self.last_change_at = now
            self.downshift_at = None
            self.downshift_restore_frames = None
            self.downshift_block_until = now + AUTO_BUFFER_DOWNSHIFT_BLOCK_SECONDS
            return AudioBufferDecision(
                restore_frames,
                (
                    f"Audio buffer automatically restored: {current_frames} -> "
                    f"{restore_frames} (supply shortage after reduction)"
                ),
            )

        if (
            self.downshift_at is not None
            and now - self.downshift_at >= AUTO_BUFFER_STABILIZATION_SECONDS
        ):
            self.downshift_at = None
            self.downshift_restore_frames = None

        if now - self.last_change_at < AUTO_BUFFER_STABILIZATION_SECONDS:
            return None

        shortage_cutoff = now - AUTO_BUFFER_SHORTAGE_WINDOW_SECONDS
        shortage_count = sum(
            timestamp >= shortage_cutoff
            for timestamp in recent_shortages
        )
        supply_delay_count = sum(
            timestamp >= shortage_cutoff
            for timestamp in recent_supply_delays
        )
        pressure_count = max(shortage_count, supply_delay_count)
        current_index = AUDIO_BUFFER_FRAME_OPTIONS.index(current_frames)
        if (
            pressure_count >= AUTO_BUFFER_SHORTAGE_THRESHOLD
            and current_index < len(AUDIO_BUFFER_FRAME_OPTIONS) - 1
        ):
            next_frames = AUDIO_BUFFER_FRAME_OPTIONS[current_index + 1]
            self.last_change_at = now
            self.downshift_at = None
            self.downshift_restore_frames = None
            return AudioBufferDecision(
                next_frames,
                (
                    f"Audio buffer automatically increased: {current_frames} -> "
                    f"{next_frames} ({shortage_count} shortages, "
                    f"{supply_delay_count} synthesis delays in 5s)"
                ),
            )

        stable_since = max(
            self.enabled_at,
            self.last_change_at,
            self.last_shortage_at,
        )
        if (
            current_frames <= minimum_frames
            or now < self.downshift_block_until
            or now - stable_since < AUTO_BUFFER_DOWNSHIFT_STABLE_SECONDS
        ):
            return None
        utilization_cutoff = now - AUTO_BUFFER_DOWNSHIFT_STABLE_SECONDS
        utilization = [
            value
            for timestamp, value in metrics.synthesis_utilization
            if timestamp >= utilization_cutoff
        ]
        if not utilization:
            return None
        ordered = sorted(utilization)
        percentile_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
        percentile_95 = ordered[percentile_index]
        if percentile_95 >= AUTO_BUFFER_DOWNSHIFT_MAX_UTILIZATION:
            return None
        next_frames = max(
            minimum_frames,
            AUDIO_BUFFER_FRAME_OPTIONS[current_index - 1],
        )
        self.last_change_at = now
        self.downshift_at = now
        self.downshift_restore_frames = current_frames
        return AudioBufferDecision(
            next_frames,
            (
                f"Audio buffer automatically reduced: {current_frames} -> "
                f"{next_frames} ({AUTO_BUFFER_DOWNSHIFT_STABLE_SECONDS:.0f}s "
                f"stable, synthesis p95 "
                f"{percentile_95 * 100:.1f}% of deadline)"
            ),
        )


class SoftwareSynthStream:
    """PCM producer shared by MIDI playback and realtime preview."""

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        channels: int = 2,
        buffer_frames: int = DEFAULT_AUDIO_BUFFER_FRAMES,
        time_source: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.sample_rate = max(8_000, int(sample_rate))
        self.channels = max(1, int(channels))
        self.buffer_frames = normalize_audio_buffer_frames(buffer_frames)
        self.sample_format = QAudioFormat.SampleFormat.Int16
        self._voices: dict[tuple[int, int, int], Voice] = {}
        self._fading_voices: list[Voice] = []
        self._sustain: set[tuple[int, int]] = set()
        self._time_source = time_source
        self._commands: queue.SimpleQueue[
            tuple[float, int, tuple[object, ...]]
        ] = queue.SimpleQueue()
        self._pending_commands: deque[
            tuple[float, int, tuple[object, ...]]
        ] = deque()
        self._command_origin_time: float | None = None
        self._command_rendered_frames = 0
        self._command_revision = 0
        self._rendered_command_revision = 0
        self._voice_order = 0
        self._mix_gain = 0.30
        render_voice_capacity = MAX_VOICES + MAX_FADING_VOICES
        render_shape = (render_voice_capacity, RENDER_CHUNK_FRAMES)
        self._render_voices: list[Voice | None] = [None] * render_voice_capacity
        self._render_keys: list[tuple[int, int, int] | None] = [
            None
        ] * render_voice_capacity
        self._active_render_voice_count = 0
        self._frame_offsets = np.arange(RENDER_CHUNK_FRAMES, dtype=np.float32)
        self._envelope_offsets = self._frame_offsets + 1.0
        self._phase_scratch = np.empty(render_shape, dtype=np.float32)
        self._index_scratch = np.empty(render_shape, dtype=np.intp)
        self._envelope_scratch = np.empty(render_shape, dtype=np.float32)
        self._sample_scratch = np.empty(render_shape, dtype=np.float32)
        self._phase_values = np.empty(render_voice_capacity, dtype=np.float32)
        self._phase_steps = np.empty(render_voice_capacity, dtype=np.float32)
        self._amplitudes = np.empty(render_voice_capacity, dtype=np.float32)
        self._source_offsets = np.empty(render_voice_capacity, dtype=np.intp)
        self._rendered_frames = np.empty(render_voice_capacity, dtype=np.intp)
        self._mix_scratch = np.empty(RENDER_CHUNK_FRAMES, dtype=np.float32)
        # Buffer size can change while the worker is rendering.  Reserve the
        # largest selectable workspace up front so a live switch never
        # reallocates audio buffers on the render path.
        initial_frames = max(
            RENDER_CHUNK_FRAMES,
            max(AUDIO_BUFFER_FRAME_OPTIONS),
        )
        self._gain_scratch = np.empty(initial_frames, dtype=np.float32)
        self._limiter_magnitude_scratch = np.empty(initial_frames, dtype=np.float32)
        self._limiter_excess_scratch = np.empty(initial_frames, dtype=np.float32)
        self._output_scratch = np.empty(initial_frames, dtype=np.float32)
        initial_samples = initial_frames * self.channels
        self._interleaved_scratch = np.empty(initial_samples, dtype=np.float32)
        self._pcm_int16_scratch = np.empty(initial_samples, dtype=np.int16)
        self._pcm_int32_scratch = np.empty(initial_samples, dtype=np.int32)
        self._ring_condition = threading.Condition()
        self._pcm_ring: deque[bytes] = deque()
        self._pcm_ring_states: deque[SynthRenderState] = deque()
        self._pcm_ring_offset = 0
        self._pcm_ring_bytes = 0
        self._worker_active = False
        self._worker_primed = False
        self._worker_stop = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._last_command_monotonic = float("-inf")
        self._metrics_lock = threading.Lock()
        self._shortage_timestamps: deque[float] = deque()
        self._synthesis_utilization: deque[tuple[float, float]] = deque()
        self._synthesis_durations: deque[tuple[float, float]] = deque()
        self._supply_delay_timestamps: deque[float] = deque()
        self._last_shortage_at = float("-inf")
        self._last_supply_delay_at = float("-inf")

    def configure(
        self,
        sample_rate: int,
        channels: int,
        sample_format: QAudioFormat.SampleFormat,
        buffer_frames: int,
    ) -> None:
        self.sample_rate = max(8_000, int(sample_rate))
        self.channels = max(1, int(channels))
        self.sample_format = sample_format
        self.buffer_frames = normalize_audio_buffer_frames(buffer_frames)
        initial_frames = max(RENDER_CHUNK_FRAMES, self.buffer_frames)
        self._ensure_output_capacity(initial_frames)
        self._ensure_pcm_capacity(initial_frames * self.channels)

    def set_buffer_frames_live(self, buffer_frames: int) -> None:
        """Change synthesis chunking without touching the running Qt sink."""
        with self._ring_condition:
            self.buffer_frames = normalize_audio_buffer_frames(buffer_frames)
            self._ring_condition.notify_all()

    def start_worker(self, timeout: float = 1.0) -> bool:
        with self._ring_condition:
            if self._worker_active:
                return self._worker_primed
            self._pcm_ring.clear()
            self._pcm_ring_states.clear()
            self._pcm_ring_offset = 0
            self._pcm_ring_bytes = 0
            self._worker_primed = False
            self._worker_stop.clear()
            self._worker_active = True
            worker = threading.Thread(
                target=self._audio_worker_loop,
                name="SoftwareSynthWorker",
                daemon=True,
            )
            self._worker_thread = worker
            worker.start()
            deadline = time.monotonic() + max(0.0, float(timeout))
            while (
                self._worker_active
                and not self._worker_primed
                and not self._worker_stop.is_set()
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    break
                self._ring_condition.wait(remaining)
            return self._worker_primed

    def stop_worker(self) -> None:
        with self._ring_condition:
            worker = self._worker_thread
            self._worker_active = False
            self._worker_stop.set()
            self._ring_condition.notify_all()
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=1.0)
        with self._ring_condition:
            if self._worker_thread is worker:
                self._worker_thread = None
            self._pcm_ring.clear()
            self._pcm_ring_states.clear()
            self._pcm_ring_offset = 0
            self._pcm_ring_bytes = 0
            self._worker_primed = False

    def close(self) -> None:
        self.stop_worker()

    def take_pcm_frames(
        self,
        frame_count: int,
        *,
        pad_silence: bool = True,
    ) -> bytes:
        frame_count = max(0, int(frame_count))
        frame_size = self._frame_size()
        if self._worker_active:
            return self._read_pcm_ring(
                frame_count * frame_size,
                pad_silence=pad_silence,
            )
        return self._render_pcm_bytes(frame_count)

    def _render_pcm_bytes(
        self,
        frame_count: int,
        *,
        collect_commands: bool = True,
    ) -> bytes:
        mono = self._render_array(
            frame_count,
            collect_commands=collect_commands,
        )
        sample_count = frame_count * self.channels
        self._ensure_pcm_capacity(sample_count)
        interleaved = self._interleaved_scratch[:sample_count]
        if frame_count:
            interleaved.reshape(frame_count, self.channels)[:] = mono[:, np.newaxis]
        if self.sample_format == QAudioFormat.SampleFormat.Float:
            return interleaved.tobytes()
        if self.sample_format == QAudioFormat.SampleFormat.Int32:
            # 2_147_483_647 rounds up in float32 and can overflow to INT32_MIN.
            interleaved *= 2_147_483_520.0
            np.rint(interleaved, out=interleaved)
            np.copyto(
                self._pcm_int32_scratch[:sample_count],
                interleaved,
                casting="unsafe",
            )
            return self._pcm_int32_scratch[:sample_count].tobytes()
        interleaved *= 32_767.0
        np.rint(interleaved, out=interleaved)
        np.copyto(
            self._pcm_int16_scratch[:sample_count],
            interleaved,
            casting="unsafe",
        )
        return self._pcm_int16_scratch[:sample_count].tobytes()

    def _audio_worker_loop(self) -> None:
        while not self._worker_stop.is_set():
            refreshed_pcm = False
            with self._ring_condition:
                target_bytes = self._target_ring_bytes()
                while (
                    self._worker_active
                    and self._pcm_ring_bytes >= target_bytes
                    and self._rendered_command_revision
                    == self._command_revision
                    and not self._worker_stop.is_set()
                ):
                    self._ring_condition.wait(0.1)
                if not self._worker_active or self._worker_stop.is_set():
                    break
                command_revision = self._command_revision
                refresh_pending_audio = (
                    self._rendered_command_revision != command_revision
                )
                if refresh_pending_audio and self._pcm_ring:
                    if self._pcm_ring_offset:
                        self._ring_condition.wait(0.002)
                        continue
                    if self._pcm_ring_states:
                        self._restore_render_state(self._pcm_ring_states[0])
                    frame_size = self._frame_size()
                    frame_count = min(
                        max(
                            1,
                            (
                                target_bytes
                                + frame_size
                                - 1
                            )
                            // frame_size,
                        ),
                        LOW_LATENCY_AUDIO_FRAMES,
                    )
                    self._apply_worker_commands_through(command_revision)
                    render_state = self._capture_render_state()
                    started_at = time.perf_counter()
                    try:
                        pcm = self._render_pcm_bytes(
                            frame_count,
                            collect_commands=False,
                        )
                    except Exception:
                        self._restore_render_state(render_state)
                        pcm = bytes(frame_count * frame_size)
                        self._record_supply_shortage()
                    elapsed = max(
                        0.0,
                        time.perf_counter() - started_at,
                    )
                    self._pcm_ring.clear()
                    self._pcm_ring_states.clear()
                    self._pcm_ring_offset = 0
                    self._pcm_ring.append(pcm)
                    self._pcm_ring_states.append(render_state)
                    self._pcm_ring_bytes = len(pcm)
                    self._rendered_command_revision = command_revision
                    self._worker_primed = True
                    self._ring_condition.notify_all()
                    refreshed_pcm = True
                    refresh_deadline = (
                        frame_count / max(1, self.sample_rate)
                    )
                if refreshed_pcm:
                    frame_count = 0
                else:
                    frame_size = self._frame_size()
                    immediate_bytes = PUSH_TARGET_FRAMES * frame_size
                    deep_refill_delay = (
                        self._last_command_monotonic
                        + COMMAND_DEEP_REFILL_GRACE_SECONDS
                        - time.monotonic()
                    )
                    if (
                        not refresh_pending_audio
                        and self._pcm_ring_bytes >= immediate_bytes
                        and self._pcm_ring_bytes < target_bytes
                        and deep_refill_delay > 0.0
                    ):
                        self._ring_condition.wait(deep_refill_delay)
                        continue
                    missing_bytes = max(
                        frame_size,
                        target_bytes - self._pcm_ring_bytes,
                    )
                    missing_frames = (
                        missing_bytes + frame_size - 1
                    ) // frame_size
                    frame_count = min(
                        missing_frames,
                        LOW_LATENCY_AUDIO_FRAMES,
                    )
            if refreshed_pcm:
                self._record_synthesis_utilization(
                    (
                        elapsed / refresh_deadline
                        if refresh_deadline > 0.0
                        else 0.0
                    ),
                    elapsed,
                )
                continue
            self._apply_worker_commands_through(command_revision)
            render_state = self._capture_render_state()
            started_at = time.perf_counter()
            try:
                pcm = self._render_pcm_bytes(
                    frame_count,
                    collect_commands=False,
                )
            except Exception:
                self._restore_render_state(render_state)
                pcm = bytes(frame_count * self._frame_size())
                self._record_supply_shortage()
            elapsed = max(0.0, time.perf_counter() - started_at)
            deadline = frame_count / max(1, self.sample_rate)
            self._record_synthesis_utilization(
                elapsed / deadline if deadline > 0.0 else 0.0,
                elapsed,
            )
            with self._ring_condition:
                if not self._worker_active or self._worker_stop.is_set():
                    break
                if command_revision != self._command_revision:
                    self._restore_render_state(render_state)
                    continue
                self._pcm_ring.append(pcm)
                self._pcm_ring_states.append(render_state)
                self._pcm_ring_bytes += len(pcm)
                self._rendered_command_revision = command_revision
                if self._pcm_ring_bytes >= self._target_ring_bytes():
                    self._worker_primed = True
                self._ring_condition.notify_all()
        with self._ring_condition:
            self._ring_condition.notify_all()

    def _read_pcm_ring(
        self,
        byte_count: int,
        *,
        pad_silence: bool = True,
    ) -> bytes:
        byte_count = max(0, int(byte_count))
        if byte_count == 0:
            return b""
        remaining = byte_count
        with self._ring_condition:
            if (
                self._pcm_ring_offset == 0
                and self._pcm_ring
                and len(self._pcm_ring[0]) == byte_count
            ):
                pcm = self._pcm_ring.popleft()
                if self._pcm_ring_states:
                    self._pcm_ring_states.popleft()
                self._pcm_ring_bytes -= byte_count
                self._ring_condition.notify_all()
                return pcm
            chunks: list[bytes] = []
            while remaining > 0 and self._pcm_ring:
                chunk = self._pcm_ring[0]
                available = len(chunk) - self._pcm_ring_offset
                take = min(remaining, available)
                start = self._pcm_ring_offset
                end = start + take
                if start == 0 and take == len(chunk):
                    chunks.append(chunk)
                else:
                    chunks.append(chunk[start:end])
                remaining -= take
                self._pcm_ring_bytes -= take
                if take == available:
                    self._pcm_ring.popleft()
                    if self._pcm_ring_states:
                        self._pcm_ring_states.popleft()
                    self._pcm_ring_offset = 0
                else:
                    self._pcm_ring_offset = end
            primed = self._worker_primed
            self._ring_condition.notify_all()
        if remaining and pad_silence:
            chunks.append(bytes(remaining))
            if primed:
                self._record_supply_shortage()
        if len(chunks) == 1:
            return chunks[0]
        return b"".join(chunks)

    def _target_ring_bytes(self) -> int:
        return self.buffer_frames * self._frame_size()

    def _frame_size(self) -> int:
        return self.channels * self._bytes_per_sample()

    def _bytes_per_sample(self) -> int:
        if self.sample_format in {
            QAudioFormat.SampleFormat.Float,
            QAudioFormat.SampleFormat.Int32,
        }:
            return 4
        return 2

    def minimum_effective_buffer_frames(self) -> int:
        return DEFAULT_AUDIO_BUFFER_FRAMES

    def _record_supply_shortage(self) -> None:
        now = time.monotonic()
        with self._metrics_lock:
            if now - self._last_shortage_at < AUDIO_SHORTAGE_DEBOUNCE_SECONDS:
                return
            self._last_shortage_at = now
            self._shortage_timestamps.append(now)
            self._prune_metrics_locked(now)

    def _record_synthesis_utilization(
        self,
        utilization: float,
        duration_seconds: float | None = None,
    ) -> None:
        now = time.monotonic()
        with self._metrics_lock:
            utilization = max(0.0, float(utilization))
            self._synthesis_utilization.append((now, utilization))
            if duration_seconds is not None:
                self._synthesis_durations.append(
                    (now, max(0.0, float(duration_seconds)))
                )
            if (
                utilization >= 1.0
                and now - self._last_supply_delay_at
                >= AUDIO_SHORTAGE_DEBOUNCE_SECONDS
            ):
                self._last_supply_delay_at = now
                self._supply_delay_timestamps.append(now)
            self._prune_metrics_locked(now)

    def metrics_snapshot(self) -> AudioSupplyMetrics:
        now = time.monotonic()
        with self._ring_condition:
            ring_buffer_bytes = self._pcm_ring_bytes
            ring_target_bytes = self._target_ring_bytes()
        with self._metrics_lock:
            self._prune_metrics_locked(now)
            return AudioSupplyMetrics(
                shortages=tuple(self._shortage_timestamps),
                synthesis_utilization=tuple(self._synthesis_utilization),
                synthesis_durations=tuple(self._synthesis_durations),
                supply_delays=tuple(self._supply_delay_timestamps),
                ring_buffer_bytes=ring_buffer_bytes,
                ring_target_bytes=ring_target_bytes,
            )

    def clear_metrics(self) -> None:
        with self._metrics_lock:
            self._shortage_timestamps.clear()
            self._synthesis_utilization.clear()
            self._synthesis_durations.clear()
            self._supply_delay_timestamps.clear()
            self._last_shortage_at = float("-inf")
            self._last_supply_delay_at = float("-inf")

    def _prune_metrics_locked(self, now: float) -> None:
        cutoff = now - AUDIO_METRICS_RETENTION_SECONDS
        while self._shortage_timestamps and self._shortage_timestamps[0] < cutoff:
            self._shortage_timestamps.popleft()
        while (
            self._synthesis_utilization
            and self._synthesis_utilization[0][0] < cutoff
        ):
            self._synthesis_utilization.popleft()
        while (
            self._synthesis_durations
            and self._synthesis_durations[0][0] < cutoff
        ):
            self._synthesis_durations.popleft()
        while (
            self._supply_delay_timestamps
            and self._supply_delay_timestamps[0] < cutoff
        ):
            self._supply_delay_timestamps.popleft()

    def note_on(self, client_id: int, channel: int, note: int, velocity: int, source: str) -> None:
        source = normalize_sound_source(source)
        note = max(0, min(127, int(note)))
        velocity = max(1, min(127, int(velocity)))
        frequency = 440.0 * (2.0 ** ((note - 69) / 12.0))
        self._queue_command(
            (
                COMMAND_NOTE_ON,
                int(client_id),
                int(channel),
                note,
                source,
                frequency * WAVETABLE_SIZE / self.sample_rate,
                (velocity / 127.0) ** 0.72,
            )
        )

    def note_off(self, client_id: int, channel: int, note: int) -> None:
        self._queue_command(
            (COMMAND_NOTE_OFF, int(client_id), int(channel), int(note))
        )

    def set_sustain(self, client_id: int, channel: int, enabled: bool) -> None:
        self._queue_command(
            (COMMAND_SUSTAIN, int(client_id), int(channel), bool(enabled))
        )

    def release_all(
        self,
        client_id: int,
        channel: int | None = None,
        *,
        immediate: bool = False,
        release_seconds: float | None = None,
    ) -> None:
        self._queue_command(
            (
                COMMAND_RELEASE_ALL,
                int(client_id),
                None if channel is None else int(channel),
                bool(immediate),
                release_seconds,
            )
        )

    def _queue_command(self, command: tuple[object, ...]) -> None:
        with self._ring_condition:
            self._command_revision += 1
            self._last_command_monotonic = time.monotonic()
            self._commands.put(
                (
                    self._time_source(),
                    self._command_revision,
                    command,
                )
            )
            self._ring_condition.notify_all()

    def _collect_commands(self) -> None:
        while not self._commands.empty():
            self._pending_commands.append(self._commands.get_nowait())

    def _apply_worker_commands_through(self, revision: int) -> None:
        self._collect_commands()
        commands: list[tuple[object, ...]] = []
        while (
            self._pending_commands
            and self._pending_commands[0][1] <= revision
        ):
            _queued_at, _revision, command = self._pending_commands.popleft()
            commands.append(command)
        self._apply_command_batch(commands)
        self._reset_command_timeline()

    def _capture_render_state(self) -> SynthRenderState:
        return SynthRenderState(
            voices={
                key: replace(voice)
                for key, voice in self._voices.items()
            },
            fading_voices=[
                replace(voice)
                for voice in self._fading_voices
            ],
            sustain=set(self._sustain),
            voice_order=self._voice_order,
            mix_gain=self._mix_gain,
            pending_commands=deque(self._pending_commands),
            command_origin_time=self._command_origin_time,
            command_rendered_frames=self._command_rendered_frames,
        )

    def _restore_render_state(self, state: SynthRenderState) -> None:
        self._voices = {
            key: replace(voice)
            for key, voice in state.voices.items()
        }
        self._fading_voices = [
            replace(voice)
            for voice in state.fading_voices
        ]
        self._sustain = set(state.sustain)
        self._voice_order = state.voice_order
        self._mix_gain = state.mix_gain
        self._pending_commands = deque(state.pending_commands)
        self._command_origin_time = state.command_origin_time
        self._command_rendered_frames = state.command_rendered_frames

    def _apply_command(self, command: tuple[object, ...]) -> None:
        command_type = int(command[0])
        if command_type == COMMAND_NOTE_ON:
            self._apply_note_on(command)
        elif command_type == COMMAND_NOTE_OFF:
            self._apply_note_off(command)
        elif command_type == COMMAND_SUSTAIN:
            self._apply_sustain(command)
        elif command_type == COMMAND_RELEASE_ALL:
            self._apply_release_all(command)

    def _apply_note_on(self, command: tuple[object, ...]) -> None:
        client_id = int(command[1])
        channel = int(command[2])
        note = int(command[3])
        source = str(command[4])
        phase_step = float(command[5])
        amplitude = float(command[6])
        self._voice_order += 1
        key = (client_id, channel, note)
        previous = self._voices.pop(key, None)
        if previous is not None:
            previous.key_released = True
            self._begin_release(
                previous,
                release_seconds=RETRIGGER_RELEASE_SECONDS,
            )
            self._fading_voices.append(previous)
        self._voices[key] = Voice(
            client_id=client_id,
            channel=channel,
            note=note,
            source=source,
            phase=0.0,
            phase_step=phase_step,
            amplitude=amplitude,
            started_order=self._voice_order,
        )
        self._trim_voices()
        self._trim_fading_voices()

    def _apply_note_off(self, command: tuple[object, ...]) -> None:
        client_id = int(command[1])
        channel = int(command[2])
        note = int(command[3])
        voice = self._voices.get((client_id, channel, note))
        if voice is None:
            return
        voice.key_released = True
        if (client_id, channel) not in self._sustain:
            self._begin_release(voice)

    def _apply_sustain(self, command: tuple[object, ...]) -> None:
        sustain_key = (int(command[1]), int(command[2]))
        if bool(command[3]):
            self._sustain.add(sustain_key)
            return
        self._sustain.discard(sustain_key)
        for voice in self._voices.values():
            if (
                voice.client_id == sustain_key[0]
                and voice.channel == sustain_key[1]
                and voice.key_released
            ):
                self._begin_release(voice)

    def _apply_release_all(self, command: tuple[object, ...]) -> None:
        client_id = int(command[1])
        channel = command[2]
        immediate = bool(command[3])
        release_seconds = command[4]
        for sustain_key in tuple(self._sustain):
            if sustain_key[0] == client_id and (
                channel is None or sustain_key[1] == channel
            ):
                self._sustain.discard(sustain_key)
        for key, voice in tuple(self._voices.items()):
            if voice.client_id != client_id or (
                channel is not None and voice.channel != channel
            ):
                continue
            if immediate:
                self._voices.pop(key, None)
            else:
                voice.key_released = True
                self._begin_release(
                    voice,
                    release_seconds=None
                    if release_seconds is None
                    else float(release_seconds),
                )
        write_index = 0
        for voice in self._fading_voices:
            matches = voice.client_id == client_id and (
                channel is None or voice.channel == channel
            )
            if matches and immediate:
                continue
            if matches and release_seconds is not None:
                self._begin_release(
                    voice,
                    release_seconds=float(release_seconds),
                )
            self._fading_voices[write_index] = voice
            write_index += 1
        del self._fading_voices[write_index:]

    def render(self, frame_count: int) -> list[float]:
        return self._render_array(frame_count).tolist()

    def _render_array(
        self,
        frame_count: int,
        *,
        collect_commands: bool = True,
    ) -> np.ndarray:
        frame_count = max(0, int(frame_count))
        if collect_commands:
            self._collect_commands()
        if frame_count == 0:
            while self._pending_commands:
                _queued_at, _revision, command = (
                    self._pending_commands.popleft()
                )
                self._apply_command(command)
            self._reset_command_timeline()
            return self._output_scratch[:0]
        self._ensure_output_capacity(frame_count)
        output = self._output_scratch[:frame_count]
        output_cursor = 0
        if self._pending_commands and self._command_origin_time is None:
            self._command_origin_time = self._pending_commands[0][0]
            self._command_rendered_frames = 0

        while self._pending_commands:
            queued_at, _revision, _command = self._pending_commands[0]
            origin = self._command_origin_time
            if origin is None:
                origin = queued_at
                self._command_origin_time = origin
            target_frame = max(
                0,
                round((queued_at - origin) * self.sample_rate),
            )
            command_offset = max(
                output_cursor,
                target_frame - self._command_rendered_frames,
            )
            if command_offset >= frame_count:
                break
            self._render_audio_into(output[output_cursor:command_offset])
            output_cursor = command_offset
            commands: list[tuple[object, ...]] = []
            while self._pending_commands:
                candidate_at, _candidate_revision, candidate = (
                    self._pending_commands[0]
                )
                candidate_target = max(
                    0,
                    round((candidate_at - origin) * self.sample_rate),
                )
                candidate_offset = max(
                    output_cursor,
                    candidate_target - self._command_rendered_frames,
                )
                if candidate_offset != command_offset:
                    break
                self._pending_commands.popleft()
                commands.append(candidate)
            self._apply_command_batch(commands)

        self._render_audio_into(output[output_cursor:])
        if self._pending_commands:
            self._command_rendered_frames += frame_count
        else:
            self._reset_command_timeline()
        return output

    def _apply_command_batch(
        self,
        commands: list[tuple[object, ...]],
    ) -> None:
        for command in commands:
            self._apply_command(command)

    def _reset_command_timeline(self) -> None:
        self._command_origin_time = None
        self._command_rendered_frames = 0

    def _render_audio_into(self, output: np.ndarray) -> None:
        frame_count = len(output)
        if frame_count == 0:
            return
        voice_count = self._collect_render_voices()
        if voice_count == 0:
            self._mix_gain = 0.30
            output.fill(0.0)
            return
        target_gain = 0.30 / math.sqrt(max(1.0, voice_count / 2.0))
        for chunk_start in range(0, frame_count, RENDER_CHUNK_FRAMES):
            chunk_frames = min(RENDER_CHUNK_FRAMES, frame_count - chunk_start)
            output[chunk_start : chunk_start + chunk_frames] = self._render_voice_chunk(
                voice_count,
                chunk_frames,
            )
        self._remove_finished_voices(
            self._active_render_voice_count,
            voice_count,
        )
        gain = self._mix_gain
        ramp_frames = min(frame_count, max(1, round(self.sample_rate * 0.01)))
        self._ensure_gain_capacity(ramp_frames)
        gain_step = (target_gain - gain) / ramp_frames
        ramp_gain = self._gain_scratch[:ramp_frames]
        np.multiply(
            self._envelope_offsets[:ramp_frames],
            gain_step,
            out=ramp_gain,
        )
        ramp_gain += gain
        output[:ramp_frames] *= ramp_gain
        output[ramp_frames:] *= target_gain
        self._soft_limit_array(output)
        self._mix_gain = target_gain

    def _render_voice_chunk(
        self,
        voice_count: int,
        frame_count: int,
    ) -> np.ndarray:
        envelope = self._envelope_scratch[:voice_count, :frame_count]
        for index in range(voice_count):
            voice = self._render_voices[index]
            if voice is None:
                continue
            self._phase_values[index] = voice.phase
            self._phase_steps[index] = voice.phase_step
            self._amplitudes[index] = voice.amplitude
            self._source_offsets[index] = SOUND_SOURCE_INDEX[voice.source] * WAVETABLE_SIZE
            self._rendered_frames[index] = self._fill_envelope_row(
                envelope[index],
                voice,
                TIMBRES[voice.source],
            )

        phases = self._phase_scratch[:voice_count, :frame_count]
        np.multiply(
            self._phase_steps[:voice_count, np.newaxis],
            self._frame_offsets[np.newaxis, :frame_count],
            out=phases,
        )
        phases += self._phase_values[:voice_count, np.newaxis]
        np.remainder(phases, WAVETABLE_SIZE, out=phases)
        np.floor(phases, out=phases)

        sample_indices = self._index_scratch[:voice_count, :frame_count]
        np.copyto(sample_indices, phases, casting="unsafe")
        sample_indices += self._source_offsets[:voice_count, np.newaxis]

        samples = self._sample_scratch[:voice_count, :frame_count]
        np.take(WAVETABLE_FLAT, sample_indices, out=samples)
        samples *= envelope
        samples *= self._amplitudes[:voice_count, np.newaxis]
        mix = self._mix_scratch[:frame_count]
        np.sum(samples, axis=0, out=mix)

        for index in range(voice_count):
            voice = self._render_voices[index]
            if voice is None:
                continue
            voice.phase = (
                self._phase_values[index]
                + self._phase_steps[index] * self._rendered_frames[index]
            ) % WAVETABLE_SIZE
        return mix

    def _collect_render_voices(self) -> int:
        voice_index = 0
        for key, voice in self._voices.items():
            self._render_keys[voice_index] = key
            self._render_voices[voice_index] = voice
            voice_index += 1
        self._active_render_voice_count = voice_index
        for voice in self._fading_voices:
            self._render_keys[voice_index] = None
            self._render_voices[voice_index] = voice
            voice_index += 1
        return voice_index

    def _remove_finished_voices(
        self,
        active_voice_count: int,
        voice_count: int,
    ) -> None:
        for index in range(active_voice_count):
            voice = self._render_voices[index]
            key = self._render_keys[index]
            if (
                voice is not None
                and key is not None
                and self._voice_is_finished(voice)
                and self._voices.get(key) is voice
            ):
                self._voices.pop(key, None)

        write_index = 0
        for voice in self._fading_voices:
            if not self._voice_is_finished(voice):
                self._fading_voices[write_index] = voice
                write_index += 1
        del self._fading_voices[write_index:]

        for index in range(voice_count):
            self._render_voices[index] = None
            self._render_keys[index] = None

    def _fill_envelope_row(
        self,
        row: np.ndarray,
        voice: Voice,
        timbre: Timbre,
    ) -> int:
        frame_count = len(row)
        cursor = 0
        envelope = voice.envelope
        stage = voice.stage
        while cursor < frame_count:
            remaining = frame_count - cursor
            offsets = self._envelope_offsets[:remaining]
            target = row[cursor:]
            if stage == "attack":
                step = 1.0 / max(1.0, timbre.attack * self.sample_rate)
                transition_frames = max(1, math.ceil((1.0 - envelope) / step))
                count = min(remaining, transition_frames)
                np.multiply(offsets[:count], step, out=target[:count])
                target[:count] += envelope
                np.minimum(target[:count], 1.0, out=target[:count])
                envelope = float(target[count - 1])
                cursor += count
                if count >= transition_frames:
                    envelope = 1.0
                    stage = "decay"
                continue
            if stage == "decay":
                if timbre.held_decay is not None:
                    ratio = timbre.sustain ** (
                        1.0 / max(1.0, timbre.decay * self.sample_rate)
                    )
                    transition_frames = max(
                        1,
                        math.ceil(math.log(timbre.sustain / envelope) / math.log(ratio)),
                    )
                    count = min(remaining, transition_frames)
                    np.power(ratio, offsets[:count], out=target[:count])
                    target[:count] *= envelope
                    np.maximum(target[:count], timbre.sustain, out=target[:count])
                    envelope = float(target[count - 1])
                    cursor += count
                    if count >= transition_frames:
                        envelope = timbre.sustain
                        stage = "held_decay"
                    continue
                step = (1.0 - timbre.sustain) / max(
                    1.0,
                    timbre.decay * self.sample_rate,
                )
                transition_frames = max(
                    1,
                    math.ceil((envelope - timbre.sustain) / step),
                )
                count = min(remaining, transition_frames)
                np.multiply(offsets[:count], -step, out=target[:count])
                target[:count] += envelope
                np.maximum(target[:count], timbre.sustain, out=target[:count])
                envelope = float(target[count - 1])
                cursor += count
                if count >= transition_frames:
                    envelope = timbre.sustain
                    stage = "held_decay" if timbre.held_decay is not None else "sustain"
                continue
            if stage == "held_decay":
                if envelope <= NATURAL_DECAY_SILENCE_ENVELOPE:
                    envelope = 0.0
                    stage = "finished"
                    continue
                decay_seconds = self._natural_decay_seconds(
                    voice.note,
                    float(timbre.held_decay),
                )
                ratio = (NATURAL_DECAY_SILENCE_ENVELOPE / timbre.sustain) ** (
                    1.0 / max(1.0, decay_seconds * self.sample_rate)
                )
                transition_frames = max(
                    1,
                    math.ceil(
                        math.log(NATURAL_DECAY_SILENCE_ENVELOPE / envelope)
                        / math.log(ratio)
                    ),
                )
                count = min(remaining, transition_frames)
                np.power(ratio, offsets[:count], out=target[:count])
                target[:count] *= envelope
                envelope = float(target[count - 1])
                cursor += count
                if count >= transition_frames:
                    envelope = 0.0
                    stage = "finished"
                continue
            if stage == "release":
                np.multiply(offsets, -voice.release_step, out=target)
                target += envelope
                np.maximum(target, 0.0, out=target)
                envelope = float(target[-1])
                cursor = frame_count
                voice.envelope = envelope
                voice.stage = stage
                return frame_count
            if stage == "finished":
                target.fill(0.0)
                envelope = 0.0
                cursor = frame_count
                continue
            target.fill(timbre.sustain)
            envelope = timbre.sustain
            cursor = frame_count

        voice.envelope = envelope
        voice.stage = stage
        return frame_count

    @staticmethod
    def _natural_decay_seconds(note: int, reference_seconds: float) -> float:
        pitch_factor = 2.0 ** (
            (NATURAL_DECAY_REFERENCE_NOTE - int(note)) / NATURAL_DECAY_PITCH_SPAN
        )
        return max(
            NATURAL_DECAY_MIN_SECONDS,
            min(NATURAL_DECAY_MAX_SECONDS, reference_seconds * pitch_factor),
        )

    def _ensure_output_capacity(self, frame_count: int) -> None:
        if self._output_scratch.size < frame_count:
            self._output_scratch = np.empty(frame_count, dtype=np.float32)
        if self._limiter_magnitude_scratch.size < frame_count:
            self._limiter_magnitude_scratch = np.empty(
                frame_count,
                dtype=np.float32,
            )
            self._limiter_excess_scratch = np.empty(
                frame_count,
                dtype=np.float32,
            )

    def _ensure_gain_capacity(self, frame_count: int) -> None:
        if self._gain_scratch.size < frame_count:
            self._gain_scratch = np.empty(frame_count, dtype=np.float32)

    def _ensure_pcm_capacity(self, sample_count: int) -> None:
        if self._interleaved_scratch.size >= sample_count:
            return
        self._interleaved_scratch = np.empty(sample_count, dtype=np.float32)
        self._pcm_int16_scratch = np.empty(sample_count, dtype=np.int16)
        self._pcm_int32_scratch = np.empty(sample_count, dtype=np.int32)

    def _soft_limit_array(self, samples: np.ndarray) -> None:
        frame_count = len(samples)
        magnitudes = self._limiter_magnitude_scratch[:frame_count]
        excess = self._limiter_excess_scratch[:frame_count]
        np.abs(samples, out=magnitudes)
        np.subtract(magnitudes, LIMITER_THRESHOLD, out=excess)
        np.maximum(excess, 0.0, out=excess)
        excess /= 1.0 - LIMITER_THRESHOLD
        np.tanh(excess, out=excess)
        excess *= 1.0 - LIMITER_THRESHOLD
        np.minimum(magnitudes, LIMITER_THRESHOLD, out=magnitudes)
        magnitudes += excess
        np.copysign(magnitudes, samples, out=samples)

    @staticmethod
    def _voice_is_finished(voice: Voice) -> bool:
        return voice.stage == "finished" or (
            voice.stage == "release" and voice.envelope <= 0.0
        )

    def _begin_release(
        self,
        voice: Voice,
        release_seconds: float | None = None,
    ) -> None:
        release = (
            TIMBRES[voice.source].release
            if release_seconds is None
            else max(0.001, float(release_seconds))
        )
        release_step = max(voice.envelope, 0.0001) / max(1.0, release * self.sample_rate)
        if voice.stage == "release":
            voice.release_step = max(voice.release_step, release_step)
            return
        voice.stage = "release"
        voice.release_step = release_step

    def _trim_voices(self) -> None:
        while len(self._voices) > MAX_VOICES:
            key, voice = min(
                self._voices.items(),
                key=lambda item: (
                    item[1].stage != "release",
                    item[1].envelope * item[1].amplitude,
                    item[1].started_order,
                ),
            )
            self._voices.pop(key, None)
            voice.key_released = True
            self._begin_release(
                voice,
                release_seconds=RETRIGGER_RELEASE_SECONDS,
            )
            self._fading_voices.append(voice)

    def _trim_fading_voices(self) -> None:
        while len(self._fading_voices) > MAX_FADING_VOICES:
            quietest = min(
                self._fading_voices,
                key=lambda voice: (voice.envelope * voice.amplitude, voice.started_order),
            )
            self._fading_voices.remove(quietest)

    @staticmethod
    def _soft_limit(sample: float) -> float:
        magnitude = abs(sample)
        if magnitude <= LIMITER_THRESHOLD:
            return sample
        limited = LIMITER_THRESHOLD + (1.0 - LIMITER_THRESHOLD) * math.tanh(
            (magnitude - LIMITER_THRESHOLD) / (1.0 - LIMITER_THRESHOLD)
        )
        return math.copysign(limited, sample)


def _audio_start_failed(sink) -> bool:  # type: ignore[no-untyped-def]
    return (
        sink.state() == QAudio.State.StoppedState
        and sink.error()
        in {
            QAudio.Error.OpenError,
            QAudio.Error.IOError,
            QAudio.Error.FatalError,
        }
    )


class _PushAudioOutput(QObject):
    """Feeds short PCM blocks into QAudioSink from a dedicated Qt thread."""

    def __init__(
        self,
        stream: SoftwareSynthStream,
        device,
        audio_format: QAudioFormat,
        requested_sink_frames: int,
    ) -> None:
        super().__init__()
        self.stream = stream
        self.device = device
        self.audio_format = audio_format
        self.requested_sink_frames = max(1, int(requested_sink_frames))
        self.ready = threading.Event()
        self.stopped = threading.Event()
        self.started_ok = False
        self.error = ""
        self.actual_sink_frames = self.requested_sink_frames
        self._sink: QAudioSink | None = None
        self._output_device = None
        self._timer: QTimer | None = None
        self._pending_pcm = b""
        self._pumping = False

    @Slot()
    def start_output(self) -> None:
        try:
            sink = QAudioSink(self.device, self.audio_format)
            sink.setBufferFrameCount(self.requested_sink_frames)
            output_device = sink.start()
            if output_device is None or _audio_start_failed(sink):
                error_name = sink.error().name
                sink.reset()
                self.error = f"Audio output initialization failed ({error_name})"
                return
            self._sink = sink
            self._output_device = output_device
            actual_frames = int(sink.bufferFrameCount())
            if actual_frames > 0:
                self.actual_sink_frames = actual_frames
            timer = QTimer(self)
            timer.setTimerType(Qt.TimerType.PreciseTimer)
            timer.setInterval(PUSH_PUMP_INTERVAL_MS)
            timer.timeout.connect(self.pump)
            self._timer = timer
            try:
                output_device.bytesWritten.connect(self._on_bytes_written)
            except (AttributeError, RuntimeError, TypeError):
                pass
            self.started_ok = True
            self.pump()
            timer.start()
        except Exception as exc:
            self.error = str(exc)
            if self._sink is not None:
                self._sink.reset()
                self._sink = None
            self._output_device = None
        finally:
            self.ready.set()

    @Slot(int)
    def _on_bytes_written(self, _byte_count: int) -> None:
        self.pump()

    @Slot()
    def pump(self) -> None:
        if self._pumping or not self.started_ok:
            return
        sink = self._sink
        output_device = self._output_device
        if sink is None or output_device is None:
            return
        if _audio_start_failed(sink):
            self.error = f"Audio output failed ({sink.error().name})"
            if self._timer is not None:
                self._timer.stop()
            return

        self._pumping = True
        try:
            if self._pending_pcm:
                written = int(output_device.write(self._pending_pcm))
                if written < 0:
                    self.error = "Audio output rejected PCM data"
                    self.stream._record_supply_shortage()
                    return
                if written == 0:
                    return
                self._pending_pcm = self._pending_pcm[written:]
                if self._pending_pcm:
                    return

            actual_frames = max(1, int(sink.bufferFrameCount()))
            target_frames = min(PUSH_TARGET_FRAMES, actual_frames)
            write_frames = min(PUSH_WRITE_FRAMES, target_frames)
            refill_threshold = max(0, target_frames - write_frames)
            max_writes = max(
                1,
                (target_frames + write_frames - 1) // write_frames,
            )
            for _ in range(max_writes):
                free_frames = max(0, int(sink.framesFree()))
                queued_frames = max(0, actual_frames - free_frames)
                if queued_frames > refill_threshold:
                    return
                frame_count = min(
                    write_frames,
                    free_frames,
                    max(0, target_frames - queued_frames),
                )
                if frame_count <= 0:
                    return

                pcm = self.stream.take_pcm_frames(
                    frame_count,
                    pad_silence=False,
                )
                if not pcm:
                    if queued_frames <= 0:
                        self.stream._record_supply_shortage()
                    return
                written = int(output_device.write(pcm))
                if written < 0:
                    self.error = "Audio output rejected PCM data"
                    self.stream._record_supply_shortage()
                    return
                if written < len(pcm):
                    self._pending_pcm = pcm[max(0, written):]
                    return
        except Exception as exc:
            self.error = str(exc)
            self.stream._record_supply_shortage()
        finally:
            self._pumping = False

    @Slot()
    def stop_output(self) -> None:
        try:
            if self._timer is not None:
                self._timer.stop()
                self._timer = None
            output_device = self._output_device
            if output_device is not None:
                try:
                    output_device.bytesWritten.disconnect(self._on_bytes_written)
                except (AttributeError, RuntimeError, TypeError):
                    pass
            self._output_device = None
            self._pending_pcm = b""
            if self._sink is not None:
                self._sink.reset()
                self._sink = None
            self.started_ok = False
        finally:
            self.stopped.set()


class SoftwareSynthEngine:
    def __init__(self) -> None:
        self.stream = SoftwareSynthStream()
        self._output_thread: QThread | None = None
        self._output_worker: _PushAudioOutput | None = None
        self._lock = threading.RLock()
        self._next_client_id = 0
        self.buffer_frames = DEFAULT_AUDIO_BUFFER_FRAMES
        self.qt_frames = DEFAULT_QT_AUDIO_FRAMES
        self.last_error = ""
        self._runtime_callbacks: dict[
            int,
            Callable[[int, int, str], None],
        ] = {}
        self._active_clients: set[int] = set()
        self._buffer_policy = AudioBufferAutoPolicy()
        self._monitor_stop = threading.Event()
        self._monitor_thread = threading.Thread(
            target=self._monitor_audio_supply,
            name="AudioRuntimeMonitor",
            daemon=True,
        )
        self._monitor_thread.start()

    def start(self) -> bool:
        with self._lock:
            if self._output_worker is not None:
                return True
            return self._start_sink_locked()

    def new_client_id(self) -> int:
        with self._lock:
            self._next_client_id += 1
            return self._next_client_id

    def register_client(
        self,
        client_id: int,
        callback: Callable[[int, int, str], None] | None,
    ) -> None:
        with self._lock:
            self._active_clients.add(int(client_id))
            if callback is not None:
                self._runtime_callbacks[int(client_id)] = callback
            else:
                self._runtime_callbacks.pop(int(client_id), None)
            qt_frames = self.qt_frames
            buffer_frames = self.buffer_frames
        if callback is not None:
            try:
                callback(qt_frames, buffer_frames, "")
            except Exception:
                pass

    def unregister_client(self, client_id: int) -> None:
        with self._lock:
            self._active_clients.discard(int(client_id))
            self._runtime_callbacks.pop(int(client_id), None)

    def shutdown(self) -> None:
        self._monitor_stop.set()
        monitor = self._monitor_thread
        if monitor is not threading.current_thread():
            monitor.join(timeout=1.0)
        with self._lock:
            self._stop_output_locked()
            self.stream.close()

    def _stop_output_locked(self) -> None:
        worker = self._output_worker
        thread = self._output_thread
        self._output_worker = None
        self._output_thread = None
        if worker is not None and thread is not None and thread.isRunning():
            try:
                QMetaObject.invokeMethod(
                    worker,
                    "stop_output",
                    Qt.ConnectionType.QueuedConnection,
                )
                worker.stopped.wait(1.0)
            except RuntimeError:
                pass
            thread.quit()
            thread.wait(1_000)

    def _apply_buffer_frames_live_locked(self, buffer_frames: int) -> bool:
        """Update the PCM reserve depth without replacing the audio sink."""
        try:
            self.stream.set_buffer_frames_live(buffer_frames)
            self.buffer_frames = buffer_frames
            self.last_error = ""
            return True
        except Exception as exc:
            self.last_error = str(exc)
            return False

    def _start_sink_locked(self) -> bool:
        if QCoreApplication.instance() is None:
            self.last_error = "Qt application is not running"
            return False
        device = QMediaDevices.defaultAudioOutput()
        if device.isNull():
            self.last_error = "No audio output device is available"
            return False
        audio_format = self._choose_format(device)
        if audio_format is None:
            self.last_error = "The audio device has no supported PCM format"
            return False
        self.stream.configure(
            audio_format.sampleRate(),
            audio_format.channelCount(),
            audio_format.sampleFormat(),
            self.buffer_frames,
        )
        if not self.stream.start_worker():
            self.last_error = "Software synthesizer worker could not be primed"
            self.stream.stop_worker()
            return False
        thread = QThread()
        worker = _PushAudioOutput(
            self.stream,
            device,
            audio_format,
            self.qt_frames,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.start_output)
        thread.start()
        if not worker.ready.wait(2.0) or not worker.started_ok:
            self.last_error = (
                worker.error
                or "Software synthesizer push output could not be started"
            )
            if thread.isRunning():
                try:
                    QMetaObject.invokeMethod(
                        worker,
                        "stop_output",
                        Qt.ConnectionType.QueuedConnection,
                    )
                    worker.stopped.wait(1.0)
                except RuntimeError:
                    pass
                thread.quit()
                thread.wait(1_000)
            self.stream.stop_worker()
            return False
        self._output_thread = thread
        self._output_worker = worker
        self.qt_frames = worker.actual_sink_frames
        self._buffer_policy.reset()
        self.stream.clear_metrics()
        self.last_error = ""
        return True

    def _monitor_audio_supply(self) -> None:
        while not self._monitor_stop.wait(0.25):
            metrics = self.stream.metrics_snapshot()
            with self._lock:
                if self._output_worker is None or not self._active_clients:
                    continue
                now = time.monotonic()
                decision = self._buffer_policy.evaluate(
                    now,
                    self.buffer_frames,
                    metrics,
                    self.stream.minimum_effective_buffer_frames(),
                )
                if (
                    decision is not None
                    and decision.frames != self.buffer_frames
                    and not self._apply_buffer_frames_live_locked(decision.frames)
                ):
                    decision = None
                if decision is None:
                    continue
                self.stream.clear_metrics()
                callbacks = tuple(self._runtime_callbacks.values())
                qt_frames = self.qt_frames
                buffer_frames = self.buffer_frames
            for callback in callbacks:
                try:
                    callback(qt_frames, buffer_frames, decision.reason)
                except Exception:
                    continue

    @staticmethod
    def _choose_format(device) -> QAudioFormat | None:  # type: ignore[no-untyped-def]
        supported_formats = (
            QAudioFormat.SampleFormat.Float,
            QAudioFormat.SampleFormat.Int16,
            QAudioFormat.SampleFormat.Int32,
        )
        preferred = device.preferredFormat()
        if (
            preferred.isValid()
            and preferred.sampleFormat() in supported_formats
            and device.isFormatSupported(preferred)
        ):
            return preferred

        preferred_rate = preferred.sampleRate() if preferred.isValid() else 48_000
        preferred_channels = preferred.channelCount() if preferred.isValid() else 2
        candidates = (
            (preferred_rate, preferred_channels),
            (48_000, 2),
            (44_100, 2),
            (48_000, 1),
            (44_100, 1),
        )
        for sample_rate, channels in candidates:
            for sample_format in supported_formats:
                audio_format = QAudioFormat()
                audio_format.setSampleRate(sample_rate)
                audio_format.setChannelCount(channels)
                audio_format.setSampleFormat(sample_format)
                if device.isFormatSupported(audio_format):
                    return audio_format
        return None

    @staticmethod
    def _audio_start_failed(sink) -> bool:  # type: ignore[no-untyped-def]
        return _audio_start_failed(sink)


_engine_lock = threading.Lock()
_engine: SoftwareSynthEngine | None = None


def shared_software_synth() -> SoftwareSynthEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = SoftwareSynthEngine()
        return _engine


def shutdown_software_synth() -> None:
    global _engine
    with _engine_lock:
        engine = _engine
        _engine = None
    if engine is not None:
        engine.shutdown()


class SoftwareSynthClient:
    def __init__(
        self,
        sound_source: str = DEFAULT_SOUND_SOURCE,
        *,
        on_runtime_changed: Callable[[int, int, str], None] | None = None,
    ) -> None:
        self.sound_source = normalize_sound_source(sound_source)
        self.qt_frames = DEFAULT_QT_AUDIO_FRAMES
        self.buffer_frames = DEFAULT_AUDIO_BUFFER_FRAMES
        self.on_runtime_changed = on_runtime_changed
        self._engine: SoftwareSynthEngine | None = None
        self._client_id: int | None = None
        self._last_error = ""

    @property
    def is_open(self) -> bool:
        return self._engine is not None and self._client_id is not None

    @property
    def last_error(self) -> str:
        return self._last_error

    def open(self) -> bool:
        if self.is_open:
            return True
        engine = shared_software_synth()
        if not engine.start():
            self._last_error = engine.last_error
            return False
        self._engine = engine
        self._client_id = engine.new_client_id()
        engine.register_client(
            self._client_id,
            self._runtime_changed,
        )
        self._last_error = ""
        return True

    def close(self) -> None:
        if self._engine is not None and self._client_id is not None:
            self._engine.stream.release_all(
                self._client_id,
                release_seconds=STOP_RELEASE_SECONDS,
            )
            self._engine.unregister_client(self._client_id)
        self._engine = None
        self._client_id = None

    def set_sound_source(self, sound_source: str) -> None:
        self.sound_source = normalize_sound_source(sound_source)

    def _runtime_changed(
        self,
        qt_frames: int,
        buffer_frames: int,
        reason: str,
    ) -> None:
        self.qt_frames = max(1, int(qt_frames))
        self.buffer_frames = normalize_audio_buffer_frames(buffer_frames)
        if self.on_runtime_changed is not None:
            self.on_runtime_changed(
                self.qt_frames,
                self.buffer_frames,
                str(reason),
            )

    def note_on(self, channel: int, note: int, velocity: int) -> None:
        if self._engine is not None and self._client_id is not None:
            self._engine.stream.note_on(
                self._client_id,
                channel,
                note,
                velocity,
                self.sound_source,
            )

    def note_off(self, channel: int, note: int) -> None:
        if self._engine is not None and self._client_id is not None:
            self._engine.stream.note_off(self._client_id, channel, note)

    def set_sustain(self, channel: int, enabled: bool) -> None:
        if self._engine is not None and self._client_id is not None:
            self._engine.stream.set_sustain(self._client_id, channel, enabled)

    def release_all(self, channel: int | None = None) -> None:
        if self._engine is not None and self._client_id is not None:
            self._engine.stream.release_all(self._client_id, channel)
