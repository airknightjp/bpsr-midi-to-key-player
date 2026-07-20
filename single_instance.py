from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
EVENT_MODIFY_STATE = 0x0002
SYNCHRONIZE = 0x00100000
SW_RESTORE = 9
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_SHOWWINDOW = 0x0040
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
INSTANCE_MUTEX_NAME = "Local\\BPSR_MIDI_to_KEY_Player_Instance"
ACTIVATION_EVENT_NAME = "Local\\BPSR_MIDI_to_KEY_Player_Activate"


class SingleInstance:
    def __init__(self, window_title: str):
        self.window_title = window_title
        self._event: int | None = None
        self._mutex: int | None = None
        self._kernel32 = None
        self._user32 = None
        self.is_primary = True
        if sys.platform != "win32":
            return

        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._configure_signatures()

        event = self._kernel32.CreateEventW(
            None,
            False,
            False,
            ACTIVATION_EVENT_NAME,
        )
        if not event:
            raise ctypes.WinError(ctypes.get_last_error())
        self._event = event

        ctypes.set_last_error(0)
        mutex = self._kernel32.CreateMutexW(
            None,
            False,
            INSTANCE_MUTEX_NAME,
        )
        if not mutex:
            error = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(error)
        self._mutex = mutex
        self.is_primary = ctypes.get_last_error() != ERROR_ALREADY_EXISTS

    def notify_existing(self) -> None:
        if self._kernel32 is None or self._event is None:
            return
        self._kernel32.SetEvent(self._event)
        self._show_existing_window()

    def bring_existing_window_to_front(self) -> None:
        self._show_existing_window()

    def consume_activation_request(self) -> bool:
        if self._kernel32 is None or self._event is None:
            return False
        return (
            self._kernel32.WaitForSingleObject(self._event, 0)
            == WAIT_OBJECT_0
        )

    def close(self) -> None:
        if self._kernel32 is not None:
            for handle_name in ("_mutex", "_event"):
                handle = getattr(self, handle_name)
                if handle is not None:
                    self._kernel32.CloseHandle(handle)
                    setattr(self, handle_name, None)

    def _show_existing_window(self) -> None:
        if self._user32 is None:
            return
        window = self._user32.FindWindowW(None, self.window_title)
        if not window:
            return
        foreground = self._user32.GetForegroundWindow()
        current_thread = self._kernel32.GetCurrentThreadId()
        foreground_thread = (
            self._user32.GetWindowThreadProcessId(foreground, None)
            if foreground
            else 0
        )
        window_thread = self._user32.GetWindowThreadProcessId(window, None)
        attached_foreground = (
            foreground_thread not in (0, current_thread)
            and self._user32.AttachThreadInput(
                current_thread,
                foreground_thread,
                True,
            )
        )
        attached_window = (
            window_thread not in (0, current_thread, foreground_thread)
            and self._user32.AttachThreadInput(
                current_thread,
                window_thread,
                True,
            )
        )
        try:
            self._user32.ShowWindow(window, SW_RESTORE)
            self._user32.SetWindowPos(
                window,
                HWND_TOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
            )
            self._user32.SetWindowPos(
                window,
                HWND_NOTOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
            )
            self._user32.BringWindowToTop(window)
            self._user32.SetForegroundWindow(window)
            self._user32.SetFocus(window)
        finally:
            if attached_window:
                self._user32.AttachThreadInput(
                    current_thread,
                    window_thread,
                    False,
                )
            if attached_foreground:
                self._user32.AttachThreadInput(
                    current_thread,
                    foreground_thread,
                    False,
                )

    def _configure_signatures(self) -> None:
        assert self._kernel32 is not None
        assert self._user32 is not None
        self._kernel32.CreateEventW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        self._kernel32.CreateEventW.restype = wintypes.HANDLE
        self._kernel32.CreateMutexW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        self._kernel32.CreateMutexW.restype = wintypes.HANDLE
        self._kernel32.SetEvent.argtypes = [wintypes.HANDLE]
        self._kernel32.SetEvent.restype = wintypes.BOOL
        self._kernel32.WaitForSingleObject.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
        ]
        self._kernel32.WaitForSingleObject.restype = wintypes.DWORD
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32.GetCurrentThreadId.argtypes = []
        self._kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        self._user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        self._user32.FindWindowW.restype = wintypes.HWND
        self._user32.GetForegroundWindow.argtypes = []
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self._user32.AttachThreadInput.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.BOOL,
        ]
        self._user32.AttachThreadInput.restype = wintypes.BOOL
        self._user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.ShowWindow.restype = wintypes.BOOL
        self._user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        self._user32.SetWindowPos.restype = wintypes.BOOL
        self._user32.BringWindowToTop.argtypes = [wintypes.HWND]
        self._user32.BringWindowToTop.restype = wintypes.BOOL
        self._user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self._user32.SetForegroundWindow.restype = wintypes.BOOL
        self._user32.SetFocus.argtypes = [wintypes.HWND]
        self._user32.SetFocus.restype = wintypes.HWND
