from __future__ import annotations

import multiprocessing
import os
import queue
import threading
import traceback
from pathlib import Path
from typing import Callable

from piano_arrangement import analyze_piano_arrangement
from piano_arrangement_models import PianoArrangementConfig
from process_lifecycle import (
    register_child_process,
    start_parent_process_watchdog,
)


ProgressHandler = Callable[[int], None]
CompleteHandler = Callable[[str, str], None]
ErrorHandler = Callable[[str], None]
CancelledHandler = Callable[[], None]


def _arrangement_worker(
    parent_pid: int,
    path: str,
    config: PianoArrangementConfig,
    progress_queue: object,
    result_queue: object,
    cancel_event: object,
) -> None:
    start_parent_process_watchdog(parent_pid, 1.0)
    try:
        plan = analyze_piano_arrangement(
            path,
            config,
            progress_callback=lambda value: progress_queue.put(
                ("progress", int(value))
            ),
            cancel_callback=cancel_event.is_set,
            use_cache=True,
        )
        result_queue.put(
            (
                "complete",
                plan.source_file_hash,
                plan.config_key,
            )
        )
    except Exception as exc:
        if cancel_event.is_set():
            result_queue.put(("cancelled",))
        else:
            result_queue.put(
                (
                    "error",
                    str(exc),
                    traceback.format_exc(limit=8),
                )
            )


class PianoArrangementProcess:
    """Runs one cancellable piano-arrangement job outside the GUI process."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: multiprocessing.Process | None = None
        self._cancel_event: object | None = None
        self._monitor: threading.Thread | None = None
        self._generation = 0
        self._closed = False

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._process is not None and self._process.is_alive())

    def start(
        self,
        path: str | Path,
        config: PianoArrangementConfig,
        *,
        on_progress: ProgressHandler,
        on_complete: CompleteHandler,
        on_error: ErrorHandler,
        on_cancelled: CancelledHandler,
    ) -> int:
        self.cancel(wait=True)
        with self._lock:
            if self._closed:
                raise RuntimeError("Piano arrangement process is closed")
            self._generation += 1
            generation = self._generation
            context = multiprocessing.get_context("spawn")
            progress_queue = context.Queue()
            result_queue = context.Queue()
            cancel_event = context.Event()
            process = context.Process(
                target=_arrangement_worker,
                args=(
                    os.getpid(),
                    str(Path(path)),
                    config.normalized(),
                    progress_queue,
                    result_queue,
                    cancel_event,
                ),
                name="PianoArrangementWorker",
                daemon=False,
            )
            process.start()
            register_child_process(process.pid)
            self._process = process
            self._cancel_event = cancel_event
            monitor = threading.Thread(
                target=self._monitor_process,
                args=(
                    generation,
                    process,
                    progress_queue,
                    result_queue,
                    on_progress,
                    on_complete,
                    on_error,
                    on_cancelled,
                ),
                name="PianoArrangementMonitor",
                daemon=True,
            )
            self._monitor = monitor
            monitor.start()
            return generation

    def cancel(self, *, wait: bool = False) -> None:
        with self._lock:
            process = self._process
            cancel_event = self._cancel_event
        if cancel_event is not None:
            cancel_event.set()
        if process is not None and wait:
            process.join(timeout=3.0)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2.0)

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
        self.cancel(wait=True)
        monitor = self._monitor
        if monitor is not None and monitor is not threading.current_thread():
            monitor.join(timeout=2.0)

    def _monitor_process(
        self,
        generation: int,
        process: multiprocessing.Process,
        progress_queue: object,
        result_queue: object,
        on_progress: ProgressHandler,
        on_complete: CompleteHandler,
        on_error: ErrorHandler,
        on_cancelled: CancelledHandler,
    ) -> None:
        result: tuple[object, ...] | None = None
        last_progress = -1
        while process.is_alive() or result is None:
            try:
                while True:
                    message = progress_queue.get_nowait()
                    if (
                        isinstance(message, tuple)
                        and message
                        and message[0] == "progress"
                    ):
                        last_progress = int(message[1])
                        on_progress(last_progress)
            except queue.Empty:
                pass
            try:
                result = result_queue.get(timeout=0.05)
                break
            except queue.Empty:
                if not process.is_alive():
                    break
        process.join(timeout=1.0)
        try:
            while True:
                message = progress_queue.get_nowait()
                if (
                    isinstance(message, tuple)
                    and message
                    and message[0] == "progress"
                ):
                    last_progress = int(message[1])
                    on_progress(last_progress)
        except queue.Empty:
            pass
        with self._lock:
            current = generation == self._generation
            if current and self._process is process:
                self._process = None
                self._cancel_event = None
        if not current:
            self._close_queue(progress_queue)
            self._close_queue(result_queue)
            return
        if result is None:
            if process.exitcode:
                on_error(
                    f"Piano arrangement process ended unexpectedly "
                    f"(exit code {process.exitcode})"
                )
            else:
                on_cancelled()
        else:
            kind = str(result[0])
            if kind == "complete":
                if last_progress < 100:
                    on_progress(100)
                on_complete(str(result[1]), str(result[2]))
            elif kind == "cancelled":
                on_cancelled()
            else:
                detail = str(result[2]) if len(result) > 2 else ""
                on_error(f"{result[1]}\n{detail}".strip())
        self._close_queue(progress_queue)
        self._close_queue(result_queue)

    @staticmethod
    def _close_queue(target: object) -> None:
        try:
            target.close()
            target.join_thread()
        except (AttributeError, OSError, ValueError):
            pass
