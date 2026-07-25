from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from midi_parser_process import MidiParserProcess
from process_lifecycle import initialize_process_job
from software_synth import SoftwareSynthClient, SoftwareSynthProcessHost


def _single_note_midi() -> bytes:
    track = (
        b"\x00\x90\x3c\x40"
        + b"\x83\x60\x80\x3c\x00"
        + b"\x00\xff\x2f\x00"
    )
    header = (
        b"MThd"
        + (6).to_bytes(4, "big")
        + (0).to_bytes(2, "big")
        + (1).to_bytes(2, "big")
        + (480).to_bytes(2, "big")
    )
    return header + b"MTrk" + len(track).to_bytes(4, "big") + track


class ProcessIsolationTests(unittest.TestCase):
    def test_midi_parser_runs_in_a_spawned_process(self) -> None:
        parser = MidiParserProcess()
        try:
            with tempfile.TemporaryDirectory() as temporary_directory:
                path = Path(temporary_directory) / "song.mid"
                path.write_bytes(_single_note_midi())

                events, summary = parser.parse(path)

            executor = parser._executor
            self.assertIsNotNone(executor)
            assert executor is not None
            worker_pids = tuple(executor._processes)
            job = initialize_process_job()
            worker_in_job = (
                job is None
                or all(job.contains_pid(pid) for pid in worker_pids)
            )
        finally:
            parser.shutdown()

        self.assertEqual(summary.event_count, 2)
        self.assertEqual(len(events), 2)
        self.assertTrue(worker_pids)
        self.assertNotIn(os.getpid(), worker_pids)
        self.assertTrue(worker_in_job)

    def test_audio_host_runs_its_command_loop_in_a_spawned_process(
        self,
    ) -> None:
        host = SoftwareSynthProcessHost()
        try:
            ok, result, error = host._request("ping")
            process = host._process
            self.assertIsNotNone(process)
            assert process is not None
            process_id = process.pid
            job = initialize_process_job()
            process_in_job = (
                job is None
                or (
                    process_id is not None
                    and job.contains_pid(process_id)
                )
            )
        finally:
            host.shutdown()

        self.assertTrue(ok, error)
        self.assertTrue(result)
        self.assertIsNotNone(process_id)
        self.assertNotEqual(process_id, os.getpid())
        self.assertTrue(process_in_job)

    def test_audio_process_opens_the_device_and_accepts_notes(self) -> None:
        host = SoftwareSynthProcessHost()
        try:
            self.assertTrue(
                host.configure_audio_settings(
                    1_024,
                    512,
                    256,
                    1_024,
                    4,
                ),
                host.last_error,
            )
            if not host.start():
                self.skipTest(host.last_error)
            client_id = host.new_client_id()
            host.register_client(client_id, None)
            host.note_on(client_id, 0, 60, 96, "piano")
            time.sleep(0.05)
            metrics = host.metrics_snapshot()
            host.note_off(client_id, 0, 60)
            host.release_all(client_id)
            host.unregister_client(client_id)
        finally:
            host.shutdown()

        self.assertGreater(metrics.ring_target_bytes, 0)

    def test_software_synth_client_uses_the_audio_process_host(self) -> None:
        host = SoftwareSynthProcessHost()
        client = SoftwareSynthClient()
        try:
            with patch(
                "software_synth.shared_software_synth",
                return_value=host,
            ):
                if not client.open():
                    self.skipTest(client.last_error)
                client.note_on(0, 60, 96)
                time.sleep(0.02)
                client.note_off(0, 60)
                client.close()
        finally:
            host.shutdown()

        self.assertFalse(client.is_open)


if __name__ == "__main__":
    unittest.main()
