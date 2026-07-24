from __future__ import annotations

import unittest

from rhythm_scoring import RhythmScorer


class RhythmScorerTests(unittest.TestCase):
    def test_timing_windows_award_perfect_great_and_good_points(self) -> None:
        scorer = RhythmScorer()

        hits = []
        for index, error in enumerate((0.050, 0.075, 0.149)):
            note = 60 + index
            expected_at = 10.0 + index
            scorer.record_expected(note, expected_at)
            hits.append(scorer.record_input(note, expected_at + error))
            scorer.cancel_pending()

        self.assertEqual(
            tuple(hit.judgment for hit in hits if hit is not None),
            ("PERFECT", "GREAT", "GOOD"),
        )
        self.assertEqual(
            tuple(hit.awarded_points for hit in hits if hit is not None),
            (100, 70, 40),
        )
        self.assertEqual(scorer.score, 210)
        self.assertEqual(scorer.combo, 3)
        self.assertEqual(scorer.judgment, "GOOD")

    def test_early_input_uses_the_same_timing_judgment(self) -> None:
        scorer = RhythmScorer()

        scorer.record_input(60, 9.930)
        hit = scorer.record_expected(60, 10.000)

        self.assertIsNotNone(hit)
        self.assertEqual(hit.judgment, "GREAT")
        self.assertAlmostEqual(hit.timing_error_seconds, -0.070)

    def test_combo_multiplier_increases_every_ten_hits_and_caps_at_two(self) -> None:
        scorer = RhythmScorer()

        hits = []
        for index in range(100):
            timestamp = float(index)
            scorer.record_expected(60, timestamp)
            hits.append(scorer.record_input(60, timestamp))

        self.assertEqual(hits[8].multiplier_tenths, 10)
        self.assertEqual(hits[8].awarded_points, 100)
        self.assertEqual(hits[9].multiplier_tenths, 11)
        self.assertEqual(hits[9].awarded_points, 110)
        self.assertEqual(hits[-1].multiplier_tenths, 20)
        self.assertEqual(hits[-1].awarded_points, 200)
        self.assertEqual(scorer.combo, 100)
        self.assertEqual(scorer.multiplier_tenths, 20)

    def test_automatic_midi_only_hit_is_always_perfect(self) -> None:
        scorer = RhythmScorer()

        hit = scorer.record_automatic_perfect(60)

        self.assertEqual(hit.judgment, "PERFECT")
        self.assertEqual(hit.timing_error_seconds, 0.0)
        self.assertEqual(hit.awarded_points, 100)
        self.assertEqual(scorer.score, 100)
        self.assertEqual(scorer.combo, 1)

    def test_release_uses_the_same_timing_windows_as_press(self) -> None:
        scorer = RhythmScorer()

        scorer.record_expected(60, 10.0, released=True)
        hit = scorer.record_input(60, 10.1, released=True)

        self.assertIsNotNone(hit)
        self.assertEqual(hit.judgment, "GREAT")
        self.assertTrue(hit.released)
        self.assertEqual(scorer.score, 70)
        self.assertEqual(scorer.combo, 1)

    def test_press_and_release_events_are_matched_independently(self) -> None:
        scorer = RhythmScorer()
        scorer.record_expected(60, 1.00)
        scorer.record_expected(60, 1.01, released=True)

        press = scorer.record_input(60, 1.01)
        release = scorer.record_input(60, 1.00, released=True)

        self.assertIsNotNone(press)
        self.assertFalse(press.released)
        self.assertIsNotNone(release)
        self.assertTrue(release.released)
        self.assertEqual(scorer.score, 200)
        self.assertEqual(scorer.combo, 2)

    def test_missed_release_resets_combo_without_removing_score(self) -> None:
        scorer = RhythmScorer()
        scorer.record_automatic_perfect(60)
        scorer.record_expected(60, 1.0, released=True)

        scorer.expire(1.151)

        self.assertEqual(scorer.score, 100)
        self.assertEqual(scorer.combo, 0)
        self.assertEqual(scorer.judgment, "MISS")
        self.assertEqual(scorer.take_missed_events(), ((60, True),))
        self.assertEqual(scorer.take_missed_events(), ())

    def test_automatic_release_is_always_perfect(self) -> None:
        scorer = RhythmScorer()

        hit = scorer.record_automatic_perfect(60, released=True)

        self.assertEqual(hit.judgment, "PERFECT")
        self.assertTrue(hit.released)
        self.assertEqual(scorer.score, 100)
        self.assertEqual(scorer.combo, 1)

    def test_hold_awards_ten_points_every_100ms_without_raising_combo(self) -> None:
        scorer = RhythmScorer()
        scorer.record_expected(60, 1.0)
        scorer.record_input(60, 1.0)

        changed = scorer.advance(1.35)

        self.assertTrue(changed)
        self.assertEqual(scorer.score, 130)
        self.assertEqual(scorer.combo, 1)

    def test_hold_tick_uses_the_current_combo_multiplier(self) -> None:
        scorer = RhythmScorer()
        for note in range(10):
            scorer.record_expected(note, float(note))
            scorer.record_input(note, float(note))
            scorer.record_expected(note, float(note), released=True)
            scorer.record_input(note, float(note), released=True)
        scorer.record_expected(60, 20.0)
        scorer.record_input(60, 20.0)

        scorer.advance(20.1)

        self.assertEqual(scorer.combo, 21)
        self.assertEqual(scorer.multiplier_tenths, 12)
        self.assertEqual(scorer.score, 2_252)

    def test_early_release_stops_hold_ticks(self) -> None:
        scorer = RhythmScorer()
        scorer.record_expected(60, 1.0)
        scorer.record_input(60, 1.0)
        scorer.record_input(60, 1.25, released=True)

        scorer.advance(2.0)

        self.assertEqual(scorer.score, 120)
        self.assertEqual(scorer.combo, 1)

    def test_automatic_hold_scores_ticks_between_press_and_release(self) -> None:
        scorer = RhythmScorer()
        scorer.record_automatic_perfect(60, timestamp=1.0)

        release = scorer.record_automatic_perfect(
            60,
            released=True,
            timestamp=1.35,
        )

        self.assertTrue(release.released)
        self.assertEqual(scorer.score, 230)
        self.assertEqual(scorer.combo, 2)

    def test_next_hold_tick_reports_the_remaining_delay(self) -> None:
        scorer = RhythmScorer()
        scorer.record_expected(60, 1.0)
        scorer.record_input(60, 1.0)

        self.assertEqual(scorer.next_hold_tick_delay_ms(1.025), 75)
        scorer.advance(1.1)
        self.assertEqual(scorer.next_hold_tick_delay_ms(1.125), 75)

    def test_expected_and_input_events_are_consumed_one_to_one(self) -> None:
        scorer = RhythmScorer()

        scorer.record_expected(60, 1.0)
        scorer.record_input(60, 1.0)
        scorer.record_input(60, 1.01)

        self.assertEqual(scorer.score, 100)
        self.assertEqual(scorer.combo, 1)
        scorer.expire(1.20)
        self.assertEqual(scorer.combo, 0)

    def test_missed_note_resets_combo_without_removing_score(self) -> None:
        scorer = RhythmScorer()
        scorer.record_expected(60, 1.0)
        scorer.record_input(60, 1.0)
        scorer.cancel_pending()
        scorer.record_expected(62, 2.0)

        scorer.expire(2.151)

        self.assertEqual(scorer.score, 100)
        self.assertEqual(scorer.combo, 0)
        self.assertEqual(scorer.judgment, "MISS")
        self.assertEqual(scorer.multiplier_tenths, 10)

    def test_wrong_input_resets_combo_after_early_hit_window(self) -> None:
        scorer = RhythmScorer()
        scorer.record_expected(60, 1.0)
        scorer.record_input(60, 1.0)
        scorer.cancel_pending()
        scorer.record_input(61, 2.0)

        scorer.expire(2.151)

        self.assertEqual(scorer.score, 100)
        self.assertEqual(scorer.combo, 0)
        self.assertEqual(scorer.judgment, "MISS")
        self.assertEqual(scorer.take_missed_notes(), (61,))

    def test_outside_window_does_not_score(self) -> None:
        scorer = RhythmScorer()
        scorer.record_expected(60, 1.0)

        scorer.record_input(60, 1.151)

        self.assertEqual(scorer.score, 0)
        self.assertEqual(scorer.combo, 0)
        self.assertEqual(scorer.judgment, "MISS")

    def test_pending_miss_schedules_an_update_after_the_hit_window(self) -> None:
        scorer = RhythmScorer()
        scorer.record_expected(60, 1.0)

        self.assertEqual(scorer.next_update_delay_ms(1.0), 151)
        scorer.expire(1.151)

        self.assertEqual(scorer.judgment, "MISS")
        self.assertIsNone(scorer.next_update_delay_ms(1.151))

    def test_reset_clears_score_combo_and_pending_events(self) -> None:
        scorer = RhythmScorer()
        scorer.record_expected(60, 1.0)
        scorer.record_input(60, 1.0)
        scorer.record_expected(62, 2.0)

        scorer.reset()
        scorer.record_input(62, 2.0)

        self.assertEqual(scorer.score, 0)
        self.assertEqual(scorer.combo, 0)
        self.assertEqual(scorer.judgment, "")
        self.assertEqual(scorer.multiplier_tenths, 10)


if __name__ == "__main__":
    unittest.main()
