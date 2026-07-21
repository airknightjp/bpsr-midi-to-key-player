from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from chord_optimization import (
    ChordOptimizationCancelled,
    ChordOptimizationPlan,
    build_chord_optimization_plan,
)
from midi_parser import MidiEvent


OPTIMIZATION_DEBOUNCE_SECONDS = 0.15

ProgressCallback = Callable[[int | None], None]


@dataclass(frozen=True)
class ChordOptimizationRequest:
    generation: int
    events: list[MidiEvent]
    options: dict[str, object]


class ChordOptimizationPlanner:
    def __init__(
        self,
        request_provider: Callable[[], ChordOptimizationRequest | None],
        request_is_current: Callable[[int], bool],
        commit_plan: Callable[[ChordOptimizationRequest, ChordOptimizationPlan], bool],
        should_stop: Callable[[], bool],
        on_progress: ProgressCallback | None = None,
        debounce_seconds: float = OPTIMIZATION_DEBOUNCE_SECONDS,
    ) -> None:
        self._request_provider = request_provider
        self._request_is_current = request_is_current
        self._commit_plan = commit_plan
        self._should_stop = should_stop
        self._on_progress = on_progress or (lambda _progress: None)
        self._debounce_seconds = max(0.0, float(debounce_seconds))
        self._worker_lock = threading.Lock()
        self._worker: threading.Thread | None = None

    def build_now(self) -> bool:
        while not self._should_stop():
            request = self._request_provider()
            if request is None:
                self._on_progress(None)
                return True
            plan = self._build(request)
            if plan is None:
                continue
            if self._commit_plan(request, plan):
                self._on_progress(None)
                return True
        self._on_progress(None)
        return False

    def schedule(self) -> None:
        if self._should_stop():
            return
        with self._worker_lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(target=self._run_worker, daemon=True)
            self._worker.start()

    def wait(self, timeout: float | None = None) -> None:
        with self._worker_lock:
            worker = self._worker
        if worker is not None and threading.current_thread() is not worker:
            worker.join(timeout)

    def _run_worker(self) -> None:
        try:
            while not self._should_stop():
                request = self._stable_request()
                if request is None:
                    self._on_progress(None)
                    return
                plan = self._build(request)
                if plan is None:
                    continue
                if self._commit_plan(request, plan):
                    self._on_progress(None)
        finally:
            with self._worker_lock:
                self._worker = None
            if not self._should_stop() and self._request_provider() is not None:
                self.schedule()

    def _stable_request(self) -> ChordOptimizationRequest | None:
        request = self._request_provider()
        if request is None:
            return None
        deadline = time.perf_counter() + self._debounce_seconds
        while not self._should_stop():
            remaining = deadline - time.perf_counter()
            if remaining > 0:
                time.sleep(min(remaining, 0.02))
            current = self._request_provider()
            if current is None:
                return None
            if current.generation != request.generation:
                request = current
                deadline = time.perf_counter() + self._debounce_seconds
                continue
            if time.perf_counter() >= deadline:
                return current
        return None

    def _build(
        self,
        request: ChordOptimizationRequest,
    ) -> ChordOptimizationPlan | None:
        try:
            return build_chord_optimization_plan(
                request.events,
                **request.options,
                progress_callback=lambda progress: self._report_progress(
                    request.generation,
                    progress,
                ),
                cancel_callback=lambda: (
                    self._should_stop()
                    or not self._request_is_current(request.generation)
                ),
            )
        except ChordOptimizationCancelled:
            return None

    def _report_progress(self, generation: int, progress: int) -> None:
        if self._request_is_current(generation):
            self._on_progress(progress)
