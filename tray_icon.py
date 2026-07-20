from __future__ import annotations

import ctypes
from collections.abc import Callable
from pathlib import Path
from ctypes import wintypes


IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
NIM_ADD = 0x00000000
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 20
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
IDI_APPLICATION = 32512
GWL_WNDPROC = -4
MENU_EXIT_ID = 1001


class NOTIFYICONDATAW(ctypes.Structure):
    class VERSION_UNION(ctypes.Union):
        _fields_ = [
            ("uTimeout", wintypes.UINT),
            ("uVersion", wintypes.UINT),
        ]

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("version", VERSION_UNION),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


class TrayIcon:
    def __init__(self, hwnd: int, tooltip: str, icon_path: str | Path | None = None):
        self.hwnd = hwnd
        self.tooltip = tooltip[:127]
        self.icon_path = Path(icon_path) if icon_path else None
        self.visible = False
        self.restore_requested = False
        self.exit_requested = False
        self._old_wndproc: int | None = None
        self._new_wndproc = WNDPROC(self._wndproc)
        self._icon_handle: int | None = None
        self._taskbar_created_message = 0

    def install(self) -> None:
        if self._old_wndproc is None:
            user32 = ctypes.windll.user32
            user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            user32.SetWindowLongPtrW.restype = ctypes.c_void_p
            user32.CallWindowProcW.argtypes = [
                ctypes.c_void_p,
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            user32.CallWindowProcW.restype = ctypes.c_ssize_t
            user32.DefWindowProcW.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            user32.DefWindowProcW.restype = ctypes.c_ssize_t
            self._taskbar_created_message = user32.RegisterWindowMessageW("TaskbarCreated")
            self._old_wndproc = user32.SetWindowLongPtrW(
                self.hwnd,
                GWL_WNDPROC,
                ctypes.cast(self._new_wndproc, ctypes.c_void_p),
            )
            if not self._old_wndproc:
                raise OSError("Could not install the tray window hook")

    def uninstall(self) -> None:
        self.hide()
        if self._old_wndproc is not None:
            ctypes.windll.user32.SetWindowLongPtrW(
                self.hwnd,
                GWL_WNDPROC,
                ctypes.c_void_p(self._old_wndproc),
            )
            self._old_wndproc = None
        if self._icon_handle is not None:
            ctypes.windll.user32.DestroyIcon(self._icon_handle)
            self._icon_handle = None

    def show(self) -> None:
        if self.visible:
            return
        data = self._notify_data()
        if ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)):
            self.visible = True

    def hide(self) -> None:
        if not self.visible:
            return
        data = self._notify_data()
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))
        self.visible = False

    def consume_restore_request(self) -> bool:
        if not self.restore_requested:
            return False
        self.restore_requested = False
        return True

    def consume_exit_request(self) -> bool:
        if not self.exit_requested:
            return False
        self.exit_requested = False
        return True

    def _notify_data(self) -> NOTIFYICONDATAW:
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = self.hwnd
        data.uID = 1
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        data.uCallbackMessage = WM_TRAYICON
        data.hIcon = self._load_icon()
        data.szTip = self.tooltip
        return data

    def _load_icon(self) -> int:
        if self._icon_handle is not None:
            return self._icon_handle
        if self.icon_path and self.icon_path.exists():
            ctypes.windll.user32.LoadImageW.restype = wintypes.HANDLE
            self._icon_handle = ctypes.windll.user32.LoadImageW(
                None,
                str(self.icon_path),
                IMAGE_ICON,
                0,
                0,
                LR_LOADFROMFILE,
            )
            if self._icon_handle:
                return self._icon_handle
        return ctypes.windll.user32.LoadIconW(None, IDI_APPLICATION)

    def _show_context_menu(self) -> None:
        user32 = ctypes.windll.user32
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        user32.AppendMenuW(menu, 0x00000000, MENU_EXIT_ID, "終了")
        user32.SetForegroundWindow(self.hwnd)
        command = user32.TrackPopupMenu(
            menu,
            TPM_RETURNCMD | TPM_RIGHTBUTTON,
            point.x,
            point.y,
            0,
            self.hwnd,
            None,
        )
        user32.DestroyMenu(menu)
        if command == MENU_EXIT_ID:
            self.exit_requested = True

    def _wndproc(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        if message == self._taskbar_created_message and self.visible:
            self.visible = False
            self.show()
            return 0
        if message == WM_TRAYICON and int(wparam) == 1:
            if int(lparam) == WM_LBUTTONDBLCLK:
                self.restore_requested = True
                return 0
            if int(lparam) == WM_RBUTTONUP:
                self._show_context_menu()
                return 0
        if self._old_wndproc is not None:
            return ctypes.windll.user32.CallWindowProcW(self._old_wndproc, hwnd, message, wparam, lparam)
        return ctypes.windll.user32.DefWindowProcW(hwnd, message, wparam, lparam)
