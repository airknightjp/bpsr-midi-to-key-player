from __future__ import annotations

import inspect
import threading
import unittest
from unittest.mock import patch

import legacy_tk_main as app_main
import main as qt_main
from legacy_tk_main import App
from single_instance import SingleInstance, WAIT_OBJECT_0


class FakeSingleInstance:
    def __init__(self, is_primary: bool):
        self.is_primary = is_primary
        self.notified = False
        self.closed = False
        self.activation_requested = False
        self.brought_to_front = False

    def notify_existing(self) -> None:
        self.notified = True

    def consume_activation_request(self) -> bool:
        requested = self.activation_requested
        self.activation_requested = False
        return requested

    def close(self) -> None:
        self.closed = True

    def bring_existing_window_to_front(self) -> None:
        self.brought_to_front = True


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

    def test_secondary_instance_notifies_existing_without_creating_app(self) -> None:
        instance = FakeSingleInstance(is_primary=False)

        with patch("legacy_tk_main.SingleInstance", return_value=instance), patch("legacy_tk_main.App") as app:
            app_main.main()

        app.assert_not_called()
        self.assertTrue(instance.notified)
        self.assertTrue(instance.closed)

    def test_activation_request_restores_and_raises_existing_window(self) -> None:
        app = object.__new__(App)
        instance = FakeSingleInstance(is_primary=True)
        instance.activation_requested = True
        app.single_instance = instance
        app.exiting = False
        restored: list[bool] = []
        topmost: list[tuple[str, bool]] = []
        callbacks: list[tuple[int, object]] = []
        app._restore_from_tray = lambda: restored.append(True)
        app.attributes = lambda name, value: topmost.append((name, value))
        app._apply_always_on_top = lambda: None
        app.after = lambda delay, callback: callbacks.append((delay, callback))

        App._poll_single_instance(app)

        self.assertEqual(restored, [True])
        self.assertTrue(instance.brought_to_front)
        self.assertEqual(topmost, [("-topmost", True)])
        self.assertIn((100, app._apply_always_on_top), callbacks)
        self.assertIn((100, app._poll_single_instance), callbacks)


if __name__ == "__main__":
    unittest.main()
