from __future__ import annotations

import ctypes
import unittest
from ctypes import wintypes

from device_hotplug import (
    DBT_DEVICEARRIVAL,
    DBT_DEVICEREMOVECOMPLETE,
    DBT_DEVNODES_CHANGED,
    WM_DEVICECHANGE,
    is_native_device_change,
    is_relevant_device_change,
)


class DeviceHotplugTests(unittest.TestCase):
    def test_recognizes_device_arrival_removal_and_node_changes(self) -> None:
        for event_code in (
            DBT_DEVICEARRIVAL,
            DBT_DEVICEREMOVECOMPLETE,
            DBT_DEVNODES_CHANGED,
        ):
            with self.subTest(event_code=event_code):
                self.assertTrue(
                    is_relevant_device_change(WM_DEVICECHANGE, event_code)
                )

    def test_ignores_unrelated_windows_messages_and_device_events(self) -> None:
        self.assertFalse(
            is_relevant_device_change(WM_DEVICECHANGE + 1, DBT_DEVICEARRIVAL)
        )
        self.assertFalse(is_relevant_device_change(WM_DEVICECHANGE, 0x1234))

    def test_decodes_relevant_native_windows_message(self) -> None:
        message = wintypes.MSG()
        message.message = WM_DEVICECHANGE
        message.wParam = DBT_DEVNODES_CHANGED

        self.assertTrue(
            is_native_device_change(
                b"windows_generic_MSG",
                ctypes.addressof(message),
            )
        )
        self.assertFalse(
            is_native_device_change(
                b"unrelated_event",
                ctypes.addressof(message),
            )
        )


if __name__ == "__main__":
    unittest.main()
