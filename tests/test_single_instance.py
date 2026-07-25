from __future__ import annotations

import inspect
import threading
import unittest

import main as qt_main
from single_instance import SingleInstance, WAIT_OBJECT_0


class SingleInstanceTests(unittest.TestCase):
    def test_qt_main_uses_an_activation_listener_instead_of_polling(self) -> None:
        source = inspect.getsource(qt_main)

        self.assertIn("start_activation_listener", source)
        self.assertNotIn("activation_timer", source)
        self.assertNotIn("consume_activation_request", source)

    def test_activation_listener_waits_for_the_windows_event(self) -> None:
        class FakeKernel32:
            def __init__(self) -> None:
                self.event = threading.Event()
                self.closed: list[int] = []

            def WaitForSingleObject(self, _handle: int, _timeout: int) -> int:
                self.event.wait(timeout=1.0)
                self.event.clear()
                return WAIT_OBJECT_0

            def SetEvent(self, _handle: int) -> bool:
                self.event.set()
                return True

            def CloseHandle(self, handle: int) -> bool:
                self.closed.append(handle)
                return True

        kernel32 = FakeKernel32()
        instance = object.__new__(SingleInstance)
        instance.window_title = "test"
        instance._event = 11
        instance._mutex = 12
        instance._kernel32 = kernel32
        instance._user32 = None
        instance._activation_stop = threading.Event()
        instance._activation_thread = None
        instance.is_primary = True
        activated = threading.Event()

        instance.start_activation_listener(activated.set)
        kernel32.SetEvent(11)

        self.assertTrue(activated.wait(timeout=1.0))
        instance.close()
        self.assertEqual(set(kernel32.closed), {11, 12})


if __name__ == "__main__":
    unittest.main()
