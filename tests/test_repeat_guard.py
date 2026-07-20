from __future__ import annotations

import unittest

from repeat_guard import RapidRepeatGuard


class RapidRepeatGuardTests(unittest.TestCase):
    def test_suppresses_only_repeats_below_minimum_interval(self) -> None:
        guard = RapidRepeatGuard(enabled=True, min_interval_seconds=0.05)

        self.assertFalse(guard.should_suppress("a", 0.0))
        self.assertTrue(guard.should_suppress("a", 0.049))
        self.assertFalse(guard.should_suppress("a", 0.05))

    def test_different_tokens_are_independent(self) -> None:
        guard = RapidRepeatGuard(enabled=True, min_interval_seconds=0.05)

        self.assertFalse(guard.should_suppress("a", 1.0))
        self.assertFalse(guard.should_suppress("b", 1.01))

    def test_toggling_setting_clears_previous_history(self) -> None:
        guard = RapidRepeatGuard(enabled=True, min_interval_seconds=0.05)
        guard.should_suppress("a", 1.0)

        guard.set_enabled(False)
        guard.set_enabled(True)

        self.assertFalse(guard.should_suppress("a", 1.01))


if __name__ == "__main__":
    unittest.main()
