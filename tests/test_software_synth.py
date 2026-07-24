from __future__ import annotations

import inspect
import threading
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np
import software_synth
import sound_player
from audio_buffer import (
    AUDIO_BUFFER_FRAME_OPTIONS,
    QT_AUDIO_FRAME_OPTIONS,
    qt_audio_frame_ceiling,
)
from PySide6.QtMultimedia import QAudio
from software_synth import (
    AudioBufferDecision,
    AudioBufferAutoPolicy,
    AudioSupplyMetrics,
    QtAudioAutoPolicy,
    SoftwareSynthStream,
)


class SoftwareSynthTests(unittest.TestCase):
    class FakeSink:
        def __init__(self, state, error) -> None:  # type: ignore[no-untyped-def]
            self._state = state
            self._error = error

        def state(self):  # type: ignore[no-untyped-def]
            return self._state

        def error(self):  # type: ignore[no-untyped-def]
            return self._error

    def test_note_generates_pcm_and_releases_to_silence(self) -> None:
        stream = SoftwareSynthStream(sample_rate=44_100, channels=1)

        stream.note_on(1, 0, 69, 100, "piano")
        attack = stream.render(1_024)
        stream.note_off(1, 0, 69)
        stream.render(24_000)
        silence = stream.render(256)

        self.assertGreater(max(abs(sample) for sample in attack), 0.01)
        self.assertEqual(silence, [0.0] * 256)

    def test_note_commands_are_applied_by_the_audio_render_path(self) -> None:
        stream = SoftwareSynthStream(sample_rate=44_100, channels=1)

        stream.note_on(1, 0, 60, 100, "piano")
        self.assertEqual(stream._voices, {})

        stream.render(0)
        self.assertIn((1, 0, 60), stream._voices)
        self.assertFalse(hasattr(stream, "_lock"))

    def test_audio_workspaces_use_float32_and_are_reused(self) -> None:
        stream = SoftwareSynthStream(sample_rate=44_100, channels=2)
        workspace_ids = (
            id(stream._output_scratch),
            id(stream._interleaved_scratch),
            id(stream._phase_scratch),
            id(stream._sample_scratch),
            id(stream._limiter_magnitude_scratch),
        )

        stream.note_on(1, 0, 60, 100, "organ")
        stream.take_pcm_frames(256)
        stream.take_pcm_frames(256)

        self.assertEqual(software_synth.WAVETABLE_FLAT.dtype, np.float32)
        for workspace in (
            stream._output_scratch,
            stream._interleaved_scratch,
            stream._phase_scratch,
            stream._sample_scratch,
            stream._limiter_magnitude_scratch,
        ):
            self.assertEqual(workspace.dtype, np.float32)
        self.assertEqual(
            workspace_ids,
            (
                id(stream._output_scratch),
                id(stream._interleaved_scratch),
                id(stream._phase_scratch),
                id(stream._sample_scratch),
                id(stream._limiter_magnitude_scratch),
            ),
        )

    def test_each_selectable_source_has_a_distinct_waveform(self) -> None:
        rendered = {}
        for source in ("piano", "electric_piano", "organ", "synth"):
            stream = SoftwareSynthStream(sample_rate=44_100, channels=1)
            stream.note_on(1, 0, 60, 100, source)
            rendered[source] = stream.render(512)

        fingerprints = {
            tuple(round(sample, 5) for sample in samples[128:256])
            for samples in rendered.values()
        }
        self.assertEqual(len(fingerprints), 4)

    def test_piano_naturally_decays_to_silence_while_key_is_held(self) -> None:
        stream = SoftwareSynthStream(sample_rate=8_000, channels=1)
        stream.note_on(1, 0, 60, 100, "piano")

        stream.render(stream.sample_rate)
        early_envelope = next(iter(stream._voices.values())).envelope
        stream.render(stream.sample_rate * 3)
        late_envelope = next(iter(stream._voices.values())).envelope
        stream.render(stream.sample_rate * 4)
        silence = stream.render(128)

        self.assertGreater(early_envelope, late_envelope)
        self.assertEqual(stream._voices, {})
        self.assertEqual(silence, [0.0] * 128)

    def test_high_piano_notes_decay_faster_than_low_notes(self) -> None:
        stream = SoftwareSynthStream(sample_rate=8_000, channels=1)
        stream.note_on(1, 0, 36, 100, "piano")
        stream.note_on(1, 0, 84, 100, "piano")

        stream.render(stream.sample_rate * 6)

        self.assertIn((1, 0, 36), stream._voices)
        self.assertNotIn((1, 0, 84), stream._voices)

    def test_organ_still_sustains_while_key_is_held(self) -> None:
        stream = SoftwareSynthStream(sample_rate=8_000, channels=1)
        stream.note_on(1, 0, 60, 100, "organ")

        stream.render(stream.sample_rate * 10)
        held = stream.render(128)

        self.assertNotEqual(stream._voices, {})
        self.assertGreater(max(abs(sample) for sample in held), 0.01)

    def test_numpy_renderer_matches_preoptimization_reference(self) -> None:
        stream = SoftwareSynthStream(sample_rate=44_100, channels=1)
        stream.note_on(1, 0, 69, 100, "piano")

        samples = stream.render(16)
        voice = next(iter(stream._voices.values()))

        expected = [
            0.0,
            0.000547918675,
            0.001609007409,
            0.003150844578,
            0.004974443524,
            0.007028655199,
            0.009078025198,
            0.011064625634,
            0.012818400955,
            0.014302649667,
            0.015462820743,
            0.016327850735,
            0.016887435597,
            0.017276759564,
            0.017486216449,
            0.017681353592,
        ]
        np.testing.assert_allclose(samples, expected, rtol=0.0, atol=3e-9)
        self.assertAlmostEqual(voice.phase, 326.936961451247, places=4)
        self.assertAlmostEqual(voice.envelope, 0.090702947846, places=6)
        self.assertEqual(voice.stage, "attack")

    def test_pcm_frames_vectorize_stereo_int16_output(self) -> None:
        stream = SoftwareSynthStream(sample_rate=44_100, channels=2)
        stream.note_on(1, 0, 69, 100, "piano")

        pcm = np.frombuffer(stream.take_pcm_frames(256), dtype=np.int16).reshape(-1, 2)

        self.assertEqual(pcm.shape, (256, 2))
        np.testing.assert_array_equal(pcm[:, 0], pcm[:, 1])
        self.assertGreater(int(np.max(np.abs(pcm[:, 0]))), 0)

    def test_pcm_frames_vectorize_float_output(self) -> None:
        stream = SoftwareSynthStream(sample_rate=44_100, channels=1)
        stream.sample_format = software_synth.QAudioFormat.SampleFormat.Float
        stream.note_on(1, 0, 69, 100, "piano")

        pcm = np.frombuffer(stream.take_pcm_frames(256), dtype=np.float32)

        self.assertEqual(pcm.shape, (256,))
        self.assertGreater(float(np.max(np.abs(pcm))), 0.01)

    def test_pcm_frames_vectorize_int32_output(self) -> None:
        stream = SoftwareSynthStream(sample_rate=44_100, channels=2)
        stream.sample_format = software_synth.QAudioFormat.SampleFormat.Int32
        stream.note_on(1, 0, 69, 100, "piano")

        pcm = np.frombuffer(stream.take_pcm_frames(256), dtype=np.int32).reshape(-1, 2)

        self.assertEqual(pcm.shape, (256, 2))
        np.testing.assert_array_equal(pcm[:, 0], pcm[:, 1])
        self.assertGreater(int(np.max(np.abs(pcm[:, 0]))), 0)

    def test_pcm_frames_use_the_explicit_push_block_size(self) -> None:
        stream = SoftwareSynthStream(
            sample_rate=44_100,
            channels=2,
            buffer_frames=2_048,
        )
        stream.configure(
            44_100,
            2,
            software_synth.QAudioFormat.SampleFormat.Int16,
            2_048,
        )
        stream.note_on(1, 0, 69, 100, "piano")

        pcm = stream.take_pcm_frames(512)

        self.assertEqual(len(pcm), 512 * 2 * 2)

    def test_audio_worker_prefills_pcm_ring_before_audio_push(self) -> None:
        stream = SoftwareSynthStream(
            sample_rate=44_100,
            channels=1,
            buffer_frames=128,
        )
        stream.note_on(1, 0, 69, 100, "piano")
        try:
            self.assertTrue(stream.start_worker())
            pcm = np.frombuffer(stream.take_pcm_frames(128), dtype=np.int16)
            metrics = stream.metrics_snapshot()
        finally:
            stream.stop_worker()

        self.assertGreater(int(np.max(np.abs(pcm))), 0)
        self.assertTrue(metrics.synthesis_utilization)
        self.assertTrue(metrics.synthesis_durations)
        self.assertGreaterEqual(metrics.ring_buffer_bytes, 0)
        self.assertGreater(metrics.ring_target_bytes, 0)

    def test_audio_worker_replaces_prefilled_silence_when_note_arrives(self) -> None:
        stream = SoftwareSynthStream(
            sample_rate=44_100,
            channels=1,
            buffer_frames=128,
        )
        try:
            self.assertTrue(stream.start_worker())
            stream.note_on(1, 0, 69, 100, "piano")
            deadline = time.monotonic() + 1.0
            with stream._ring_condition:
                while (
                    stream._rendered_command_revision
                    != stream._command_revision
                    and time.monotonic() < deadline
                ):
                    stream._ring_condition.wait(
                        max(0.0, deadline - time.monotonic())
                    )
            pcm = np.frombuffer(stream.take_pcm_frames(128), dtype=np.int16)
        finally:
            stream.stop_worker()

        self.assertEqual(
            stream._rendered_command_revision,
            stream._command_revision,
        )
        self.assertGreater(int(np.max(np.abs(pcm))), 0)

    def test_audio_worker_refresh_preserves_existing_voice_phase(self) -> None:
        expected = SoftwareSynthStream(
            sample_rate=44_100,
            channels=1,
            buffer_frames=128,
        )
        expected.note_on(1, 0, 60, 100, "organ")
        expected.note_on(1, 0, 64, 100, "organ")
        first_expected = expected.take_pcm_frames(128)
        expected.note_on(1, 0, 67, 100, "organ")
        second_expected = expected.take_pcm_frames(128)

        stream = SoftwareSynthStream(
            sample_rate=44_100,
            channels=1,
            buffer_frames=128,
        )
        stream.note_on(1, 0, 60, 100, "organ")
        stream.note_on(1, 0, 64, 100, "organ")
        try:
            self.assertTrue(stream.start_worker())
            first_actual = stream.take_pcm_frames(128)
            deadline = time.monotonic() + 1.0
            with stream._ring_condition:
                while (
                    stream._pcm_ring_bytes < stream._target_ring_bytes()
                    and time.monotonic() < deadline
                ):
                    stream._ring_condition.wait(
                        max(0.0, deadline - time.monotonic())
                    )
            stream.note_on(1, 0, 67, 100, "organ")
            deadline = time.monotonic() + 1.0
            with stream._ring_condition:
                while (
                    stream._rendered_command_revision
                    != stream._command_revision
                    and time.monotonic() < deadline
                ):
                    stream._ring_condition.wait(
                        max(0.0, deadline - time.monotonic())
                    )
            second_actual = stream.take_pcm_frames(128)
        finally:
            stream.stop_worker()

        self.assertEqual(first_actual, first_expected)
        self.assertEqual(second_actual, second_expected)

    def test_large_reserve_uses_bounded_worker_chunks(self) -> None:
        stream = SoftwareSynthStream(
            sample_rate=44_100,
            channels=2,
            buffer_frames=8_192,
        )
        try:
            self.assertTrue(stream.start_worker())
            stream.note_on(1, 0, 69, 100, "piano")
            deadline = time.monotonic() + 1.0
            with stream._ring_condition:
                while (
                    stream._rendered_command_revision
                    != stream._command_revision
                    and time.monotonic() < deadline
                ):
                    stream._ring_condition.wait(
                        max(0.0, deadline - time.monotonic())
                    )
                chunk_sizes = tuple(
                    len(chunk)
                    for chunk in stream._pcm_ring
                )
        finally:
            stream.stop_worker()

        self.assertTrue(chunk_sizes)
        self.assertLessEqual(
            max(chunk_sizes),
            software_synth.LOW_LATENCY_AUDIO_FRAMES * 2 * 2,
        )

    def test_command_refresh_rebuilds_one_low_latency_push_block(self) -> None:
        stream = SoftwareSynthStream(
            sample_rate=48_000,
            channels=2,
            buffer_frames=8_192,
        )
        stream.configure(
            48_000,
            2,
            software_synth.QAudioFormat.SampleFormat.Float,
            8_192,
        )
        try:
            self.assertTrue(stream.start_worker())
            stream.note_on(1, 0, 60, 100, "piano")
            deadline = time.monotonic() + 1.0
            with stream._ring_condition:
                while (
                    stream._rendered_command_revision
                    != stream._command_revision
                    and time.monotonic() < deadline
                ):
                    stream._ring_condition.wait(
                        max(0.0, deadline - time.monotonic())
                    )
                first_chunk_frames = (
                    len(stream._pcm_ring[0]) // stream._frame_size()
                    if stream._pcm_ring
                    else 0
                )
        finally:
            stream.stop_worker()

        self.assertEqual(
            first_chunk_frames,
            software_synth.LOW_LATENCY_AUDIO_FRAMES,
        )

    def test_large_reserve_keeps_a_low_latency_push_floor(self) -> None:
        stream = SoftwareSynthStream(
            sample_rate=44_100,
            channels=2,
            buffer_frames=8_192,
        )

        stream.configure(
            44_100,
            2,
            software_synth.QAudioFormat.SampleFormat.Int16,
            8_192,
        )

        self.assertEqual(
            stream.minimum_effective_buffer_frames(),
            AUDIO_BUFFER_FRAME_OPTIONS[0],
        )
        self.assertEqual(
            stream._target_ring_bytes(),
            8_192 * 2 * 2,
        )

    def test_audio_metrics_distinguish_supply_delay_from_buffer_shortage(self) -> None:
        stream = SoftwareSynthStream(sample_rate=44_100, channels=1)

        stream._record_synthesis_utilization(1.25, 0.01)
        stream._record_supply_shortage()
        metrics = stream.metrics_snapshot()

        self.assertEqual(len(metrics.supply_delays), 1)
        self.assertEqual(len(metrics.shortages), 1)
        self.assertEqual(metrics.synthesis_durations[-1][1], 0.01)

    def test_output_underrun_is_marked_when_pcm_producer_was_empty(self) -> None:
        stream = SoftwareSynthStream(sample_rate=44_100, channels=1)
        now = time.monotonic()

        with patch(
            "software_synth.time.monotonic",
            side_effect=(now, now + 0.01),
        ):
            stream._record_output_underrun()
            stream._record_output_underrun(producer_starved=True)

        metrics = stream.metrics_snapshot()
        self.assertEqual(metrics.output_underruns, (now,))
        self.assertEqual(
            metrics.producer_starved_output_underruns,
            (now,),
        )

    def test_live_buffer_change_keeps_the_audio_worker_and_pcm_flowing(self) -> None:
        stream = SoftwareSynthStream(
            sample_rate=44_100,
            channels=1,
            buffer_frames=2_048,
        )
        stream.note_on(1, 0, 69, 100, "organ")
        try:
            self.assertTrue(stream.start_worker())
            worker = stream._worker_thread
            for frames in AUDIO_BUFFER_FRAME_OPTIONS:
                with self.subTest(frames=frames):
                    stream.set_buffer_frames_live(frames)
                    self.assertIs(stream._worker_thread, worker)
                    deadline = time.monotonic() + 1.0
                    with stream._ring_condition:
                        while (
                            stream._pcm_ring_bytes
                            < min(frames, software_synth.PUSH_WRITE_FRAMES) * 2
                            and time.monotonic() < deadline
                        ):
                            stream._ring_condition.wait(
                                max(0.0, deadline - time.monotonic())
                            )
                    pcm = np.frombuffer(stream.take_pcm_frames(128), dtype=np.int16)
                    self.assertEqual(stream.buffer_frames, frames)
                    self.assertEqual(len(pcm), 128)
                    self.assertGreater(int(np.max(np.abs(pcm))), 0)
        finally:
            stream.stop_worker()

        self.assertIs(stream._worker_thread, None)
        self.assertIsNotNone(worker)

    def test_live_buffer_change_keeps_push_output_untouched(self) -> None:
        engine = software_synth.SoftwareSynthEngine()
        output_worker = Mock()
        engine._output_worker = output_worker
        try:
            for frames in AUDIO_BUFFER_FRAME_OPTIONS:
                self.assertTrue(engine._apply_buffer_frames_live_locked(frames))
        finally:
            engine._output_worker = None
            engine.shutdown()

        self.assertIs(engine._output_worker, None)
        self.assertEqual(output_worker.method_calls, [])
        self.assertEqual(engine.buffer_frames, AUDIO_BUFFER_FRAME_OPTIONS[-1])
        self.assertEqual(
            engine.stream.buffer_frames,
            AUDIO_BUFFER_FRAME_OPTIONS[-1],
        )

    def test_push_output_fills_the_active_qt_queue_target(self) -> None:
        class FakeStream:
            def __init__(self) -> None:
                self.requests = []
                self.shortages = 0

            def take_pcm_frames(
                self,
                frame_count: int,
                *,
                pad_silence: bool = True,
            ) -> bytes:
                self.requests.append(frame_count)
                return bytes(frame_count * 4)

            def _record_supply_shortage(self) -> None:
                self.shortages += 1

        class FakeSink:
            def __init__(self) -> None:
                self.queued_frames = 0

            def state(self):  # type: ignore[no-untyped-def]
                return QAudio.State.ActiveState

            def error(self):  # type: ignore[no-untyped-def]
                return QAudio.Error.NoError

            def bufferFrameCount(self) -> int:
                return 2_048

            def framesFree(self) -> int:
                return 2_048 - self.queued_frames

        class FakeOutput:
            def __init__(self, sink: FakeSink) -> None:
                self.sink = sink
                self.writes = []

            def write(self, pcm: bytes) -> int:
                self.writes.append(pcm)
                self.sink.queued_frames += len(pcm) // 4
                return len(pcm)

        stream = FakeStream()
        sink = FakeSink()
        output = FakeOutput(sink)
        worker = software_synth._PushAudioOutput(
            stream,  # type: ignore[arg-type]
            Mock(),
            software_synth.QAudioFormat(),
            512,
        )
        worker._sink = sink  # type: ignore[assignment]
        worker._output_device = output
        worker.started_ok = True

        worker.pump()

        write_count = (
            sink.bufferFrameCount()
            + software_synth.PUSH_WRITE_FRAMES
            - 1
        ) // software_synth.PUSH_WRITE_FRAMES
        self.assertEqual(
            stream.requests,
            [software_synth.PUSH_WRITE_FRAMES] * write_count,
        )
        self.assertEqual(sink.queued_frames, sink.bufferFrameCount())
        self.assertEqual(len(output.writes), write_count)
        self.assertEqual(stream.shortages, 0)

    def test_qt_queue_candidates_include_low_latency_and_safe_sizes(self) -> None:
        self.assertEqual(
            QT_AUDIO_FRAME_OPTIONS,
            (128, 256, 512, 1_024, 2_048, 4_096),
        )
        self.assertEqual(qt_audio_frame_ceiling(100), 128)
        self.assertEqual(qt_audio_frame_ceiling(480), 512)
        self.assertEqual(qt_audio_frame_ceiling(512), 512)

    def test_push_output_waits_for_pcm_while_qt_still_has_audio(self) -> None:
        stream = Mock()
        stream.take_pcm_frames.return_value = b""
        sink = Mock()
        sink.state.return_value = QAudio.State.ActiveState
        sink.error.return_value = QAudio.Error.NoError
        sink.bufferFrameCount.return_value = 512
        sink.framesFree.return_value = 384
        output = Mock()

        worker = software_synth._PushAudioOutput(
            stream,
            Mock(),
            software_synth.QAudioFormat(),
            512,
        )
        worker._sink = sink
        worker._output_device = output
        worker.started_ok = True

        worker.pump()

        stream.take_pcm_frames.assert_called_once_with(
            software_synth.PUSH_WRITE_FRAMES,
            pad_silence=False,
        )
        stream._record_supply_shortage.assert_not_called()
        output.write.assert_not_called()

    def test_push_output_records_shortage_only_after_qt_queue_empties(self) -> None:
        stream = Mock()
        stream.take_pcm_frames.return_value = b""
        sink = Mock()
        sink.state.return_value = QAudio.State.ActiveState
        sink.error.return_value = QAudio.Error.NoError
        sink.bufferFrameCount.return_value = 512
        sink.framesFree.return_value = 512
        output = Mock()

        worker = software_synth._PushAudioOutput(
            stream,
            Mock(),
            software_synth.QAudioFormat(),
            512,
        )
        worker._sink = sink
        worker._output_device = output
        worker.started_ok = True

        worker.pump()

        stream._record_supply_shortage.assert_called_once_with()
        output.write.assert_not_called()

    def test_push_output_records_qt_underrun_after_primed_queue_empties(self) -> None:
        stream = Mock()
        stream.take_pcm_frames.return_value = b""
        sink = Mock()
        sink.state.return_value = QAudio.State.ActiveState
        sink.error.return_value = QAudio.Error.NoError
        sink.bufferFrameCount.return_value = 512
        sink.framesFree.return_value = 512

        worker = software_synth._PushAudioOutput(
            stream,
            Mock(),
            software_synth.QAudioFormat(),
            512,
        )
        worker._sink = sink
        worker._output_device = Mock()
        worker.started_ok = True
        worker._primed = True

        worker.pump()

        stream._record_output_underrun.assert_called()

    def test_software_synth_stream_has_no_qt_pull_interface(self) -> None:
        stream = SoftwareSynthStream()

        self.assertFalse(hasattr(stream, "readData"))
        self.assertFalse(hasattr(stream, "bytesAvailable"))
        source = inspect.getsource(software_synth._PushAudioOutput.start_output)
        self.assertIn("output_device = sink.start()", source)
        self.assertNotIn("sink.start(self.stream)", source)

    def test_auto_buffer_increases_after_three_recent_shortages(self) -> None:
        policy = AudioBufferAutoPolicy(now=0.0)
        metrics = AudioSupplyMetrics(
            shortages=(1.0, 2.0, 3.0),
            synthesis_utilization=(),
        )

        decision = policy.evaluate(3.0, 512, metrics)

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.frames, 1_024)
        self.assertIn("increased", decision.reason)

    def test_auto_buffer_increases_after_synthesis_supply_delays(self) -> None:
        policy = AudioBufferAutoPolicy(now=0.0)
        metrics = AudioSupplyMetrics(
            shortages=(),
            synthesis_utilization=(),
            supply_delays=(1.0, 2.0, 3.0),
        )

        decision = policy.evaluate(3.0, 512, metrics)

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.frames, 1_024)
        self.assertIn("3 synthesis delays", decision.reason)

    def test_auto_buffer_reduces_after_stable_low_cost_period(self) -> None:
        policy = AudioBufferAutoPolicy(now=0.0)
        metrics = AudioSupplyMetrics(
            shortages=(),
            synthesis_utilization=tuple(
                (float(second), 0.10)
                for second in range(1, 22)
            ),
        )

        decision = policy.evaluate(21.0, 2_048, metrics)

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.frames, 1_024)
        self.assertIn("reduced", decision.reason)

    def test_shortage_after_reduction_restores_previous_buffer(self) -> None:
        policy = AudioBufferAutoPolicy(now=0.0)
        low_cost_metrics = AudioSupplyMetrics(
            shortages=(),
            synthesis_utilization=tuple(
                (float(second), 0.10)
                for second in range(1, 22)
            ),
        )
        reduced = policy.evaluate(21.0, 2_048, low_cost_metrics)
        self.assertIsNotNone(reduced)

        restored = policy.evaluate(
            22.0,
            1_024,
            AudioSupplyMetrics(
                shortages=(22.0,),
                synthesis_utilization=((22.0, 0.10),),
            ),
        )

        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(restored.frames, 2_048)
        self.assertIn("restored", restored.reason)
        self.assertEqual(policy.downshift_block_until, 82.0)

    def test_auto_buffer_does_not_reduce_below_effective_pull_size(self) -> None:
        policy = AudioBufferAutoPolicy(now=0.0)
        metrics = AudioSupplyMetrics(
            shortages=(),
            synthesis_utilization=tuple(
                (float(second), 0.10)
                for second in range(1, 22)
            ),
        )

        decision = policy.evaluate(
            21.0,
            128,
            metrics,
            minimum_frames=128,
        )

        self.assertIsNone(decision)

    def test_auto_buffer_can_reduce_from_default_to_128_frames(self) -> None:
        policy = AudioBufferAutoPolicy(now=0.0)

        reduced_to_256 = policy.evaluate(
            21.0,
            512,
            AudioSupplyMetrics(
                shortages=(),
                synthesis_utilization=tuple(
                    (float(second), 0.10)
                    for second in range(1, 22)
                ),
            ),
            minimum_frames=128,
        )
        self.assertIsNotNone(reduced_to_256)
        assert reduced_to_256 is not None
        self.assertEqual(reduced_to_256.frames, 256)

        reduced_to_128 = policy.evaluate(
            42.0,
            256,
            AudioSupplyMetrics(
                shortages=(),
                synthesis_utilization=tuple(
                    (float(second), 0.10)
                    for second in range(22, 43)
                ),
            ),
            minimum_frames=128,
        )
        self.assertIsNotNone(reduced_to_128)
        assert reduced_to_128 is not None
        self.assertEqual(reduced_to_128.frames, 128)

    def test_auto_buffer_waits_after_qt_output_underrun_before_reducing(
        self,
    ) -> None:
        policy = AudioBufferAutoPolicy(now=0.0)
        metrics = AudioSupplyMetrics(
            shortages=(),
            synthesis_utilization=tuple(
                (float(second), 0.10)
                for second in range(1, 22)
            ),
            output_underruns=(20.0,),
        )

        decision = policy.evaluate(21.0, 2_048, metrics)

        self.assertIsNone(decision)

    @staticmethod
    def _active_metrics(
        start: int,
        end: int,
        *,
        underruns: tuple[float, ...] = (),
        currently_active: bool = False,
    ) -> AudioSupplyMetrics:
        return AudioSupplyMetrics(
            shortages=(),
            synthesis_utilization=(),
            output_underruns=underruns,
            audio_activity=tuple(
                float(second)
                for second in range(start, end + 1)
            ),
            currently_active_audio=currently_active,
        )

    def test_qt_policy_probes_down_to_128_before_learning_minimum(self) -> None:
        policy = QtAudioAutoPolicy(now=0.0)

        first = policy.evaluate(
            61.0,
            1_024,
            self._active_metrics(1, 61),
        )
        self.assertIsNotNone(first)
        assert first is not None
        self.assertEqual(first.frames, 512)
        self.assertIsNone(first.learned_minimum_frames)

        learned_512 = policy.evaluate(
            122.0,
            512,
            self._active_metrics(62, 122),
        )
        self.assertIsNotNone(learned_512)
        assert learned_512 is not None
        self.assertEqual(learned_512.frames, 512)
        self.assertEqual(learned_512.learned_minimum_frames, 512)

        second = policy.evaluate(
            183.0,
            512,
            self._active_metrics(123, 183),
        )
        self.assertIsNotNone(second)
        assert second is not None
        self.assertEqual(second.frames, 256)
        self.assertIsNone(second.learned_minimum_frames)

        learned_256 = policy.evaluate(
            244.0,
            256,
            self._active_metrics(184, 244),
        )
        self.assertIsNotNone(learned_256)
        assert learned_256 is not None
        self.assertEqual(learned_256.frames, 256)
        self.assertEqual(learned_256.learned_minimum_frames, 256)

        third = policy.evaluate(
            305.0,
            256,
            self._active_metrics(245, 305),
        )
        self.assertIsNotNone(third)
        assert third is not None
        self.assertEqual(third.frames, 128)
        self.assertIsNone(third.learned_minimum_frames)

        learned = policy.evaluate(
            366.0,
            128,
            self._active_metrics(306, 366),
        )
        self.assertIsNotNone(learned)
        assert learned is not None
        self.assertEqual(learned.frames, 128)
        self.assertEqual(learned.learned_minimum_frames, 128)

    def test_qt_policy_restores_failed_probe_after_one_underrun(self) -> None:
        policy = QtAudioAutoPolicy(now=0.0)
        reduced = policy.evaluate(
            61.0,
            1_024,
            self._active_metrics(1, 61),
        )
        self.assertIsNotNone(reduced)

        restored = policy.evaluate(
            62.0,
            512,
            self._active_metrics(62, 62, underruns=(62.0,)),
        )

        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual(restored.frames, 1_024)
        self.assertIsNone(restored.learned_minimum_frames)
        self.assertIn(512, policy.failed_candidates)

    def test_qt_policy_does_not_repeat_failed_probe_in_same_session(
        self,
    ) -> None:
        policy = QtAudioAutoPolicy(now=0.0)
        policy.evaluate(
            61.0,
            1_024,
            self._active_metrics(1, 61),
        )
        policy.evaluate(
            62.0,
            512,
            self._active_metrics(62, 62, underruns=(62.0,)),
        )
        repeated = policy.evaluate(
            123.0,
            1_024,
            self._active_metrics(63, 123),
        )

        self.assertIsNone(repeated)

    def test_qt_policy_retries_failed_value_in_new_session(self) -> None:
        policy = QtAudioAutoPolicy(
            minimum_stable_frames=1_024,
            now=0.0,
        )
        decision = policy.evaluate(
            61.0,
            1_024,
            self._active_metrics(1, 61),
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.frames, 512)

    def test_qt_policy_increases_after_repeated_output_underruns(self) -> None:
        policy = QtAudioAutoPolicy(now=0.0)
        decision = policy.evaluate(
            3.0,
            1_024,
            AudioSupplyMetrics(
                shortages=(),
                synthesis_utilization=(),
                output_underruns=(1.0, 2.0, 3.0),
            ),
        )

        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.frames, 2_048)
        self.assertEqual(decision.learned_minimum_frames, 2_048)

    def test_qt_policy_ignores_producer_starved_output_underruns(self) -> None:
        policy = QtAudioAutoPolicy(now=0.0)
        decision = policy.evaluate(
            3.0,
            1_024,
            AudioSupplyMetrics(
                shortages=(1.0, 2.0, 3.0),
                synthesis_utilization=(),
                output_underruns=(1.0, 2.0, 3.0),
                producer_starved_output_underruns=(1.0, 2.0, 3.0),
            ),
        )

        self.assertIsNone(decision)

    def test_qt_policy_returns_no_decision_at_maximum_queue(self) -> None:
        policy = QtAudioAutoPolicy(now=0.0)
        decision = policy.evaluate(
            3.0,
            QT_AUDIO_FRAME_OPTIONS[-1],
            AudioSupplyMetrics(
                shortages=(),
                synthesis_utilization=(),
                output_underruns=(1.0, 2.0, 3.0),
            ),
        )

        self.assertIsNone(decision)

    def test_qt_policy_waits_after_producer_pressure_before_reducing(
        self,
    ) -> None:
        policy = QtAudioAutoPolicy(now=0.0)
        metrics = self._active_metrics(1, 61)
        metrics = AudioSupplyMetrics(
            shortages=(60.0,),
            synthesis_utilization=metrics.synthesis_utilization,
            audio_activity=metrics.audio_activity,
        )

        decision = policy.evaluate(61.0, 1_024, metrics)

        self.assertIsNone(decision)

    def test_monitor_prioritizes_pcm_buffer_when_both_layers_report_low(
        self,
    ) -> None:
        engine = object.__new__(software_synth.SoftwareSynthEngine)
        metrics = AudioSupplyMetrics(
            shortages=(1.0, 2.0, 3.0),
            synthesis_utilization=(),
            output_underruns=(1.0, 2.0, 3.0),
            producer_starved_output_underruns=(1.0, 2.0, 3.0),
        )
        engine.stream = Mock()
        engine.stream.metrics_snapshot.return_value = metrics
        engine.stream.minimum_effective_buffer_frames.return_value = 128
        engine._monitor_stop = Mock()
        engine._monitor_stop.wait.side_effect = (False, True)
        engine._lock = threading.RLock()
        engine._output_worker = Mock()
        engine._active_clients = {1}
        engine._runtime_callbacks = {}
        engine._qt_learning_callbacks = {}
        engine._buffer_policy = Mock()
        engine._buffer_policy.evaluate.return_value = AudioBufferDecision(
            1_024,
            "producer reserve increased",
        )
        engine._qt_policy = Mock()
        engine.buffer_frames = 512
        engine.qt_frames = 1_024
        engine._requested_qt_frames = 1_024
        engine.minimum_stable_qt_frames = None
        engine.qt_audio_environment = "device|48000|2|Float"

        def apply_buffer(frames: int) -> bool:
            engine.buffer_frames = frames
            return True

        engine._apply_buffer_frames_live_locked = Mock(
            side_effect=apply_buffer
        )

        engine._monitor_audio_supply()

        self.assertEqual(engine.buffer_frames, 1_024)
        engine._qt_policy.evaluate.assert_not_called()
        engine.stream.clear_metrics.assert_called_once()

    def test_qt_policy_waits_for_silence_before_probing_lower(self) -> None:
        policy = QtAudioAutoPolicy(now=0.0)

        while_playing = policy.evaluate(
            61.0,
            1_024,
            self._active_metrics(1, 61, currently_active=True),
        )
        after_release = policy.evaluate(
            61.1,
            1_024,
            self._active_metrics(1, 61, currently_active=False),
        )

        self.assertIsNone(while_playing)
        self.assertIsNotNone(after_release)
        assert after_release is not None
        self.assertEqual(after_release.frames, 512)

    def test_changed_audio_environment_resets_qt_learning(self) -> None:
        engine = software_synth.SoftwareSynthEngine()
        try:
            engine.configure_qt_learning(
                512,
                "device-a|48000|2|Float",
            )

            with engine._lock:
                unchanged = engine._apply_audio_environment_locked(
                    "device-a|48000|2|Float"
                )
                changed = engine._apply_audio_environment_locked(
                    "device-b|44100|2|Int16"
                )

            self.assertFalse(unchanged)
            self.assertTrue(changed)
            self.assertIsNone(engine.minimum_stable_qt_frames)
            self.assertEqual(
                engine._requested_qt_frames,
                software_synth.DEFAULT_QT_AUDIO_FRAMES,
            )
            self.assertEqual(
                engine.qt_audio_environment,
                "device-b|44100|2|Int16",
            )
        finally:
            engine.shutdown()

    def test_qt_reduction_is_rejected_when_backend_queue_does_not_shrink(self) -> None:
        engine = software_synth.SoftwareSynthEngine()
        previous_worker = Mock()
        previous_thread = Mock()
        engine._output_worker = previous_worker
        engine._output_thread = previous_thread
        engine._requested_qt_frames = 1_024
        engine.qt_frames = 1_024

        def start_output(
            frames: int,
            *,
            start_muted: bool,
            standby_silence: bool = False,
        ) -> bool:
            engine._output_worker = Mock()
            engine._output_thread = Mock()
            engine._requested_qt_frames = frames
            engine.qt_frames = 1_024
            return True

        try:
            with (
                patch.object(
                    engine,
                    "_start_output_locked",
                    side_effect=start_output,
                ) as start_output_mock,
                patch.object(engine, "_stop_output_worker") as stop_output,
            ):
                changed = engine._recreate_output_locked(512)
                previous_output_was_restored = (
                    engine._output_worker is previous_worker
                    and engine._output_thread is previous_thread
                )
        finally:
            engine._output_worker = None
            engine._output_thread = None
            engine.shutdown()

        self.assertFalse(changed)
        self.assertEqual(engine._requested_qt_frames, 1_024)
        self.assertTrue(previous_output_was_restored)
        stop_output.assert_called_once()
        self.assertEqual(
            [call.args[0] for call in start_output_mock.call_args_list],
            [512],
        )

    def test_commands_collected_together_keep_their_relative_timing(self) -> None:
        now = [10.0]
        stream = SoftwareSynthStream(
            sample_rate=44_100,
            channels=1,
            buffer_frames=512,
            time_source=lambda: now[0],
        )
        stream.note_on(1, 0, 60, 100, "piano")
        now[0] += 0.005
        stream.note_off(1, 0, 60)

        samples = np.asarray(stream.render(512), dtype=np.float32)

        self.assertGreater(float(np.max(np.abs(samples[:220]))), 0.01)
        self.assertEqual(stream._voices[(1, 0, 60)].stage, "release")

    def test_sustain_holds_released_note_until_pedal_is_lifted(self) -> None:
        stream = SoftwareSynthStream(sample_rate=44_100, channels=1)
        stream.note_on(1, 2, 60, 100, "organ")
        stream.render(2_048)
        stream.set_sustain(1, 2, True)
        stream.note_off(1, 2, 60)

        held = stream.render(12_000)
        stream.set_sustain(1, 2, False)
        stream.render(8_000)
        silence = stream.render(256)

        self.assertGreater(max(abs(sample) for sample in held), 0.01)
        self.assertEqual(silence, [0.0] * 256)

    def test_separate_clients_can_play_the_same_note_at_the_same_time(self) -> None:
        stream = SoftwareSynthStream(sample_rate=44_100, channels=1)
        stream.note_on(1, 0, 60, 100, "piano")
        stream.note_on(2, 0, 60, 100, "organ")
        stream.render(1_024)

        stream.release_all(1, immediate=True)
        second_client_only = stream.render(1_024)
        stream.release_all(2, immediate=True)
        silence = stream.render(256)

        self.assertGreater(max(abs(sample) for sample in second_client_only), 0.01)
        self.assertEqual(silence, [0.0] * 256)

    def test_retrigger_crossfades_the_previous_voice(self) -> None:
        stream = SoftwareSynthStream(sample_rate=44_100, channels=1)
        stream.note_on(1, 0, 60, 100, "piano")
        stream.render(2_048)

        stream.note_on(1, 0, 60, 110, "piano")
        stream.render(0)

        self.assertEqual(len(stream._voices), 1)
        self.assertEqual(len(stream._fading_voices), 1)
        stream.render(1_024)
        self.assertEqual(stream._fading_voices, [])

    def test_polyphony_pressure_fades_a_voice_instead_of_cutting_it(self) -> None:
        stream = SoftwareSynthStream(sample_rate=44_100, channels=1)
        for index in range(software_synth.MAX_VOICES + 1):
            stream.note_on(1, index // 64, 36 + (index % 64), 100, "organ")
        stream.render(0)

        self.assertEqual(len(stream._voices), software_synth.MAX_VOICES)
        self.assertEqual(len(stream._fading_voices), 1)

    def test_all_selectable_buffer_sizes_control_the_pcm_reserve(self) -> None:
        for frames in AUDIO_BUFFER_FRAME_OPTIONS:
            with self.subTest(frames=frames):
                stream = SoftwareSynthStream(
                    sample_rate=44_100,
                    channels=2,
                    buffer_frames=frames,
                )
                self.assertEqual(
                    stream._target_ring_bytes(),
                    frames * 2 * 2,
                )

    def test_synth_supports_64_sustained_voices(self) -> None:
        stream = SoftwareSynthStream(sample_rate=44_100, channels=1)
        for index in range(64):
            stream.note_on(1, index // 64, 36 + (index % 64), 100, "organ")
        stream.render(0)

        self.assertEqual(software_synth.MAX_VOICES, 64)
        self.assertEqual(len(stream._voices), 64)
        self.assertEqual(stream._fading_voices, [])

    def test_playback_code_does_not_pause_for_software_synth_retrigger(self) -> None:
        self.assertNotIn(
            "sleep",
            inspect.getsource(sound_player.MidiSoundPlayer._send_note_on),
        )

    def test_sound_output_code_has_no_winmm_midi_output_calls(self) -> None:
        source = inspect.getsource(sound_player) + inspect.getsource(software_synth)

        self.assertNotIn("midiOutOpen", source)
        self.assertNotIn("midiOutShortMsg", source)
        self.assertNotIn("ctypes.windll.winmm", source)

    def test_device_preferred_supported_format_is_used_first(self) -> None:
        preferred = software_synth.QAudioFormat()
        preferred.setSampleRate(48_000)
        preferred.setChannelCount(2)
        preferred.setSampleFormat(
            software_synth.QAudioFormat.SampleFormat.Int32
        )
        device = Mock()
        device.preferredFormat.return_value = preferred
        device.isFormatSupported.return_value = True

        selected = software_synth.SoftwareSynthEngine._choose_format(device)

        self.assertIs(selected, preferred)
        device.isFormatSupported.assert_called_once_with(preferred)

    def test_unsupported_preferred_sample_format_falls_back_in_pcm_order(self) -> None:
        preferred = software_synth.QAudioFormat()
        preferred.setSampleRate(48_000)
        preferred.setChannelCount(2)
        preferred.setSampleFormat(
            software_synth.QAudioFormat.SampleFormat.UInt8
        )
        checked_formats = []
        device = Mock()
        device.preferredFormat.return_value = preferred

        def supports(audio_format):  # type: ignore[no-untyped-def]
            checked_formats.append(audio_format.sampleFormat())
            return (
                audio_format.sampleFormat()
                == software_synth.QAudioFormat.SampleFormat.Int32
            )

        device.isFormatSupported.side_effect = supports

        selected = software_synth.SoftwareSynthEngine._choose_format(device)

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(
            selected.sampleFormat(),
            software_synth.QAudioFormat.SampleFormat.Int32,
        )
        self.assertEqual(
            checked_formats[-3:],
            [
                software_synth.QAudioFormat.SampleFormat.Float,
                software_synth.QAudioFormat.SampleFormat.Int16,
                software_synth.QAudioFormat.SampleFormat.Int32,
            ],
        )

    def test_temporary_underrun_does_not_fail_audio_startup(self) -> None:
        sink = self.FakeSink(QAudio.State.IdleState, QAudio.Error.UnderrunError)

        self.assertFalse(software_synth.SoftwareSynthEngine._audio_start_failed(sink))

    def test_fatal_stopped_audio_sink_fails_startup(self) -> None:
        sink = self.FakeSink(QAudio.State.StoppedState, QAudio.Error.OpenError)

        self.assertTrue(software_synth.SoftwareSynthEngine._audio_start_failed(sink))


if __name__ == "__main__":
    unittest.main()
