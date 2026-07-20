from __future__ import annotations

import unittest
from unittest.mock import patch

import main as app_main
from main import App


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
    def test_secondary_instance_notifies_existing_without_creating_app(self) -> None:
        instance = FakeSingleInstance(is_primary=False)

        with patch("main.SingleInstance", return_value=instance), patch("main.App") as app:
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
