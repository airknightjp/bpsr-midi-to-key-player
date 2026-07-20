from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable
from ctypes import wintypes


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012


HotkeyCallback = Callable[[str], None]


class HotkeySpec:
    def __init__(self, action: str, modifiers: int, vk: int):
        self.action = action
        self.modifiers = modifiers
        self.vk = vk


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


class GlobalHotkeyManager:
    def __init__(self, specs: list[HotkeySpec], callback: HotkeyCallback):
        self.specs = specs
        self.callback = callback
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._registered_count = 0
        self._failed_actions: tuple[str, ...] = ()

    def start(self) -> None:
        if not self.specs or self._thread is not None:
            return
        with self._lock:
            self._registered_count = 0
            self._failed_actions = ()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=1.0)

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop_event.set()
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread.join(timeout=1.0)
        self._thread = None
        self._thread_id = 0
        self._ready.clear()
        with self._lock:
            self._registered_count = 0
            self._failed_actions = ()

    @property
    def registered_count(self) -> int:
        with self._lock:
            return self._registered_count

    @property
    def is_healthy(self) -> bool:
        if not self.specs:
            return True
        thread = self._thread
        return (
            thread is not None
            and thread.is_alive()
            and self.registered_count == len(self.specs)
        )

    @property
    def failed_actions(self) -> tuple[str, ...]:
        with self._lock:
            return self._failed_actions

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        registered: dict[int, HotkeySpec] = {}
        try:
            for index, spec in enumerate(self.specs, start=1):
                if user32.RegisterHotKey(None, index, spec.modifiers | MOD_NOREPEAT, spec.vk):
                    registered[index] = spec
            with self._lock:
                self._registered_count = len(registered)
                self._failed_actions = tuple(
                    spec.action
                    for index, spec in enumerate(self.specs, start=1)
                    if index not in registered
                )
            self._ready.set()

            message = MSG()
            while not self._stop_event.is_set():
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0:
                    break
                if message.message == WM_HOTKEY:
                    spec = registered.get(int(message.wParam))
                    if spec is not None:
                        self.callback(spec.action)
        except Exception:
            with self._lock:
                self._failed_actions = tuple(spec.action for spec in self.specs)
        finally:
            for hotkey_id in registered:
                user32.UnregisterHotKey(None, hotkey_id)
            with self._lock:
                self._registered_count = 0
            self._ready.set()


def shortcut_to_hotkey_spec(shortcut: str, action: str) -> HotkeySpec | None:
    value = shortcut.strip()
    if not value:
        return None
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1]
    parts = [part for part in value.replace("-", "+").replace(" ", "").split("+") if part]
    if not parts:
        return None

    modifiers = 0
    for part in parts[:-1]:
        lowered = part.lower()
        if lowered in {"ctrl", "control"}:
            modifiers |= MOD_CONTROL
        elif lowered == "alt":
            modifiers |= MOD_ALT
        elif lowered == "shift":
            modifiers |= MOD_SHIFT
        else:
            return None

    vk = _key_to_vk(parts[-1])
    if vk is None:
        return None
    return HotkeySpec(action=action, modifiers=modifiers, vk=vk)


def _key_to_vk(key: str) -> int | None:
    lowered = key.lower()
    aliases = {
        "esc": 0x1B,
        "escape": 0x1B,
        "enter": 0x0D,
        "return": 0x0D,
        "space": 0x20,
        "tab": 0x09,
        "backspace": 0x08,
        "back_space": 0x08,
        "pause": 0x13,
        "capslock": 0x14,
        "caps_lock": 0x14,
        "pageup": 0x21,
        "prior": 0x21,
        "pagedown": 0x22,
        "next": 0x22,
        "end": 0x23,
        "home": 0x24,
        "left": 0x25,
        "up": 0x26,
        "right": 0x27,
        "down": 0x28,
        "insert": 0x2D,
        "delete": 0x2E,
    }
    if lowered in aliases:
        return aliases[lowered]
    if lowered.startswith("f"):
        try:
            number = int(lowered[1:])
        except ValueError:
            return None
        if 1 <= number <= 24:
            return 0x70 + number - 1
    if len(key) == 1:
        char = key.upper()
        if "A" <= char <= "Z" or "0" <= char <= "9":
            return ord(char)
    return None
