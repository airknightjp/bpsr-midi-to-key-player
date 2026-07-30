from __future__ import annotations

import os
from ctypes import wintypes


WM_DEVICECHANGE = 0x0219
DBT_DEVNODES_CHANGED = 0x0007
DBT_DEVICEARRIVAL = 0x8000
DBT_DEVICEREMOVECOMPLETE = 0x8004

WINDOWS_NATIVE_EVENT_TYPES = {
    b"windows_generic_MSG",
    b"windows_dispatcher_MSG",
}
RELEVANT_DEVICE_CHANGE_EVENTS = {
    DBT_DEVNODES_CHANGED,
    DBT_DEVICEARRIVAL,
    DBT_DEVICEREMOVECOMPLETE,
}


def is_relevant_device_change(message_id: int, event_code: int) -> bool:
    return (
        int(message_id) == WM_DEVICECHANGE
        and int(event_code) in RELEVANT_DEVICE_CHANGE_EVENTS
    )


def is_native_device_change(event_type: object, message: object) -> bool:
    if os.name != "nt":
        return False
    try:
        if bytes(event_type) not in WINDOWS_NATIVE_EVENT_TYPES:
            return False
        address = int(message)
        if address <= 0:
            return False
        native_message = wintypes.MSG.from_address(address)
    except (AttributeError, TypeError, ValueError, OverflowError, OSError):
        return False
    return is_relevant_device_change(
        native_message.message,
        native_message.wParam,
    )
