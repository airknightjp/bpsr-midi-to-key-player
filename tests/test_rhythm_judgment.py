from __future__ import annotations

import unittest

from rhythm_judgment import RhythmJudge


class RhythmJudgeTests(unittest.TestCase):
    def test_timing_windows_return_perfect_great_and_good(self) -> None:
        judge = RhythmJudge()

        judgments = []
        for index, error in enumerate((0.050, 0.075, 0.149)):
            note = 60 + index
            expected_at = 10.0 + index
            judge.record_expected(note, expected_at)
            judgments.append(judge.record_input(note, expected_at + error))
            judge.cancel_pending()

        self.assertEqual(
            tuple(
                result.judgment
                for result in judgments
                if result is not None
            ),
            ("PERFECT", "GREAT", "GOOD"),
        )

    def test_early_input_uses_the_same_timing_judgment(self) -> None:
        judge = RhythmJudge()
        judge.record_input(60, 9.930)

        result = judge.record_expected(60, 10.000)

        self.assertIsNotNone(result)
        self.assertEqual(result.judgment, "GREAT")
        self.assertAlmostEqual(result.timing_error_seconds, -0.070)

    def test_press_and_release_are_matched_independently(self) -> None:
        judge = RhythmJudge()
        judge.record_expected(60, 1.00)
        judge.record_expected(60, 1.01, released=True)

        pressed = judge.record_input(60, 1.01)
        released = judge.record_input(60, 1.00, released=True)

        self.assertIsNotNone(pressed)
        self.assertFalse(pressed.released)
        self.assertIsNotNone(released)
        self.assertTrue(released.released)

    def test_automatic_event_is_always_perfect(self) -> None:
        pressed = RhythmJudge.record_automatic_perfect(60)
        released = RhythmJudge.record_automatic_perfect(
            60,
            released=True,
        )

        self.assertEqual(pressed.judgment, "PERFECT")
        self.assertEqual(pressed.timing_error_seconds, 0.0)
        self.assertEqual(released.judgment, "PERFECT")
        self.assertTrue(released.released)

    def test_event_outside_window_does_not_create_miss_or_judgment(self) -> None:
        judge = RhythmJudge()
        judge.record_expected(60, 1.0)

        result = judge.record_input(60, 1.151)

        self.assertIsNone(result)
        self.assertFalse(hasattr(judge, "score"))
        self.assertFalse(hasattr(judge, "combo"))
        self.assertFalse(hasattr(judge, "missed_events"))

    def test_reset_discards_pending_events(self) -> None:
        judge = RhythmJudge()
        judge.record_expected(60, 1.0)

        judge.reset()

        self.assertIsNone(judge.record_input(60, 1.0))


if __name__ == "__main__":
    unittest.main()
