from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes


INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
TAP_HOLD_SECONDS = 0.03
TAP_GAP_SECONDS = 0.01


VK_TO_SCANCODE: dict[str, int] = {
    "1": 0x02,
    "2": 0x03,
    "3": 0x04,
    "4": 0x05,
    "5": 0x06,
    "6": 0x07,
    "7": 0x08,
    "8": 0x09,
    "9": 0x0A,
    "0": 0x0B,
    "q": 0x10,
    "w": 0x11,
    "e": 0x12,
    "r": 0x13,
    "t": 0x14,
    "y": 0x15,
    "u": 0x16,
    "i": 0x17,
    "o": 0x18,
    "p": 0x19,
    "[": 0x1A,
    "]": 0x1B,
    "a": 0x1E,
    "s": 0x1F,
    "d": 0x20,
    "f": 0x21,
    "g": 0x22,
    "h": 0x23,
    "j": 0x24,
    "z": 0x2C,
    "x": 0x2D,
    "c": 0x2E,
    "v": 0x2F,
    "b": 0x30,
    "n": 0x31,
    "m": 0x32,
    "<": 0x33,
    ">": 0x34,
    "space": 0x39,
    "ctrl": 0x1D,
    "shift": 0x2A,
}


class KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class InputUnion(ctypes.Union):
    _fields_ = [
        ("ki", KeyBdInput),
        ("mi", MouseInput),
        ("hi", HardwareInput),
    ]


class Input(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", InputUnion),
    ]


class KeyboardOutput:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self._lock = threading.RLock()
        self._pressed: set[str] = set()
        self._pressed_at: dict[str, float] = {}
        self._last_released_at: dict[str, float] = {}

    def press(self, key: str) -> None:
        with self._lock:
            if key in self._pressed:
                return
            self._wait_for_repeat_gap(key)
            self._send(key, key_up=False)
            self._pressed.add(key)
            self._pressed_at[key] = time.perf_counter()

    def release(self, key: str) -> None:
        with self._lock:
            if key not in self._pressed:
                return
            self._wait_for_minimum_hold(key)
            self._send(key, key_up=True)
            self._pressed.discard(key)
            self._pressed_at.pop(key, None)
            self._last_released_at[key] = time.perf_counter()

    def tap(self, key: str) -> None:
        with self._lock:
            self.press(key)
            self.release(key)
            time.sleep(TAP_GAP_SECONDS)

    def release_all(self) -> None:
        with self._lock:
            errors: list[Exception] = []
            for key in list(self._pressed):
                try:
                    self.release(key)
                except Exception as exc:
                    errors.append(exc)
            if errors:
                raise errors[0]

    def _wait_for_minimum_hold(self, key: str) -> None:
        pressed_at = self._pressed_at.get(key)
        if pressed_at is None:
            return
        held_seconds = time.perf_counter() - pressed_at
        if held_seconds < TAP_HOLD_SECONDS:
            time.sleep(TAP_HOLD_SECONDS - held_seconds)

    def _wait_for_repeat_gap(self, key: str) -> None:
        released_at = self._last_released_at.get(key)
        if released_at is None:
            return
        elapsed = time.perf_counter() - released_at
        if elapsed < TAP_GAP_SECONDS:
            time.sleep(TAP_GAP_SECONDS - elapsed)

    def _send(self, key: str, key_up: bool) -> None:
        if key not in VK_TO_SCANCODE:
            raise ValueError(f"Unsupported key: {key}")
        self._send_scancode(VK_TO_SCANCODE[key], key_up=key_up)

    def _send_scancode(self, scancode: int, key_up: bool) -> None:
        if self.dry_run:
            return

        flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if key_up else 0)
        keyboard_input = KeyBdInput(0, scancode, flags, 0, 0)
        input_struct = Input(INPUT_KEYBOARD, InputUnion(ki=keyboard_input))
        send_input = ctypes.windll.user32.SendInput
        send_input.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
        send_input.restype = wintypes.UINT
        sent = send_input(1, ctypes.byref(input_struct), ctypes.sizeof(input_struct))
        if sent != 1:
            error_code = ctypes.get_last_error()
            if error_code:
                raise ctypes.WinError(error_code)
            raise OSError("SendInput failed; the target application may be running with higher privileges")
