from __future__ import annotations

import unittest

from config import fit_note_to_base_range, midi_note_to_key, shift_midi_note


class ConfigMappingTests(unittest.TestCase):
    def test_low_octave_targets_down_shift(self) -> None:
        mapping = midi_note_to_key(21)

        self.assertIsNotNone(mapping)
        self.assertEqual(mapping.key, "n")
        self.assertEqual(mapping.octave_shift, -1)

    def test_high_octave_targets_up_shift(self) -> None:
        mapping = midi_note_to_key(84)

        self.assertIsNotNone(mapping)
        self.assertEqual(mapping.key, "z")
        self.assertEqual(mapping.octave_shift, 1)

    def test_c8_is_supported_in_high_octave(self) -> None:
        mapping = midi_note_to_key(108)

        self.assertIsNotNone(mapping)
        self.assertEqual(mapping.key, "q")
        self.assertEqual(mapping.octave_shift, 1)

    def test_base_range_has_no_modifier(self) -> None:
        mapping = midi_note_to_key(60)

        self.assertIsNotNone(mapping)
        self.assertEqual(mapping.key, "a")
        self.assertEqual(mapping.octave_shift, 0)

    def test_fit_note_to_base_range_moves_by_octaves(self) -> None:
        self.assertEqual(fit_note_to_base_range(47), 59)
        self.assertEqual(fit_note_to_base_range(84), 72)
        self.assertEqual(fit_note_to_base_range(21), 57)
        self.assertEqual(fit_note_to_base_range(108), 72)

    def test_shift_midi_note_combines_semitones_and_octaves(self) -> None:
        self.assertEqual(shift_midi_note(60, transpose_semitones=2, octave_shift=-1), 50)

    def test_shift_midi_note_rejects_values_outside_midi_range(self) -> None:
        self.assertIsNone(shift_midi_note(0, transpose_semitones=-1))
        self.assertIsNone(shift_midi_note(127, octave_shift=1))


if __name__ == "__main__":
    unittest.main()
