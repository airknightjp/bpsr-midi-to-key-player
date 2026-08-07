from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from starra_guitar_bank import get_starra_guitar_bank


class StarraGuitarBankTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assets = Path(__file__).resolve().parents[1] / "assets"

    def test_bank_contains_the_measured_c3_to_b4_notes(self) -> None:
        bank = get_starra_guitar_bank()

        self.assertEqual(bank.sample_rate, 48_000)
        self.assertEqual(bank.notes.tolist(), list(range(48, 72)))
        self.assertEqual(bank.samples.dtype, np.int16)
        self.assertTrue(np.all(bank.lengths > 0))
        self.assertEqual(bank.analysis["partial_count"], 32)
        self.assertEqual(bank.analysis["residual_band_count"], 32)

    def test_exact_note_uses_its_own_resynthesized_sample(self) -> None:
        sample = get_starra_guitar_bank().select(60, 48_000)

        self.assertEqual(sample.bank_index, 12)
        self.assertEqual(sample.source_note, 60)
        self.assertEqual(sample.playback_step, 1.0)

    def test_notes_outside_the_measured_range_use_the_nearest_sample(self) -> None:
        bank = get_starra_guitar_bank()
        low = bank.select(40, 48_000)
        high = bank.select(80, 48_000)

        self.assertEqual(low.source_note, 48)
        self.assertLess(low.playback_step, 1.0)
        self.assertEqual(high.source_note, 71)
        self.assertGreater(high.playback_step, 1.0)

    def test_output_sample_rate_is_part_of_the_playback_step(self) -> None:
        sample = get_starra_guitar_bank().select(60, 8_000)

        self.assertEqual(sample.playback_step, 6.0)

    def test_analysis_model_contains_the_complete_time_varying_sms_data(self) -> None:
        with np.load(
            self.assets / "starra_guitar_model.npz",
            allow_pickle=False,
        ) as model:
            expected = {
                "f0_hz",
                "partial_frequency_hz",
                "partial_amplitude",
                "partial_phase",
                "formant_envelope",
                "residual_band_rms",
                "inharmonicity",
                "transient_magnitude",
                "transient_phase",
            }
            self.assertTrue(expected.issubset(model.files))
            self.assertEqual(int(model["frame_size"][0]), 4_096)
            self.assertEqual(int(model["hop_size"][0]), 512)
            self.assertEqual(model["partial_frequency_hz"].shape[2], 32)
            self.assertEqual(model["residual_band_rms"].shape[2], 32)
            frame_counts = model["frame_counts"]
            for index, frame_count in enumerate(frame_counts):
                valid_frames = slice(0, int(frame_count))
                for name in (
                    "f0_hz",
                    "partial_frequency_hz",
                    "partial_amplitude",
                    "partial_phase",
                    "formant_envelope",
                    "residual_band_rms",
                    "inharmonicity",
                ):
                    self.assertTrue(
                        np.all(np.isfinite(model[name][index, valid_frames])),
                        name,
                    )
                self.assertGreater(
                    float(np.max(model["partial_amplitude"][index, valid_frames])),
                    0.0,
                )
                self.assertGreater(
                    float(np.max(model["residual_band_rms"][index, valid_frames])),
                    0.0,
                )


if __name__ == "__main__":
    unittest.main()
