from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes


JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK = 0x00001000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
PARENT_PROCESS_LOST_EXIT_CODE = 90


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobObjectBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class WindowsProcessJob:
    """Owns a Windows Job Object that terminates members with its owner."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("Windows Job Objects are only available on Windows")
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure_signatures()
        handle = self._kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self._handle: int | None = int(handle)
        try:
            information = _JobObjectExtendedLimitInformation()
            information.BasicLimitInformation.LimitFlags = (
                JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                | JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK
            )
            if not self._kernel32.SetInformationJobObject(
                handle,
                JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(information),
                ctypes.sizeof(information),
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            self._assign_handle(self._kernel32.GetCurrentProcess())
        except Exception:
            self._kernel32.CloseHandle(handle)
            self._handle = None
            raise

    @property
    def handle(self) -> int | None:
        return self._handle

    def contains_pid(self, pid: int) -> bool:
        process_handle = self._open_process(
            int(pid),
            PROCESS_QUERY_LIMITED_INFORMATION,
        )
        try:
            return self._contains_handle(process_handle)
        finally:
            self._kernel32.CloseHandle(process_handle)

    def assign_pid(self, pid: int) -> None:
        process_handle = self._open_process(
            int(pid),
            (
                PROCESS_SET_QUOTA
                | PROCESS_TERMINATE
                | PROCESS_QUERY_LIMITED_INFORMATION
            ),
        )
        try:
            if not self._contains_handle(process_handle):
                self._assign_handle(process_handle)
        finally:
            self._kernel32.CloseHandle(process_handle)

    def close(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is not None:
            self._kernel32.CloseHandle(handle)

    def _open_process(self, pid: int, access: int) -> int:
        handle = self._kernel32.OpenProcess(access, False, int(pid))
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return int(handle)

    def _contains_handle(self, process_handle: int) -> bool:
        handle = self._handle
        if handle is None:
            raise RuntimeError("Process Job is closed")
        is_member = wintypes.BOOL()
        if not self._kernel32.IsProcessInJob(
            process_handle,
            handle,
            ctypes.byref(is_member),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return bool(is_member.value)

    def _assign_handle(self, process_handle: int) -> None:
        handle = self._handle
        if handle is None:
            raise RuntimeError("Process Job is closed")
        if not self._kernel32.AssignProcessToJobObject(
            handle,
            process_handle,
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    def _configure_signatures(self) -> None:
        self._kernel32.CreateJobObjectW.argtypes = [
            wintypes.LPVOID,
            wintypes.LPCWSTR,
        ]
        self._kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        self._kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        self._kernel32.SetInformationJobObject.restype = wintypes.BOOL
        self._kernel32.AssignProcessToJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
        ]
        self._kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        self._kernel32.IsProcessInJob.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.BOOL),
        ]
        self._kernel32.IsProcessInJob.restype = wintypes.BOOL
        self._kernel32.GetCurrentProcess.argtypes = []
        self._kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        self._kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL


_job_lock = threading.Lock()
_process_job: WindowsProcessJob | None = None
_watchdog_lock = threading.Lock()
_watchdog_started = False


def initialize_process_job() -> WindowsProcessJob | None:
    """Creates the process Job and registers the current parent process."""
    global _process_job
    if sys.platform != "win32":
        return None
    with _job_lock:
        if _process_job is None:
            _process_job = WindowsProcessJob()
        return _process_job


def register_child_process(pid: int) -> None:
    job = initialize_process_job()
    if job is not None:
        job.assign_pid(int(pid))


def start_parent_process_watchdog(
    parent_pid: int,
    interval_seconds: float = 1.0,
) -> None:
    """Terminates this child if its original parent process exits."""
    global _watchdog_started
    with _watchdog_lock:
        if _watchdog_started:
            return
        _watchdog_started = True
    interval_seconds = max(0.05, float(interval_seconds))
    thread = threading.Thread(
        target=_watch_parent_process,
        args=(int(parent_pid), interval_seconds),
        name="ParentProcessWatchdog",
        daemon=True,
    )
    thread.start()


def _watch_parent_process(
    parent_pid: int,
    interval_seconds: float,
) -> None:
    if sys.platform == "win32":
        _watch_parent_process_windows(parent_pid, interval_seconds)
        return
    while True:
        time.sleep(interval_seconds)
        if os.getppid() != parent_pid:
            os._exit(PARENT_PROCESS_LOST_EXIT_CODE)
        try:
            os.kill(parent_pid, 0)
        except OSError:
            os._exit(PARENT_PROCESS_LOST_EXIT_CODE)


def _watch_parent_process_windows(
    parent_pid: int,
    interval_seconds: float,
) -> None:
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
    parent_handle = kernel32.OpenProcess(
        SYNCHRONIZE,
        False,
        int(parent_pid),
    )
    if not parent_handle:
        os._exit(PARENT_PROCESS_LOST_EXIT_CODE)
    timeout_ms = max(50, int(interval_seconds * 1000.0))
    try:
        while True:
            result = int(
                kernel32.WaitForSingleObject(parent_handle, timeout_ms)
            )
            if result == WAIT_TIMEOUT:
                continue
            os._exit(PARENT_PROCESS_LOST_EXIT_CODE)
    finally:
        kernel32.CloseHandle(parent_handle)
