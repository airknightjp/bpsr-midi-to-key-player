"""Manual loopback test for Qt audio-queue recreation.

Run once with ``--baseline`` and once without it. The test fails when it
detects clipping, large sample discontinuities, or a long output dropout.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QCoreApplication, QTimer

try:
    import soundcard as sc
except ModuleNotFoundError:
    sc = None

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from software_synth import (
    SoftwareSynthClient,
    shared_software_synth,
    shutdown_software_synth,
)


SAMPLE_RATE = 48_000
RECORD_SECONDS = 7.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Record the same sustained chord without changing the Qt queue.",
    )
    args = parser.parse_args()
    if sc is None:
        print(
            "SoundCard is required. Install requirements-test.txt first.",
            file=sys.stderr,
        )
        return 2
    speaker = sc.default_speaker()
    microphone = sc.get_microphone(
        speaker.name,
        include_loopback=True,
    )
    recorded: list[np.ndarray] = []
    recording_error: list[BaseException] = []

    def record_output() -> None:
        try:
            with microphone.recorder(
                samplerate=SAMPLE_RATE,
                channels=2,
                blocksize=512,
            ) as recorder:
                recorded.append(
                    recorder.record(
                        numframes=int(SAMPLE_RATE * RECORD_SECONDS)
                    )
                )
        except BaseException as exc:
            recording_error.append(exc)

    recorder_thread = threading.Thread(
        target=record_output,
        name="AudioLoopbackDiagnostic",
        daemon=True,
    )
    recorder_thread.start()
    time.sleep(0.25)

    app = QCoreApplication([])
    runtime_changes: list[tuple[int, int, str]] = []
    client = SoftwareSynthClient(
        "organ",
        on_runtime_changed=lambda qt, buffer, reason: runtime_changes.append(
            (qt, buffer, reason)
        ),
        minimum_stable_qt_frames=1_024,
    )
    if not client.open():
        raise RuntimeError(client.last_error)
    for note in (48, 55, 60, 64):
        client.note_on(0, note, 72)

    engine = shared_software_synth()
    switch_results: list[tuple[int, bool, int]] = []

    def switch(frames: int) -> None:
        with engine._lock:
            changed = (
                False
                if engine._requested_qt_frames == frames
                else engine._recreate_output_locked(frames)
            )
            switch_results.append((frames, changed, engine.qt_frames))

    if not args.baseline:
        QTimer.singleShot(2_000, lambda: switch(512))
        QTimer.singleShot(4_000, lambda: switch(1_024))
    QTimer.singleShot(6_300, app.quit)
    app.exec()

    for note in (48, 55, 60, 64):
        client.note_off(0, note)
    client.close()
    recorder_thread.join(timeout=2.0)
    if recording_error:
        raise recording_error[0]
    if not recorded:
        raise RuntimeError("No loopback audio was recorded")

    audio = np.asarray(recorded[0], dtype=np.float32)
    mono = np.mean(audio, axis=1)
    active = mono[int(0.8 * SAMPLE_RATE):int(6.1 * SAMPLE_RATE)]
    differences = np.abs(np.diff(active))
    clipping_count = int(np.count_nonzero(np.abs(active) >= 0.999))
    large_jump_count = int(np.count_nonzero(differences >= 0.20))
    max_jump = float(np.max(differences, initial=0.0))

    window_frames = SAMPLE_RATE // 100
    usable = len(active) - (len(active) % window_frames)
    windows = active[:usable].reshape(-1, window_frames)
    rms = np.sqrt(np.mean(np.square(windows), axis=1))
    nonzero_rms = rms[rms > 1.0e-5]
    median_rms = (
        float(np.median(nonzero_rms))
        if len(nonzero_rms)
        else 0.0
    )
    dropout_count = int(
        np.count_nonzero(rms < max(1.0e-5, median_rms * 0.05))
    )

    metrics = engine.stream.metrics_snapshot()
    print(f"speaker={speaker.name}")
    print(f"switches={switch_results}")
    print(f"runtime_changes={runtime_changes}")
    print(f"clipping_count={clipping_count}")
    print(f"large_jump_count={large_jump_count}")
    print(f"max_jump={max_jump:.6f}")
    print(f"median_rms={median_rms:.6f}")
    print(f"dropout_windows_10ms={dropout_count}")
    print(f"dropout_indexes={np.flatnonzero(rms < max(1.0e-5, median_rms * 0.05)).tolist()}")
    print(f"output_underruns={len(metrics.output_underruns)}")
    print(f"supply_shortages={len(metrics.shortages)}")
    failed = int(
        clipping_count > 0
        or large_jump_count > 0
        or dropout_count > 8
    )
    shutdown_software_synth()
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
