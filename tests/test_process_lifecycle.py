from __future__ import annotations

import ctypes
import multiprocessing
import os
import queue
import sys
import time
import unittest
from ctypes import wintypes

from process_lifecycle import (
    PROCESS_TERMINATE,
    SYNCHRONIZE,
    WAIT_TIMEOUT,
    initialize_process_job,
    register_child_process,
    start_parent_process_watchdog,
)


def _wait_for_stop(stop_event) -> None:  # type: ignore[no-untyped-def]
    stop_event.wait(10.0)


def _watchdog_child(report_queue) -> None:  # type: ignore[no-untyped-def]
    start_parent_process_watchdog(os.getppid(), 0.05)
    report_queue.put(os.getpid())
    while True:
        time.sleep(1.0)


def _watchdog_parent(report_queue) -> None:  # type: ignore[no-untyped-def]
    context = multiprocessing.get_context("spawn")
    child = context.Process(
        target=_watchdog_child,
        args=(report_queue,),
        name="ParentWatchdogTestChild",
    )
    child.start()
    time.sleep(0.25)
    os._exit(0)


def _job_child(report_queue) -> None:  # type: ignore[no-untyped-def]
    report_queue.put(os.getpid())
    while True:
        time.sleep(1.0)


def _job_parent(report_queue) -> None:  # type: ignore[no-untyped-def]
    initialize_process_job()
    context = multiprocessing.get_context("spawn")
    child = context.Process(
        target=_job_child,
        args=(report_queue,),
        name="JobObjectTestChild",
    )
    child.start()
    assert child.pid is not None
    register_child_process(child.pid)
    time.sleep(0.25)
    os._exit(0)


def _is_process_running(pid: int) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
    ]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if not handle:
        return False
    try:
        return int(kernel32.WaitForSingleObject(handle, 0)) == WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)


def _terminate_process(pid: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.TerminateProcess.argtypes = [
        wintypes.HANDLE,
        wintypes.UINT,
    ]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
    if not handle:
        return
    try:
        kernel32.TerminateProcess(handle, 1)
    finally:
        kernel32.CloseHandle(handle)


@unittest.skipUnless(sys.platform == "win32", "Windows process supervision")
class ProcessLifecycleTests(unittest.TestCase):
    def test_unregistered_child_is_not_captured_by_the_job(self) -> None:
        job = initialize_process_job()
        self.assertIsNotNone(job)
        assert job is not None
        context = multiprocessing.get_context("spawn")
        stop_event = context.Event()
        child = context.Process(
            target=_wait_for_stop,
            args=(stop_event,),
        )
        child.start()
        try:
            self.assertIsNotNone(child.pid)
            assert child.pid is not None
            self.assertFalse(job.contains_pid(child.pid))
        finally:
            stop_event.set()
            child.join(timeout=3.0)
            if child.is_alive():
                child.terminate()
                child.join(timeout=1.0)

    def test_job_contains_parent_and_registered_child(self) -> None:
        job = initialize_process_job()
        self.assertIsNotNone(job)
        assert job is not None
        self.assertTrue(job.contains_pid(os.getpid()))
        context = multiprocessing.get_context("spawn")
        stop_event = context.Event()
        child = context.Process(
            target=_wait_for_stop,
            args=(stop_event,),
        )
        child.start()
        try:
            self.assertIsNotNone(child.pid)
            assert child.pid is not None
            register_child_process(child.pid)
            self.assertTrue(job.contains_pid(child.pid))
        finally:
            stop_event.set()
            child.join(timeout=3.0)
            if child.is_alive():
                child.terminate()
                child.join(timeout=1.0)

    def test_job_object_terminates_child_when_owner_exits(self) -> None:
        context = multiprocessing.get_context("spawn")
        report_queue = context.Queue()
        parent = context.Process(
            target=_job_parent,
            args=(report_queue,),
            name="JobObjectTestParent",
        )
        child_pid: int | None = None
        try:
            parent.start()
            try:
                child_pid = int(report_queue.get(timeout=5.0))
            except queue.Empty:
                self.fail("Job child did not report its PID")
            parent.join(timeout=3.0)
            self.assertFalse(parent.is_alive())
            deadline = time.monotonic() + 3.0
            while (
                child_pid is not None
                and _is_process_running(child_pid)
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
            assert child_pid is not None
            self.assertFalse(_is_process_running(child_pid))
        finally:
            if parent.is_alive():
                parent.terminate()
                parent.join(timeout=1.0)
            if child_pid is not None and _is_process_running(child_pid):
                _terminate_process(child_pid)
            report_queue.close()

    def test_parent_pid_watchdog_terminates_orphaned_child(self) -> None:
        context = multiprocessing.get_context("spawn")
        report_queue = context.Queue()
        parent = context.Process(
            target=_watchdog_parent,
            args=(report_queue,),
            name="ParentWatchdogTestParent",
        )
        child_pid: int | None = None
        try:
            parent.start()
            try:
                child_pid = int(report_queue.get(timeout=5.0))
            except queue.Empty:
                self.fail("Watchdog child did not report its PID")
            parent.join(timeout=3.0)
            self.assertFalse(parent.is_alive())
            deadline = time.monotonic() + 3.0
            while (
                child_pid is not None
                and _is_process_running(child_pid)
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
            assert child_pid is not None
            self.assertFalse(_is_process_running(child_pid))
        finally:
            if parent.is_alive():
                parent.terminate()
                parent.join(timeout=1.0)
            if child_pid is not None and _is_process_running(child_pid):
                _terminate_process(child_pid)
            report_queue.close()


if __name__ == "__main__":
    unittest.main()
