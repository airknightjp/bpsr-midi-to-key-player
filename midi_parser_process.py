from __future__ import annotations

import multiprocessing
import os
import threading
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

from midi_parser import MidiEvent, MidiSummary, parse_midi
from process_lifecycle import (
    register_child_process,
    start_parent_process_watchdog,
)

_PARSED_MIDI_CACHE: OrderedDict[
    tuple[str, int, int],
    tuple[list[MidiEvent], MidiSummary],
] = OrderedDict()
_PARSED_MIDI_CACHE_LIMIT = 8


def _cached_parse(path: str) -> tuple[list[MidiEvent], MidiSummary]:
    midi_path = Path(path)
    stat = midi_path.stat()
    key = (str(midi_path), int(stat.st_mtime_ns), int(stat.st_size))
    cached = _PARSED_MIDI_CACHE.get(key)
    if cached is not None:
        _PARSED_MIDI_CACHE.move_to_end(key)
        return cached
    parsed = parse_midi(midi_path)
    _PARSED_MIDI_CACHE[key] = parsed
    _PARSED_MIDI_CACHE.move_to_end(key)
    while len(_PARSED_MIDI_CACHE) > _PARSED_MIDI_CACHE_LIMIT:
        _PARSED_MIDI_CACHE.popitem(last=False)
    return parsed


def _parse_midi_in_process(
    path: str,
) -> tuple[list[MidiEvent], MidiSummary]:
    return _cached_parse(path)


def _parser_worker_pid() -> int:
    return os.getpid()


class MidiParserProcess:
    """Runs full MIDI parsing outside the GUI and audio processes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._executor: ProcessPoolExecutor | None = None
        self._closed = False
        self._parent_pid = os.getpid()

    def parse(
        self,
        path: str | Path,
    ) -> tuple[list[MidiEvent], MidiSummary]:
        path_text = str(Path(path))
        for attempt in range(2):
            executor = self._executor_for_request()
            try:
                return executor.submit(
                    _parse_midi_in_process,
                    path_text,
                ).result()
            except BrokenProcessPool:
                self._discard_executor(executor)
                if attempt:
                    raise
        raise RuntimeError("MIDI parser process could not be started")

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            executor = self._executor
            self._executor = None
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)

    def _executor_for_request(self) -> ProcessPoolExecutor:
        with self._lock:
            if self._closed:
                raise RuntimeError("MIDI parser process is closed")
            executor = self._executor
            if executor is None:
                executor = ProcessPoolExecutor(
                    max_workers=1,
                    mp_context=multiprocessing.get_context("spawn"),
                    initializer=start_parent_process_watchdog,
                    initargs=(self._parent_pid, 1.0),
                )
                try:
                    worker_pid = executor.submit(
                        _parser_worker_pid
                    ).result(timeout=5.0)
                    register_child_process(worker_pid)
                except Exception:
                    executor.shutdown(
                        wait=False,
                        cancel_futures=True,
                    )
                    raise
                self._executor = executor
            return executor

    def _discard_executor(
        self,
        executor: ProcessPoolExecutor,
    ) -> None:
        with self._lock:
            if self._executor is executor:
                self._executor = None
        executor.shutdown(wait=False, cancel_futures=True)
