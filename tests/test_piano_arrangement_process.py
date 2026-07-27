from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from piano_arrangement_cache import load_arrangement_cache
from piano_arrangement_models import PianoArrangementConfig
from piano_arrangement_process import PianoArrangementProcess


def _single_part_midi() -> bytes:
    track = (
        b"\x00\xff\x58\x04\x04\x02\x18\x08"
        + b"\x00\x90\x3c\x60"
        + b"\x83\x60\x80\x3c\x00"
        + b"\x00\x90\x40\x60"
        + b"\x83\x60\x80\x40\x00"
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


class PianoArrangementProcessTests(unittest.TestCase):
    def test_worker_reports_progress_and_writes_a_reusable_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            midi_path = root / "input.mid"
            cache_root = root / "cache"
            midi_path.write_bytes(_single_part_midi())
            process = PianoArrangementProcess()
            completed = threading.Event()
            progress: list[int] = []
            result: list[tuple[str, str]] = []
            errors: list[str] = []
            with patch.dict(
                os.environ,
                {"BPSR_ARRANGEMENT_CACHE_DIR": str(cache_root)},
            ):
                process.start(
                    midi_path,
                    PianoArrangementConfig(),
                    on_progress=progress.append,
                    on_complete=lambda source_hash, config_key: (
                        result.append((source_hash, config_key)),
                        completed.set(),
                    ),
                    on_error=lambda message: (
                        errors.append(message),
                        completed.set(),
                    ),
                    on_cancelled=completed.set,
                )
                self.assertTrue(completed.wait(20.0))
                process.shutdown()
                self.assertFalse(process.running)
                self.assertFalse(errors)
                self.assertTrue(result)
                source_hash, _config_key = result[0]
                self.assertEqual(progress[-1], 100)
                self.assertIsNotNone(
                    load_arrangement_cache(
                        source_hash,
                        PianoArrangementConfig(),
                    )
                )


if __name__ == "__main__":
    unittest.main()
