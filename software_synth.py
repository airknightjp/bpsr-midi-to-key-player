from __future__ import annotations

import math
import multiprocessing
import os
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
    Signal,
    QThread,
    QTimer,
    Qt,
    Slot,
)
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices

from audio_buffer import (
    AUDIO_BUFFER_FRAME_OPTIONS,
    AUDIO_CHUNK_FRAME_OPTIONS,
    DEFAULT_AUDIO_BUFFER_FRAMES,
    DEFAULT_AUDIO_CHUNK_FRAMES,
    DEFAULT_AUDIO_FALLBACK_INTERVAL_MS,
    DEFAULT_AUDIO_RESPONSE_FRAMES,
    DEFAULT_QT_AUDIO_FRAMES,
    normalize_audio_chunk_frames,
    normalize_audio_buffer_frames,
    normalize_audio_fallback_interval_ms,
    normalize_audio_response_frames,
    normalize_qt_audio_frames,
)
from sound_sources import (
    DEFAULT_SOUND_SOURCE,
    STARRA_GUITAR_SOURCE,
    normalize_sound_source,
)
from starra_guitar_bank import get_starra_guitar_bank
from process_lifecycle import (
    register_child_process,
    start_parent_process_watchdog,
)

SAMPLE_RATE = 44_100
WAVETABLE_SIZE = 2_048
MAX_VOICES = 64
MAX_FADING_VOICES = 16
RETRIGGER_RELEASE_SECONDS = 0.008
STOP_RELEASE_SECONDS = 0.015
LIMITER_THRESHOLD = 0.92
RENDER_CHUNK_FRAMES = DEFAULT_AUDIO_CHUNK_FRAMES
LOW_LATENCY_AUDIO_FRAMES = DEFAULT_AUDIO_RESPONSE_FRAMES
PUSH_REFILL_THRESHOLD_FRAMES = DEFAULT_AUDIO_RESPONSE_FRAMES
PUSH_MAX_WRITE_FRAMES = DEFAULT_AUDIO_CHUNK_FRAMES
PUSH_STANDBY_FRAMES = 128
PUSH_PRIME_FRAMES = DEFAULT_QT_AUDIO_FRAMES
PUSH_FALLBACK_INTERVAL_MS = DEFAULT_AUDIO_FALLBACK_INTERVAL_MS
OUTPUT_FADE_INTERVAL_MS = 1
OUTPUT_FADE_STEPS = 3
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
AUDIO_ACTIVITY_SAMPLE_SECONDS = 0.20
AUDIO_TIMER_JITTER_SAMPLE_SECONDS = 0.25
AUDIO_IDLE_SHUTDOWN_SECONDS = 0.5


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
    STARRA_GUITAR_SOURCE: Timbre((1.0,), 0.001, 0.001, 1.0, 0.13),
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
    sample_position: float = 0.0
    sample_step: float = 1.0
    sample_index: int = -1
    sample_length: int = 0


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
    supply_delays: tuple[float, ...] = ()
    output_underruns: tuple[float, ...] = ()
    producer_starved_output_underruns: tuple[float, ...] = ()
    audio_activity: tuple[float, ...] = ()
    timer_jitter: tuple[tuple[float, float], ...] = ()
    qt_queue_samples: tuple[tuple[float, int, int], ...] = ()
    currently_active_audio: bool = False
    ring_buffer_bytes: int = 0
    ring_target_bytes: int = 0


@dataclass(frozen=True)
class AudioPipelineTuning:
    response_frames: int = DEFAULT_AUDIO_RESPONSE_FRAMES
    chunk_frames: int = DEFAULT_AUDIO_CHUNK_FRAMES
    fallback_interval_ms: int = DEFAULT_AUDIO_FALLBACK_INTERVAL_MS

    def normalized(self) -> AudioPipelineTuning:
        response_frames = normalize_audio_response_frames(
            self.response_frames
        )
        chunk_frames = normalize_audio_chunk_frames(self.chunk_frames)
        if chunk_frames < response_frames:
            chunk_frames = min(
                (
                    candidate
                    for candidate in AUDIO_CHUNK_FRAME_OPTIONS
                    if candidate >= response_frames
                ),
                default=AUDIO_CHUNK_FRAME_OPTIONS[-1],
            )
        return AudioPipelineTuning(
            response_frames=response_frames,
            chunk_frames=chunk_frames,
            fallback_interval_ms=normalize_audio_fallback_interval_ms(
                self.fallback_interval_ms
            ),
        )


@dataclass(frozen=True)
class AudioRuntimeTuning:
    qt_frames: int = DEFAULT_QT_AUDIO_FRAMES
    buffer_frames: int = DEFAULT_AUDIO_BUFFER_FRAMES
    response_frames: int = DEFAULT_AUDIO_RESPONSE_FRAMES
    chunk_frames: int = DEFAULT_AUDIO_CHUNK_FRAMES
    fallback_interval_ms: int = DEFAULT_AUDIO_FALLBACK_INTERVAL_MS

    def normalized(self) -> AudioRuntimeTuning:
        pipeline = AudioPipelineTuning(
            self.response_frames,
            self.chunk_frames,
            self.fallback_interval_ms,
        ).normalized()
        return AudioRuntimeTuning(
            qt_frames=normalize_qt_audio_frames(self.qt_frames),
            buffer_frames=normalize_audio_buffer_frames(
                self.buffer_frames
            ),
            response_frames=pipeline.response_frames,
            chunk_frames=pipeline.chunk_frames,
            fallback_interval_ms=pipeline.fallback_interval_ms,
        )

    @property
    def pipeline(self) -> AudioPipelineTuning:
        return AudioPipelineTuning(
            self.response_frames,
            self.chunk_frames,
            self.fallback_interval_ms,
        ).normalized()


class SoftwareSynthStream:
    """PCM producer shared by MIDI playback and realtime preview."""

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        channels: int = 2,
        buffer_frames: int = DEFAULT_AUDIO_BUFFER_FRAMES,
        response_frames: int = DEFAULT_AUDIO_RESPONSE_FRAMES,
        chunk_frames: int = DEFAULT_AUDIO_CHUNK_FRAMES,
        time_source: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.sample_rate = max(8_000, int(sample_rate))
        self.channels = max(1, int(channels))
        self.buffer_frames = normalize_audio_buffer_frames(buffer_frames)
        self.response_frames = normalize_audio_response_frames(
            response_frames
        )
        self.chunk_frames = normalize_audio_chunk_frames(chunk_frames)
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
        self._sample_interp_scratch = np.empty(render_shape, dtype=np.float32)
        self._sample_int16_scratch = np.empty(render_shape, dtype=np.int16)
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
        self._supply_delay_timestamps: deque[float] = deque()
        self._output_underrun_timestamps: deque[float] = deque()
        self._producer_starved_output_underrun_timestamps: deque[float] = (
            deque()
        )
        self._audio_activity_timestamps: deque[float] = deque()
        self._timer_jitter: deque[tuple[float, float]] = deque()
        self._qt_queue_samples: deque[tuple[float, int, int]] = deque()
        self._last_shortage_at = float("-inf")
        self._last_supply_delay_at = float("-inf")
        self._last_output_underrun_at = float("-inf")
        self._last_producer_starved_output_underrun_at = float("-inf")
        self._last_audio_activity_at = float("-inf")
        self._currently_active_audio = False

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

    def set_pipeline_tuning_live(
        self,
        response_frames: int,
        chunk_frames: int,
    ) -> None:
        with self._ring_condition:
            tuning = AudioPipelineTuning(
                response_frames=response_frames,
                chunk_frames=chunk_frames,
            ).normalized()
            self.response_frames = tuning.response_frames
            self.chunk_frames = tuning.chunk_frames
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
                        self.response_frames,
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
                    immediate_bytes = PUSH_PRIME_FRAMES * frame_size
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
                        self.chunk_frames,
                    )
            if refreshed_pcm:
                self._record_synthesis_utilization(
                    (
                        elapsed / refresh_deadline
                        if refresh_deadline > 0.0
                        else 0.0
                    ),
                    active_audio=bool(
                        render_state.voices or render_state.fading_voices
                    ),
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
                active_audio=bool(
                    render_state.voices or render_state.fading_voices
                ),
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
        return AUDIO_BUFFER_FRAME_OPTIONS[0]

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
        *,
        active_audio: bool = False,
    ) -> None:
        now = time.monotonic()
        with self._metrics_lock:
            utilization = max(0.0, float(utilization))
            if active_audio:
                self._synthesis_utilization.append((now, utilization))
            if (
                active_audio
                and utilization >= 1.0
                and now - self._last_supply_delay_at
                >= AUDIO_SHORTAGE_DEBOUNCE_SECONDS
            ):
                self._last_supply_delay_at = now
                self._supply_delay_timestamps.append(now)
            if (
                active_audio
                and now - self._last_audio_activity_at
                >= AUDIO_ACTIVITY_SAMPLE_SECONDS
            ):
                self._last_audio_activity_at = now
                self._audio_activity_timestamps.append(now)
            self._currently_active_audio = bool(active_audio)
            self._prune_metrics_locked(now)

    def _record_output_underrun(
        self,
        *,
        producer_starved: bool = False,
    ) -> None:
        now = time.monotonic()
        with self._metrics_lock:
            if (
                now - self._last_output_underrun_at
                < AUDIO_SHORTAGE_DEBOUNCE_SECONDS
            ):
                if (
                    producer_starved
                    and self._last_output_underrun_at
                    > self._last_producer_starved_output_underrun_at
                ):
                    self._last_producer_starved_output_underrun_at = (
                        self._last_output_underrun_at
                    )
                    self._producer_starved_output_underrun_timestamps.append(
                        self._last_output_underrun_at
                    )
                    self._prune_metrics_locked(now)
                return
            self._last_output_underrun_at = now
            self._output_underrun_timestamps.append(now)
            if producer_starved:
                self._last_producer_starved_output_underrun_at = now
                self._producer_starved_output_underrun_timestamps.append(now)
            self._prune_metrics_locked(now)

    def _record_timer_jitter(self, jitter_ms: float) -> None:
        now = time.monotonic()
        with self._metrics_lock:
            self._timer_jitter.append(
                (now, max(0.0, float(jitter_ms)))
            )
            self._prune_metrics_locked(now)

    def _record_qt_queue_depth(
        self,
        queued_frames: int,
        target_frames: int,
    ) -> None:
        now = time.monotonic()
        with self._metrics_lock:
            self._qt_queue_samples.append(
                (
                    now,
                    max(0, int(queued_frames)),
                    max(1, int(target_frames)),
                )
            )
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
                supply_delays=tuple(self._supply_delay_timestamps),
                output_underruns=tuple(self._output_underrun_timestamps),
                producer_starved_output_underruns=tuple(
                    self._producer_starved_output_underrun_timestamps
                ),
                audio_activity=tuple(self._audio_activity_timestamps),
                timer_jitter=tuple(self._timer_jitter),
                qt_queue_samples=tuple(self._qt_queue_samples),
                currently_active_audio=self._currently_active_audio,
                ring_buffer_bytes=ring_buffer_bytes,
                ring_target_bytes=ring_target_bytes,
            )

    def clear_metrics(self) -> None:
        with self._metrics_lock:
            self._shortage_timestamps.clear()
            self._synthesis_utilization.clear()
            self._supply_delay_timestamps.clear()
            self._output_underrun_timestamps.clear()
            self._producer_starved_output_underrun_timestamps.clear()
            self._audio_activity_timestamps.clear()
            self._timer_jitter.clear()
            self._qt_queue_samples.clear()
            self._last_shortage_at = float("-inf")
            self._last_supply_delay_at = float("-inf")
            self._last_output_underrun_at = float("-inf")
            self._last_producer_starved_output_underrun_at = float("-inf")
            self._last_audio_activity_at = float("-inf")
            self._currently_active_audio = False

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
            self._supply_delay_timestamps
            and self._supply_delay_timestamps[0] < cutoff
        ):
            self._supply_delay_timestamps.popleft()
        while (
            self._output_underrun_timestamps
            and self._output_underrun_timestamps[0] < cutoff
        ):
            self._output_underrun_timestamps.popleft()
        while (
            self._producer_starved_output_underrun_timestamps
            and self._producer_starved_output_underrun_timestamps[0] < cutoff
        ):
            self._producer_starved_output_underrun_timestamps.popleft()
        while (
            self._audio_activity_timestamps
            and self._audio_activity_timestamps[0] < cutoff
        ):
            self._audio_activity_timestamps.popleft()
        while (
            self._timer_jitter
            and self._timer_jitter[0][0] < cutoff
        ):
            self._timer_jitter.popleft()
        while (
            self._qt_queue_samples
            and self._qt_queue_samples[0][0] < cutoff
        ):
            self._qt_queue_samples.popleft()

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
        sample_index = -1
        sample_length = 0
        sample_step = 1.0
        if source == STARRA_GUITAR_SOURCE:
            sample = get_starra_guitar_bank().select(note, self.sample_rate)
            sample_index = sample.bank_index
            sample_length = sample.sample_length
            sample_step = sample.playback_step
        self._voices[key] = Voice(
            client_id=client_id,
            channel=channel,
            note=note,
            source=source,
            phase=0.0,
            phase_step=phase_step,
            amplitude=amplitude,
            started_order=self._voice_order,
            sample_step=sample_step,
            sample_index=sample_index,
            sample_length=sample_length,
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
        self._render_sample_bank_voices(samples, voice_count, frame_count)
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

    def _render_sample_bank_voices(
        self,
        samples: np.ndarray,
        voice_count: int,
        frame_count: int,
    ) -> None:
        bank = None
        for index in range(voice_count):
            voice = self._render_voices[index]
            if voice is None or voice.source != STARRA_GUITAR_SOURCE:
                continue
            row = samples[index]
            if voice.stage == "finished" or voice.sample_position >= voice.sample_length:
                row.fill(0.0)
                voice.envelope = 0.0
                voice.stage = "finished"
                continue
            if bank is None:
                bank = get_starra_guitar_bank()
            source = bank.samples[voice.sample_index]
            available_frames = min(
                frame_count,
                max(
                    0,
                    math.ceil(
                        (voice.sample_length - voice.sample_position)
                        / voice.sample_step
                    ),
                ),
            )
            if available_frames <= 0:
                row.fill(0.0)
                voice.envelope = 0.0
                voice.stage = "finished"
                continue

            positions = self._phase_scratch[index, :available_frames]
            np.multiply(
                self._frame_offsets[:available_frames],
                voice.sample_step,
                out=positions,
            )
            positions += voice.sample_position
            lower_indices = self._index_scratch[index, :available_frames]
            np.copyto(lower_indices, positions, casting="unsafe")
            fractions = positions
            fractions -= lower_indices
            integer_samples = self._sample_int16_scratch[index, :available_frames]
            np.take(source, lower_indices, out=integer_samples)
            np.copyto(row[:available_frames], integer_samples, casting="unsafe")
            upper = self._sample_interp_scratch[index, :available_frames]
            lower_indices += 1
            np.minimum(lower_indices, voice.sample_length - 1, out=lower_indices)
            np.take(source, lower_indices, out=integer_samples)
            np.copyto(upper, integer_samples, casting="unsafe")
            upper -= row[:available_frames]
            upper *= fractions
            row[:available_frames] += upper
            row[:available_frames] /= 32_768.0
            if available_frames < frame_count:
                row[available_frames:].fill(0.0)
                voice.envelope = 0.0
                voice.stage = "finished"
            voice.sample_position += available_frames * voice.sample_step

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
        if (
            voice.source == STARRA_GUITAR_SOURCE
            and voice.stage not in ("release", "finished")
        ):
            row.fill(1.0)
            voice.envelope = 1.0
            voice.stage = "sample"
            return frame_count
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

    tuning_requested = Signal(int, int, int)

    def __init__(
        self,
        stream: SoftwareSynthStream,
        device,
        audio_format: QAudioFormat,
        requested_sink_frames: int,
        *,
        response_frames: int = DEFAULT_AUDIO_RESPONSE_FRAMES,
        chunk_frames: int = DEFAULT_AUDIO_CHUNK_FRAMES,
        fallback_interval_ms: int = DEFAULT_AUDIO_FALLBACK_INTERVAL_MS,
        start_muted: bool = False,
        standby_silence: bool = False,
    ) -> None:
        super().__init__()
        self.stream = stream
        self.device = device
        self.audio_format = audio_format
        self.requested_sink_frames = max(1, int(requested_sink_frames))
        tuning = AudioPipelineTuning(
            response_frames=response_frames,
            chunk_frames=chunk_frames,
            fallback_interval_ms=fallback_interval_ms,
        ).normalized()
        self.response_frames = tuning.response_frames
        self.chunk_frames = tuning.chunk_frames
        self.fallback_interval_ms = tuning.fallback_interval_ms
        self.start_muted = bool(start_muted)
        self.standby_silence = bool(standby_silence)
        self.ready = threading.Event()
        self.stopped = threading.Event()
        self.handoff_ready = threading.Event()
        self.handoff_frames = 0
        self.handoff_fade_interval_ms = OUTPUT_FADE_INTERVAL_MS
        self.started_ok = False
        self.error = ""
        self.actual_sink_frames = self.requested_sink_frames
        self._sink: QAudioSink | None = None
        self._output_device = None
        self._timer: QTimer | None = None
        self._fade_timer: QTimer | None = None
        self._fade_step = 0
        self._fade_direction = 0
        self._pending_pcm = b""
        self._pending_is_audio = False
        self._pumping = False
        self._pump_scheduled = False
        self._last_fallback_tick_at: float | None = None
        self._last_jitter_report_at = time.perf_counter()
        self._max_timer_jitter_ms = 0.0
        self._primed = False
        self._stopping = False
        self._bytes_written_connected = False
        self.tuning_requested.connect(self.apply_tuning)

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
            if self.start_muted:
                sink.setVolume(0.0)
            self._sink = sink
            self._output_device = output_device
            actual_frames = int(sink.bufferFrameCount())
            if actual_frames > 0:
                self.actual_sink_frames = actual_frames
            timer = QTimer(self)
            timer.setTimerType(Qt.TimerType.PreciseTimer)
            timer.setInterval(self.fallback_interval_ms)
            timer.timeout.connect(self._on_fallback_timer)
            self._timer = timer
            try:
                output_device.bytesWritten.connect(self._on_bytes_written)
                self._bytes_written_connected = True
            except (AttributeError, RuntimeError, TypeError):
                self._bytes_written_connected = False
            try:
                sink.stateChanged.connect(self._on_state_changed)
            except (AttributeError, RuntimeError, TypeError):
                pass
            self.started_ok = True
            self.pump()
            timer.start()
            if self.start_muted and not self.standby_silence:
                self._start_fade(1)
        except Exception as exc:
            self.error = str(exc)
            if self._sink is not None:
                self._sink.reset()
                self._sink = None
            self._output_device = None
        finally:
            self.ready.set()

    @Slot(int, int, int)
    def apply_tuning(
        self,
        response_frames: int,
        chunk_frames: int,
        fallback_interval_ms: int,
    ) -> None:
        tuning = AudioPipelineTuning(
            response_frames=response_frames,
            chunk_frames=chunk_frames,
            fallback_interval_ms=fallback_interval_ms,
        ).normalized()
        self.response_frames = tuning.response_frames
        self.chunk_frames = tuning.chunk_frames
        self.fallback_interval_ms = tuning.fallback_interval_ms
        if self._timer is not None:
            self._timer.setInterval(self.fallback_interval_ms)
        self._last_fallback_tick_at = None
        self._schedule_pump()

    @Slot()
    def _on_fallback_timer(self) -> None:
        now = time.perf_counter()
        if self._last_fallback_tick_at is not None:
            elapsed_ms = (now - self._last_fallback_tick_at) * 1_000.0
            self._max_timer_jitter_ms = max(
                self._max_timer_jitter_ms,
                max(0.0, elapsed_ms - self.fallback_interval_ms),
            )
        self._last_fallback_tick_at = now
        if (
            now - self._last_jitter_report_at
            >= AUDIO_TIMER_JITTER_SAMPLE_SECONDS
        ):
            self.stream._record_timer_jitter(
                self._max_timer_jitter_ms
            )
            sink = self._sink
            if sink is not None:
                try:
                    target_frames = max(
                        1,
                        int(sink.bufferFrameCount()),
                    )
                    free_frames = max(0, int(sink.framesFree()))
                    self.stream._record_qt_queue_depth(
                        max(0, target_frames - free_frames),
                        target_frames,
                    )
                except (
                    AttributeError,
                    RuntimeError,
                    TypeError,
                    ValueError,
                ):
                    pass
            self._last_jitter_report_at = now
            self._max_timer_jitter_ms = 0.0
        self._schedule_pump()

    @Slot(int)
    def _on_bytes_written(self, _byte_count: int) -> None:
        self._schedule_pump()

    @Slot()
    def _schedule_pump(self) -> None:
        if (
            self._pump_scheduled
            or self._stopping
            or not self.started_ok
            or not self._refill_needed()
        ):
            return
        self._pump_scheduled = True
        try:
            queued = QMetaObject.invokeMethod(
                self,
                "_run_scheduled_pump",
                Qt.ConnectionType.QueuedConnection,
            )
        except RuntimeError:
            queued = False
        if not queued:
            self._pump_scheduled = False

    def _refill_needed(self) -> bool:
        if self._pending_pcm:
            return True
        sink = self._sink
        if sink is None:
            return False
        try:
            actual_frames = max(1, int(sink.bufferFrameCount()))
            free_frames = max(0, int(sink.framesFree()))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return True
        queued_frames = max(0, actual_frames - free_frames)
        target_frames = (
            min(PUSH_STANDBY_FRAMES, actual_frames)
            if self.standby_silence
            else actual_frames
        )
        missing_frames = min(
            free_frames,
            max(0, target_frames - queued_frames),
        )
        refill_threshold = min(
            self.response_frames,
            target_frames,
        )
        return queued_frames <= 0 or missing_frames >= refill_threshold

    @Slot()
    def _run_scheduled_pump(self) -> None:
        self._pump_scheduled = False
        if self._stopping or not self.started_ok:
            return
        self.pump()

    @Slot(object)
    def _on_state_changed(self, state: object) -> None:
        if (
            state == QAudio.State.IdleState
            and self._primed
            and not self._stopping
        ):
            self.stream._record_output_underrun()

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
                if self._pending_is_audio:
                    self._primed = True
                if self._pending_pcm:
                    return
                self._pending_is_audio = False

            actual_frames = max(1, int(sink.bufferFrameCount()))
            free_frames = max(0, int(sink.framesFree()))
            queued_frames = max(0, actual_frames - free_frames)
            if self._primed and queued_frames <= 0 and not self._stopping:
                self.stream._record_output_underrun()
            target_frames = (
                min(PUSH_STANDBY_FRAMES, actual_frames)
                if self.standby_silence
                else actual_frames
            )
            missing_frames = min(
                free_frames,
                max(0, target_frames - queued_frames),
            )
            refill_threshold = min(
                self.response_frames,
                target_frames,
            )
            if (
                queued_frames > 0
                and missing_frames < refill_threshold
            ):
                return
            if missing_frames <= 0:
                return

            remaining_frames = missing_frames
            while remaining_frames > 0:
                frame_count = min(
                    self.chunk_frames,
                    remaining_frames,
                )
                is_audio = False
                if self.standby_silence:
                    pcm = bytes(
                        frame_count
                        * max(1, self.audio_format.bytesPerFrame())
                    )
                else:
                    pcm = self.stream.take_pcm_frames(
                        frame_count,
                        pad_silence=False,
                    )
                    is_audio = bool(pcm)
                if not pcm:
                    if queued_frames <= 0:
                        self.stream._record_supply_shortage()
                        if self._primed and not self._stopping:
                            self.stream._record_output_underrun(
                                producer_starved=True
                            )
                    return
                written = int(output_device.write(pcm))
                if written < 0:
                    self.error = "Audio output rejected PCM data"
                    self.stream._record_supply_shortage()
                    return
                if written > 0 and is_audio:
                    self._primed = True
                if written < len(pcm):
                    self._pending_pcm = pcm[max(0, written):]
                    self._pending_is_audio = is_audio
                    return
                remaining_frames -= frame_count
        except Exception as exc:
            self.error = str(exc)
            self.stream._record_supply_shortage()
        finally:
            self._pumping = False

    def _start_fade(self, direction: int) -> None:
        sink = self._sink
        if sink is None:
            if direction < 0:
                self._finish_stop()
            return
        if self._fade_timer is not None:
            self._fade_timer.stop()
        self._fade_direction = 1 if direction > 0 else -1
        self._fade_step = 0
        timer = QTimer(self)
        timer.setTimerType(Qt.TimerType.PreciseTimer)
        timer.setInterval(max(1, int(self.handoff_fade_interval_ms)))
        timer.timeout.connect(self._advance_fade)
        self._fade_timer = timer
        timer.start()

    @Slot()
    def _advance_fade(self) -> None:
        sink = self._sink
        if sink is None:
            self._finish_stop()
            return
        self._fade_step += 1
        progress = min(1.0, self._fade_step / OUTPUT_FADE_STEPS)
        volume = progress if self._fade_direction > 0 else 1.0 - progress
        sink.setVolume(max(0.0, min(1.0, volume)))
        if progress < 1.0:
            return
        if self._fade_timer is not None:
            self._fade_timer.stop()
            self._fade_timer = None
        if self._fade_direction < 0:
            self._finish_stop()

    @Slot()
    def pause_for_handoff(self) -> None:
        self.handoff_ready.clear()
        try:
            self._stopping = True
            if self._timer is not None:
                self._timer.stop()
            output_device = self._output_device
            if output_device is not None and self._bytes_written_connected:
                try:
                    output_device.bytesWritten.disconnect(
                        self._on_bytes_written
                    )
                except (AttributeError, RuntimeError, TypeError):
                    pass
                self._bytes_written_connected = False
            sink = self._sink
            if sink is None:
                self.handoff_frames = 0
            else:
                actual_frames = max(1, int(sink.bufferFrameCount()))
                free_frames = max(0, int(sink.framesFree()))
                self.handoff_frames = max(
                    0,
                    actual_frames - free_frames,
                )
        finally:
            self.handoff_ready.set()

    @Slot()
    def resume_after_handoff(self) -> None:
        self.handoff_ready.clear()
        try:
            output_device = self._output_device
            if output_device is not None and not self._bytes_written_connected:
                try:
                    output_device.bytesWritten.connect(
                        self._on_bytes_written
                    )
                    self._bytes_written_connected = True
                except (AttributeError, RuntimeError, TypeError):
                    pass
            self._stopping = False
            if self._timer is not None:
                self._timer.start()
            self.pump()
        finally:
            self.handoff_ready.set()

    @Slot()
    def activate_handoff(self) -> None:
        self.handoff_ready.clear()
        try:
            sink = self._sink
            if sink is None:
                return
            self.standby_silence = False
            self._primed = False
            if self.start_muted:
                self._start_fade(1)
            self.pump()
        finally:
            self.handoff_ready.set()

    @Slot()
    def begin_handoff_fade_out(self) -> None:
        self._start_fade(-1)

    @Slot()
    def stop_output(self) -> None:
        self._stopping = True
        self._finish_stop()

    def _finish_stop(self) -> None:
        try:
            if self._fade_timer is not None:
                self._fade_timer.stop()
                self._fade_timer = None
            if self._timer is not None:
                self._timer.stop()
                self._timer = None
            output_device = self._output_device
            if output_device is not None and self._bytes_written_connected:
                try:
                    output_device.bytesWritten.disconnect(self._on_bytes_written)
                except (AttributeError, RuntimeError, TypeError):
                    pass
                self._bytes_written_connected = False
            if self._sink is not None:
                try:
                    self._sink.stateChanged.disconnect(self._on_state_changed)
                except (AttributeError, RuntimeError, TypeError):
                    pass
            self._output_device = None
            self._pending_pcm = b""
            self._pending_is_audio = False
            self._pump_scheduled = False
            if self._sink is not None:
                self._sink.reset()
                self._sink = None
            self.started_ok = False
            self._primed = False
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
        self._requested_qt_frames = DEFAULT_QT_AUDIO_FRAMES
        self.pipeline_tuning = AudioPipelineTuning()
        self._audio_device = None
        self._audio_format: QAudioFormat | None = None
        self.last_error = ""
        self._runtime_callbacks: dict[
            int,
            Callable[[int, int, int, int, int, str], None],
        ] = {}
        self._active_clients: set[int] = set()
        self._idle_shutdown_timer: threading.Timer | None = None
        self._idle_shutdown_generation = 0

    def start(self) -> bool:
        with self._lock:
            self._cancel_idle_shutdown_locked()
            if self._output_worker is not None:
                return True
            return self._start_sink_locked()

    def new_client_id(self) -> int:
        with self._lock:
            self._next_client_id += 1
            return self._next_client_id

    def configure_audio_settings(
        self,
        qt_frames: int,
        buffer_frames: int,
        response_frames: int,
        chunk_frames: int,
        fallback_interval_ms: int,
    ) -> bool:
        tuning = AudioRuntimeTuning(
            qt_frames=qt_frames,
            buffer_frames=buffer_frames,
            response_frames=response_frames,
            chunk_frames=chunk_frames,
            fallback_interval_ms=fallback_interval_ms,
        ).normalized()
        callbacks: tuple[
            Callable[[int, int, int, int, int, str], None],
            ...,
        ] = ()
        with self._lock:
            current = self._current_runtime_tuning_locked()
            if tuning == current:
                return True
            if self._output_worker is None:
                self.buffer_frames = tuning.buffer_frames
                self.qt_frames = tuning.qt_frames
                self._requested_qt_frames = tuning.qt_frames
                self.pipeline_tuning = tuning.pipeline
                self.stream.set_buffer_frames_live(tuning.buffer_frames)
                self.stream.set_pipeline_tuning_live(
                    tuning.response_frames,
                    tuning.chunk_frames,
                )
            elif not self._apply_runtime_tuning_locked(tuning):
                return False
            callbacks = tuple(self._runtime_callbacks.values())
            applied = self._current_runtime_tuning_locked()
        for callback in callbacks:
            try:
                callback(
                    applied.qt_frames,
                    applied.buffer_frames,
                    applied.response_frames,
                    applied.chunk_frames,
                    applied.fallback_interval_ms,
                    "",
                )
            except Exception:
                continue
        return True

    def register_client(
        self,
        client_id: int,
        callback: (
            Callable[[int, int, int, int, int, str], None] | None
        ),
    ) -> None:
        with self._lock:
            self._cancel_idle_shutdown_locked()
            self._active_clients.add(int(client_id))
            if callback is not None:
                self._runtime_callbacks[int(client_id)] = callback
            else:
                self._runtime_callbacks.pop(int(client_id), None)
            tuning = self._current_runtime_tuning_locked()
        if callback is not None:
            try:
                callback(
                    tuning.qt_frames,
                    tuning.buffer_frames,
                    tuning.response_frames,
                    tuning.chunk_frames,
                    tuning.fallback_interval_ms,
                    "",
                )
            except Exception:
                pass

    def unregister_client(self, client_id: int) -> None:
        with self._lock:
            self._active_clients.discard(int(client_id))
            self._runtime_callbacks.pop(int(client_id), None)
            if not self._active_clients:
                self._schedule_idle_shutdown_locked()

    def shutdown(self) -> None:
        with self._lock:
            self._cancel_idle_shutdown_locked()
            self._stop_output_locked()
            self.stream.close()

    def _cancel_idle_shutdown_locked(self) -> None:
        self._idle_shutdown_generation += 1
        timer = self._idle_shutdown_timer
        self._idle_shutdown_timer = None
        if timer is not None:
            timer.cancel()

    def _schedule_idle_shutdown_locked(self) -> None:
        self._cancel_idle_shutdown_locked()
        generation = self._idle_shutdown_generation
        timer = threading.Timer(
            AUDIO_IDLE_SHUTDOWN_SECONDS,
            self._stop_idle_output,
            args=(generation,),
        )
        timer.daemon = True
        self._idle_shutdown_timer = timer
        timer.start()

    def _stop_idle_output(self, generation: int | None = None) -> None:
        with self._lock:
            if (
                generation is not None
                and generation != self._idle_shutdown_generation
            ):
                return
            self._idle_shutdown_timer = None
            if self._active_clients:
                return
            self._stop_output_locked()
            self.stream.stop_worker()
            self.stream.clear_metrics()

    def _stop_output_locked(self) -> None:
        worker = self._output_worker
        thread = self._output_thread
        self._output_worker = None
        self._output_thread = None
        self._stop_output_worker(worker, thread)

    @staticmethod
    def _stop_output_worker(
        worker: _PushAudioOutput | None,
        thread: QThread | None,
    ) -> None:
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

    @staticmethod
    def _invoke_handoff(
        worker: _PushAudioOutput,
        method: str,
    ) -> bool:
        worker.handoff_ready.clear()
        try:
            invoked = QMetaObject.invokeMethod(
                worker,
                method,
                Qt.ConnectionType.QueuedConnection,
            )
        except RuntimeError:
            return False
        return bool(invoked) and worker.handoff_ready.wait(1.0)

    def _start_output_locked(
        self,
        requested_frames: int,
        *,
        start_muted: bool,
        standby_silence: bool = False,
    ) -> bool:
        device = self._audio_device
        audio_format = self._audio_format
        if device is None or audio_format is None:
            self.last_error = "Audio output format is not configured"
            return False
        requested_frames = normalize_qt_audio_frames(requested_frames)
        thread = QThread()
        worker = _PushAudioOutput(
            self.stream,
            device,
            audio_format,
            requested_frames,
            response_frames=self.pipeline_tuning.response_frames,
            chunk_frames=self.pipeline_tuning.chunk_frames,
            fallback_interval_ms=(
                self.pipeline_tuning.fallback_interval_ms
            ),
            start_muted=start_muted,
            standby_silence=standby_silence,
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
            return False
        self._output_thread = thread
        self._output_worker = worker
        self._requested_qt_frames = requested_frames
        self.qt_frames = worker.actual_sink_frames
        self.last_error = ""
        return True

    def _recreate_output_locked(self, requested_frames: int) -> bool:
        requested_frames = normalize_qt_audio_frames(requested_frames)
        previous_worker = self._output_worker
        previous_thread = self._output_thread
        previous_frames = self._requested_qt_frames
        previous_actual_frames = self.qt_frames
        if previous_worker is None or previous_thread is None:
            return self._start_output_locked(
                requested_frames,
                start_muted=False,
            )
        if not self._start_output_locked(
            requested_frames,
            start_muted=True,
            standby_silence=True,
        ):
            return False
        next_worker = self._output_worker
        next_thread = self._output_thread
        assert next_worker is not None
        assert next_thread is not None
        if not self._invoke_handoff(
            previous_worker,
            "pause_for_handoff",
        ):
            self._output_worker = previous_worker
            self._output_thread = previous_thread
            self._requested_qt_frames = previous_frames
            self.qt_frames = previous_actual_frames
            self._stop_output_worker(next_worker, next_thread)
            self.last_error = "The previous audio output could not be paused"
            return False
        handoff_frames = max(0, int(previous_worker.handoff_frames))
        sample_rate = max(1, int(self.stream.sample_rate))
        handoff_milliseconds = (handoff_frames * 1_000.0) / sample_rate
        fade_interval_ms = max(
            1,
            math.ceil(handoff_milliseconds / OUTPUT_FADE_STEPS),
        )
        previous_worker.handoff_fade_interval_ms = fade_interval_ms
        next_worker.handoff_fade_interval_ms = fade_interval_ms
        if not self._invoke_handoff(next_worker, "activate_handoff"):
            self._invoke_handoff(
                previous_worker,
                "resume_after_handoff",
            )
            self._output_worker = previous_worker
            self._output_thread = previous_thread
            self._requested_qt_frames = previous_frames
            self.qt_frames = previous_actual_frames
            self._stop_output_worker(next_worker, next_thread)
            self.last_error = "The new audio output could not be activated"
            return False
        try:
            QMetaObject.invokeMethod(
                previous_worker,
                "begin_handoff_fade_out",
                Qt.ConnectionType.QueuedConnection,
            )
        except RuntimeError:
            pass
        previous_worker.stopped.wait(
            max(0.1, handoff_milliseconds / 1_000.0 + 0.1)
        )
        self._stop_output_worker(previous_worker, previous_thread)
        self.last_error = ""
        return True

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

    def _apply_pipeline_tuning_live_locked(
        self,
        tuning: AudioPipelineTuning,
    ) -> bool:
        try:
            tuning = tuning.normalized()
            self.stream.set_pipeline_tuning_live(
                tuning.response_frames,
                tuning.chunk_frames,
            )
            worker = self._output_worker
            if worker is not None:
                worker.tuning_requested.emit(
                    tuning.response_frames,
                    tuning.chunk_frames,
                    tuning.fallback_interval_ms,
                )
            self.pipeline_tuning = tuning
            self.last_error = ""
            return True
        except Exception as exc:
            self.last_error = str(exc)
            return False

    def _current_runtime_tuning_locked(self) -> AudioRuntimeTuning:
        return AudioRuntimeTuning(
            qt_frames=self._requested_qt_frames,
            buffer_frames=self.buffer_frames,
            response_frames=self.pipeline_tuning.response_frames,
            chunk_frames=self.pipeline_tuning.chunk_frames,
            fallback_interval_ms=(
                self.pipeline_tuning.fallback_interval_ms
            ),
        ).normalized()

    def _apply_runtime_tuning_locked(
        self,
        tuning: AudioRuntimeTuning,
    ) -> bool:
        tuning = tuning.normalized()
        current = self._current_runtime_tuning_locked()
        if (
            tuning.buffer_frames != current.buffer_frames
            and not self._apply_buffer_frames_live_locked(
                tuning.buffer_frames
            )
        ):
            return False
        if tuning.pipeline != current.pipeline:
            if not self._apply_pipeline_tuning_live_locked(
                tuning.pipeline
            ):
                if tuning.buffer_frames != current.buffer_frames:
                    self._apply_buffer_frames_live_locked(
                        current.buffer_frames
                    )
                return False
        if tuning.qt_frames != current.qt_frames:
            if not self._recreate_output_locked(tuning.qt_frames):
                self._apply_buffer_frames_live_locked(
                    current.buffer_frames
                )
                self._apply_pipeline_tuning_live_locked(
                    current.pipeline
                )
                return False
        return True

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
        self._audio_device = device
        self._audio_format = audio_format
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
        if not self._start_output_locked(
            self._requested_qt_frames,
            start_muted=False,
        ):
            self.stream.stop_worker()
            self._audio_device = None
            self._audio_format = None
            return False
        self.stream.clear_metrics()
        self.last_error = ""
        return True

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


class _AudioProcessCommandReceiver(QObject):
    commands_received = Signal(object)

    def __init__(self, command_queue) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self._command_queue = command_queue
        self._thread = threading.Thread(
            target=self._receive_commands,
            name="SoftwareSynthProcessCommands",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def _receive_commands(self) -> None:
        while True:
            try:
                command = self._command_queue.get()
            except (EOFError, OSError):
                return
            batch = [command]
            while len(batch) < 256:
                try:
                    batch.append(self._command_queue.get_nowait())
                except queue.Empty:
                    break
                except (EOFError, OSError):
                    break
            self.commands_received.emit(batch)
            if any(item[1] == "shutdown" for item in batch):
                return


class _AudioProcessController(QObject):
    def __init__(self, response_queue) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.response_queue = response_queue
        self.engine = SoftwareSynthEngine()

    @Slot(object)
    def handle_commands(self, commands: object) -> None:
        for request_id, action, arguments in commands:  # type: ignore[union-attr]
            try:
                result = self._handle_command(
                    str(action),
                    tuple(arguments),
                )
            except Exception as exc:
                if request_id is not None:
                    self._respond(
                        int(request_id),
                        False,
                        None,
                        str(exc) or exc.__class__.__name__,
                    )
                else:
                    self.response_queue.put(
                        (
                            "process_error",
                            str(exc) or exc.__class__.__name__,
                        )
                    )
                continue
            if request_id is not None:
                self._respond(int(request_id), True, result, "")
            if action == "shutdown":
                QTimer.singleShot(0, QCoreApplication.quit)
                return

    def _handle_command(
        self,
        action: str,
        arguments: tuple[object, ...],
    ) -> object:
        if action == "configure":
            changed = self.engine.configure_audio_settings(
                *map(int, arguments)
            )
            return changed, self.engine.last_error
        if action == "start":
            started = self.engine.start()
            return started, self.engine.last_error
        if action == "register":
            client_id = int(arguments[0])
            self.engine.register_client(
                client_id,
                lambda qt, buffer, response, chunk, fallback, reason, cid=client_id: (
                    self.response_queue.put(
                        (
                            "runtime",
                            cid,
                            qt,
                            buffer,
                            response,
                            chunk,
                            fallback,
                            reason,
                        )
                    )
                ),
            )
            return True
        if action == "unregister":
            self.engine.unregister_client(int(arguments[0]))
            return True
        if action == "note_on":
            self.engine.stream.note_on(
                int(arguments[0]),
                int(arguments[1]),
                int(arguments[2]),
                int(arguments[3]),
                str(arguments[4]),
            )
            return True
        if action == "note_off":
            self.engine.stream.note_off(
                int(arguments[0]),
                int(arguments[1]),
                int(arguments[2]),
            )
            return True
        if action == "sustain":
            self.engine.stream.set_sustain(
                int(arguments[0]),
                int(arguments[1]),
                bool(arguments[2]),
            )
            return True
        if action == "release_all":
            self.engine.stream.release_all(
                int(arguments[0]),
                (
                    None
                    if arguments[1] is None
                    else int(arguments[1])
                ),
                immediate=bool(arguments[2]),
                release_seconds=(
                    None
                    if arguments[3] is None
                    else float(arguments[3])
                ),
            )
            return True
        if action == "metrics":
            return self.engine.stream.metrics_snapshot()
        if action == "shutdown":
            self.engine.shutdown()
            return True
        if action == "ping":
            return True
        raise ValueError(f"Unsupported audio process command: {action}")

    def _respond(
        self,
        request_id: int,
        ok: bool,
        result: object,
        error: str,
    ) -> None:
        self.response_queue.put(
            ("response", request_id, bool(ok), result, str(error))
        )


def _software_synth_process_main(
    command_queue,  # type: ignore[no-untyped-def]
    response_queue,  # type: ignore[no-untyped-def]
    ready_event,  # type: ignore[no-untyped-def]
    parent_pid: int,
) -> None:
    start_parent_process_watchdog(parent_pid, 1.0)
    application = QCoreApplication([])
    controller = _AudioProcessController(response_queue)
    receiver = _AudioProcessCommandReceiver(command_queue)
    receiver.commands_received.connect(
        controller.handle_commands,
        Qt.ConnectionType.QueuedConnection,
    )
    receiver.start()
    ready_event.set()
    try:
        application.exec()
    finally:
        controller.engine.shutdown()
        response_queue.put(("stopped",))


class _PendingAudioProcessRequest:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.ok = False
        self.result: object = None
        self.error = ""


class SoftwareSynthProcessHost:
    """Parent-process proxy for the isolated software synthesizer."""

    def __init__(self) -> None:
        self._context = multiprocessing.get_context("spawn")
        self._lifecycle_lock = threading.RLock()
        self._pending_lock = threading.Lock()
        self._callback_lock = threading.Lock()
        self._command_queue = None
        self._response_queue = None
        self._process: multiprocessing.Process | None = None
        self._listener_thread: threading.Thread | None = None
        self._next_request_id = 0
        self._next_client_id = 0
        self._pending: dict[int, _PendingAudioProcessRequest] = {}
        self._runtime_callbacks: dict[
            int,
            Callable[[int, int, int, int, int, str], None],
        ] = {}
        self.qt_frames = DEFAULT_QT_AUDIO_FRAMES
        self.buffer_frames = DEFAULT_AUDIO_BUFFER_FRAMES
        self.response_frames = DEFAULT_AUDIO_RESPONSE_FRAMES
        self.chunk_frames = DEFAULT_AUDIO_CHUNK_FRAMES
        self.fallback_interval_ms = DEFAULT_AUDIO_FALLBACK_INTERVAL_MS
        self.last_error = ""

    @property
    def stream(self) -> SoftwareSynthProcessHost:
        return self

    def configure_audio_settings(
        self,
        qt_frames: int,
        buffer_frames: int,
        response_frames: int,
        chunk_frames: int,
        fallback_interval_ms: int,
    ) -> bool:
        ok, result, error = self._request(
            "configure",
            (
                qt_frames,
                buffer_frames,
                response_frames,
                chunk_frames,
                fallback_interval_ms,
            ),
        )
        if not ok:
            self.last_error = error
            return False
        changed, detail = result  # type: ignore[misc]
        self.last_error = str(detail)
        return bool(changed)

    def start(self) -> bool:
        ok, result, error = self._request("start")
        if not ok:
            self.last_error = error
            return False
        started, detail = result  # type: ignore[misc]
        self.last_error = str(detail)
        return bool(started)

    def new_client_id(self) -> int:
        with self._lifecycle_lock:
            self._next_client_id += 1
            return self._next_client_id

    def register_client(
        self,
        client_id: int,
        callback: (
            Callable[[int, int, int, int, int, str], None] | None
        ),
    ) -> None:
        client_id = int(client_id)
        with self._callback_lock:
            if callback is None:
                self._runtime_callbacks.pop(client_id, None)
            else:
                self._runtime_callbacks[client_id] = callback
        ok, _result, error = self._request(
            "register",
            (client_id,),
        )
        if not ok:
            with self._callback_lock:
                self._runtime_callbacks.pop(client_id, None)
            raise RuntimeError(error)

    def unregister_client(self, client_id: int) -> None:
        client_id = int(client_id)
        self._send("unregister", (client_id,))
        with self._callback_lock:
            self._runtime_callbacks.pop(client_id, None)

    def note_on(
        self,
        client_id: int,
        channel: int,
        note: int,
        velocity: int,
        source: str,
    ) -> None:
        self._send(
            "note_on",
            (client_id, channel, note, velocity, source),
        )

    def note_off(
        self,
        client_id: int,
        channel: int,
        note: int,
    ) -> None:
        self._send("note_off", (client_id, channel, note))

    def set_sustain(
        self,
        client_id: int,
        channel: int,
        enabled: bool,
    ) -> None:
        self._send("sustain", (client_id, channel, bool(enabled)))

    def release_all(
        self,
        client_id: int,
        channel: int | None = None,
        *,
        immediate: bool = False,
        release_seconds: float | None = None,
    ) -> None:
        self._send(
            "release_all",
            (
                client_id,
                channel,
                bool(immediate),
                release_seconds,
            ),
        )

    def metrics_snapshot(self) -> AudioSupplyMetrics:
        ok, result, _error = self._request("metrics")
        if ok and isinstance(result, AudioSupplyMetrics):
            return result
        return AudioSupplyMetrics((), ())

    def shutdown(self) -> None:
        with self._lifecycle_lock:
            process = self._process
        if process is None:
            return
        if process.is_alive():
            self._request("shutdown", timeout=3.0)
            process.join(timeout=3.0)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1.0)
        self._close_process_resources(process)

    def _request(
        self,
        action: str,
        arguments: tuple[object, ...] = (),
        *,
        timeout: float = 5.0,
    ) -> tuple[bool, object, str]:
        if not self._ensure_process():
            return False, None, self.last_error
        with self._pending_lock:
            self._next_request_id += 1
            request_id = self._next_request_id
            pending = _PendingAudioProcessRequest()
            self._pending[request_id] = pending
        command_queue = self._command_queue
        assert command_queue is not None
        try:
            command_queue.put((request_id, action, arguments))
        except (OSError, ValueError) as exc:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            return False, None, str(exc)
        if not pending.event.wait(max(0.1, float(timeout))):
            with self._pending_lock:
                self._pending.pop(request_id, None)
            return (
                False,
                None,
                f"Audio process did not respond to {action}",
            )
        return pending.ok, pending.result, pending.error

    def _send(
        self,
        action: str,
        arguments: tuple[object, ...] = (),
    ) -> bool:
        if not self._ensure_process():
            return False
        command_queue = self._command_queue
        assert command_queue is not None
        try:
            command_queue.put((None, action, arguments))
            return True
        except (OSError, ValueError) as exc:
            self.last_error = str(exc)
            return False

    def _ensure_process(self) -> bool:
        with self._lifecycle_lock:
            process = self._process
            if process is not None and process.is_alive():
                return True
            if process is not None:
                self._close_process_resources(process)
            command_queue = self._context.Queue()
            response_queue = self._context.Queue()
            ready_event = self._context.Event()
            process = self._context.Process(
                target=_software_synth_process_main,
                args=(
                    command_queue,
                    response_queue,
                    ready_event,
                    os.getpid(),
                ),
                name="SoftwareSynthProcess",
                daemon=True,
            )
            try:
                process.start()
                if process.pid is None:
                    raise RuntimeError(
                        "Software synthesizer process has no PID"
                    )
                register_child_process(process.pid)
            except Exception as exc:
                self.last_error = str(exc)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=1.0)
                command_queue.close()
                response_queue.close()
                return False
            self._command_queue = command_queue
            self._response_queue = response_queue
            self._process = process
            listener = threading.Thread(
                target=self._listen,
                args=(process, response_queue),
                name="SoftwareSynthProcessResponses",
                daemon=True,
            )
            self._listener_thread = listener
            listener.start()
        if not ready_event.wait(5.0):
            self.last_error = "Software synthesizer process did not start"
            if process.is_alive():
                process.terminate()
                process.join(timeout=1.0)
            self._close_process_resources(process)
            return False
        self.last_error = ""
        return True

    def _listen(
        self,
        process: multiprocessing.Process,
        response_queue,  # type: ignore[no-untyped-def]
    ) -> None:
        while True:
            try:
                message = response_queue.get(timeout=0.1)
            except queue.Empty:
                if not process.is_alive():
                    break
                continue
            except (EOFError, OSError, ValueError):
                break
            message_type = message[0]
            if message_type == "response":
                self._complete_request(
                    int(message[1]),
                    bool(message[2]),
                    message[3],
                    str(message[4]),
                )
            elif message_type == "runtime":
                self._notify_runtime(message)
            elif message_type == "process_error":
                self.last_error = str(message[1])
            elif message_type == "stopped":
                break
        self._fail_pending("Software synthesizer process stopped")

    def _complete_request(
        self,
        request_id: int,
        ok: bool,
        result: object,
        error: str,
    ) -> None:
        with self._pending_lock:
            pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        pending.ok = bool(ok)
        pending.result = result
        pending.error = str(error)
        pending.event.set()

    def _notify_runtime(self, message: tuple[object, ...]) -> None:
        client_id = int(message[1])
        self.qt_frames = int(message[2])
        self.buffer_frames = int(message[3])
        self.response_frames = int(message[4])
        self.chunk_frames = int(message[5])
        self.fallback_interval_ms = int(message[6])
        with self._callback_lock:
            callback = self._runtime_callbacks.get(client_id)
        if callback is None:
            return
        try:
            callback(
                int(message[2]),
                int(message[3]),
                int(message[4]),
                int(message[5]),
                int(message[6]),
                str(message[7]),
            )
        except Exception:
            pass

    def _fail_pending(self, error: str) -> None:
        with self._pending_lock:
            pending_requests = tuple(self._pending.values())
            self._pending.clear()
        for pending in pending_requests:
            pending.error = str(error)
            pending.event.set()

    def _close_process_resources(
        self,
        process: multiprocessing.Process,
    ) -> None:
        with self._lifecycle_lock:
            if self._process is not process:
                return
            command_queue = self._command_queue
            response_queue = self._response_queue
            self._process = None
            self._command_queue = None
            self._response_queue = None
            self._listener_thread = None
        for target_queue in (command_queue, response_queue):
            if target_queue is None:
                continue
            try:
                target_queue.close()
            except (OSError, ValueError):
                pass
        self._fail_pending("Software synthesizer process stopped")


_engine_lock = threading.Lock()
_engine: SoftwareSynthProcessHost | None = None


def shared_software_synth() -> SoftwareSynthProcessHost:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = SoftwareSynthProcessHost()
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
        on_runtime_changed: (
            Callable[[int, int, int, int, int, str], None] | None
        ) = None,
        qt_frames: int = DEFAULT_QT_AUDIO_FRAMES,
        buffer_frames: int = DEFAULT_AUDIO_BUFFER_FRAMES,
        response_frames: int = DEFAULT_AUDIO_RESPONSE_FRAMES,
        chunk_frames: int = DEFAULT_AUDIO_CHUNK_FRAMES,
        fallback_interval_ms: int = DEFAULT_AUDIO_FALLBACK_INTERVAL_MS,
    ) -> None:
        self.sound_source = normalize_sound_source(sound_source)
        tuning = AudioRuntimeTuning(
            qt_frames=qt_frames,
            buffer_frames=buffer_frames,
            response_frames=response_frames,
            chunk_frames=chunk_frames,
            fallback_interval_ms=fallback_interval_ms,
        ).normalized()
        self.qt_frames = tuning.qt_frames
        self.buffer_frames = tuning.buffer_frames
        self.response_frames = tuning.response_frames
        self.chunk_frames = tuning.chunk_frames
        self.fallback_interval_ms = tuning.fallback_interval_ms
        self.on_runtime_changed = on_runtime_changed
        self._engine: SoftwareSynthProcessHost | None = None
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
        if not engine.configure_audio_settings(
            self.qt_frames,
            self.buffer_frames,
            self.response_frames,
            self.chunk_frames,
            self.fallback_interval_ms,
        ):
            self._last_error = engine.last_error
            return False
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
            self._engine.release_all(
                self._client_id,
                release_seconds=STOP_RELEASE_SECONDS,
            )
            self._engine.unregister_client(self._client_id)
        self._engine = None
        self._client_id = None

    def set_sound_source(self, sound_source: str) -> None:
        self.sound_source = normalize_sound_source(sound_source)

    def set_audio_settings(
        self,
        qt_frames: int,
        buffer_frames: int,
        response_frames: int,
        chunk_frames: int,
        fallback_interval_ms: int,
    ) -> bool:
        tuning = AudioRuntimeTuning(
            qt_frames=qt_frames,
            buffer_frames=buffer_frames,
            response_frames=response_frames,
            chunk_frames=chunk_frames,
            fallback_interval_ms=fallback_interval_ms,
        ).normalized()
        self.qt_frames = tuning.qt_frames
        self.buffer_frames = tuning.buffer_frames
        self.response_frames = tuning.response_frames
        self.chunk_frames = tuning.chunk_frames
        self.fallback_interval_ms = tuning.fallback_interval_ms
        if self._engine is None:
            return True
        if self._engine.configure_audio_settings(
            tuning.qt_frames,
            tuning.buffer_frames,
            tuning.response_frames,
            tuning.chunk_frames,
            tuning.fallback_interval_ms,
        ):
            self._last_error = ""
            return True
        self._last_error = self._engine.last_error
        return False

    def _runtime_changed(
        self,
        qt_frames: int,
        buffer_frames: int,
        response_frames: int,
        chunk_frames: int,
        fallback_interval_ms: int,
        reason: str,
    ) -> None:
        self.qt_frames = max(1, int(qt_frames))
        self.buffer_frames = normalize_audio_buffer_frames(buffer_frames)
        self.response_frames = normalize_audio_response_frames(
            response_frames
        )
        self.chunk_frames = normalize_audio_chunk_frames(chunk_frames)
        self.fallback_interval_ms = normalize_audio_fallback_interval_ms(
            fallback_interval_ms
        )
        if self.on_runtime_changed is not None:
            self.on_runtime_changed(
                self.qt_frames,
                self.buffer_frames,
                self.response_frames,
                self.chunk_frames,
                self.fallback_interval_ms,
                str(reason),
            )

    def note_on(self, channel: int, note: int, velocity: int) -> None:
        if self._engine is not None and self._client_id is not None:
            self._engine.note_on(
                self._client_id,
                channel,
                note,
                velocity,
                self.sound_source,
            )

    def note_off(self, channel: int, note: int) -> None:
        if self._engine is not None and self._client_id is not None:
            self._engine.note_off(self._client_id, channel, note)

    def set_sustain(self, channel: int, enabled: bool) -> None:
        if self._engine is not None and self._client_id is not None:
            self._engine.set_sustain(self._client_id, channel, enabled)

    def release_all(self, channel: int | None = None) -> None:
        if self._engine is not None and self._client_id is not None:
            self._engine.release_all(self._client_id, channel)
