from __future__ import annotations

import unittest
import time
from unittest.mock import patch

from auto_sustain import AUTO_SUSTAIN_EVENT_KIND
from midi_parser import MidiEvent
from sound_player import MidiSoundPlayer


class RecordingSynthClient:
    def __init__(self, messages: list[tuple[int, int, int]]) -> None:
        self.messages = messages
        self.is_open = True

    def note_on(self, channel: int, note: int, velocity: int) -> None:
        self.messages.append((0x90 | channel, note, velocity))

    def note_off(self, channel: int, note: int) -> None:
        self.messages.append((0x80 | channel, note, 0))

    def set_sustain(self, channel: int, enabled: bool) -> None:
        self.messages.append((0xB0 | channel, 64, 127 if enabled else 0))

    def release_all(self, channel: int | None = None) -> None:
        if channel is not None:
            self.messages.append((0xB0 | channel, 123, 0))

    def set_sound_source(self, _sound_source: str) -> None:
        pass


class RecordingSoundPlayer(MidiSoundPlayer):
    def __init__(self):
        super().__init__()
        self.sent_notes: list[tuple[int, int, int]] = []

    def _open_audio(self) -> bool:
        return True

    def _close_audio(self) -> None:
        pass

    def _send_note_on(
        self,
        channel: int,
        note: int,
        velocity: int,
        owner_note: int | None = None,
        output_callback=None,
    ) -> None:
        self.sent_notes.append((channel, note, velocity))
        self._active_notes.add((channel, note))

    def _send_note_off(
        self,
        channel: int,
        note: int,
        owner_note: int | None = None,
        output_callback=None,
    ) -> None:
        self._active_notes.discard((channel, note))


class RecordingShortMessageSoundPlayer(MidiSoundPlayer):
    def __init__(self, repeat_prevention: bool = False, **kwargs):
        auto_fit_note_range = kwargs.pop("auto_fit_note_range", True)
        super().__init__(
            auto_fit_note_range=auto_fit_note_range,
            repeat_prevention=repeat_prevention,
            **kwargs,
        )
        self.messages: list[tuple[int, int, int]] = []
        self._synth = RecordingSynthClient(self.messages)


class MidiSwitchTests(unittest.TestCase):
    def test_sound_player_reports_playback_failure(self) -> None:
        errors: list[str] = []
        player = RecordingSoundPlayer()
        player.on_error = errors.append
        player._handle_event = lambda _event: (_ for _ in ()).throw(
            OSError("audio failed")
        )

        player.play(
            [
                MidiEvent(
                    time=0.0,
                    kind="note_on",
                    channel=0,
                    note=60,
                    velocity=64,
                )
            ]
        )
        player.wait_until_stopped(timeout=1.0)

        self.assertEqual(errors, ["audio failed"])

    def test_clean_sound_optimization_refresh_does_not_start_worker(self) -> None:
        player = MidiSoundPlayer(chord_optimization=True)
        events = [
            MidiEvent(
                time=0.0,
                kind="note_on",
                channel=0,
                note=60,
                velocity=80,
            )
        ]
        player._refresh_chord_optimization_plan(events, force=True)

        with patch.object(
            player._optimization_planner,
            "schedule",
        ) as schedule:
            for _ in range(100):
                player._refresh_chord_optimization_plan(events)

        schedule.assert_not_called()

    def test_live_auto_fit_change_affects_following_sound_playback_notes(self) -> None:
        player = RecordingSoundPlayer()
        events = [
            MidiEvent(time=0.02, kind="note_on", channel=0, note=24, velocity=64),
            MidiEvent(time=0.08, kind="note_off", channel=0, note=24, velocity=0),
            MidiEvent(time=0.30, kind="note_on", channel=0, note=24, velocity=64),
            MidiEvent(time=0.36, kind="note_off", channel=0, note=24, velocity=0),
        ]

        player.play(events)
        deadline = time.monotonic() + 1.0
        while len(player.sent_notes) < 1 and time.monotonic() < deadline:
            time.sleep(0.005)
        player.set_auto_fit_note_range(True)
        player.wait_until_stopped(timeout=1.0)

        self.assertEqual(
            [note for _channel, note, _velocity in player.sent_notes],
            [24, 48, 48],
        )

    def test_live_auto_fit_change_remaps_held_sound_playback_notes(self) -> None:
        player = RecordingShortMessageSoundPlayer(auto_fit_note_range=False)
        player._handle_event(
            MidiEvent(time=0.0, kind="note_on", channel=0, note=24, velocity=64)
        )

        player.set_auto_fit_note_range(True)
        player._consume_release_request()

        self.assertEqual(
            [
                (status, note)
                for status, note, _value in player.messages
                if status & 0xF0 in {0x80, 0x90}
            ],
            [(0x90, 24), (0x80, 24), (0x90, 48)],
        )
        self.assertEqual(player._active_notes, {(0, 48)})

        player.set_auto_fit_note_range(False)
        player._consume_release_request()

        self.assertEqual(
            [
                (status, note)
                for status, note, _value in player.messages
                if status & 0xF0 in {0x80, 0x90}
            ],
            [
                (0x90, 24),
                (0x80, 24),
                (0x90, 48),
                (0x80, 48),
                (0x90, 24),
            ],
        )
        self.assertEqual(player._active_notes, {(0, 24)})

    def test_live_auto_fit_change_preserves_manual_sustain_state(self) -> None:
        player = RecordingShortMessageSoundPlayer(auto_fit_note_range=False)
        player._handle_event(
            MidiEvent(
                time=0.0,
                kind="sustain",
                channel=0,
                value=127,
                track=2,
            )
        )
        player._handle_event(
            MidiEvent(
                time=0.0,
                kind="note_on",
                channel=0,
                note=24,
                velocity=64,
                track=2,
            )
        )

        player.set_auto_fit_note_range(True)
        player._consume_release_request()

        self.assertEqual(player._manual_sustain_sources, {(2, 0)})
        self.assertEqual(player._sustain_channels, {0})
        self.assertEqual(player._active_notes, {(0, 48)})

    def test_sound_seek_suppresses_position_updates_from_the_old_timeline(self) -> None:
        positions: list[float] = []
        player = MidiSoundPlayer(on_position=positions.append)
        previous_generation = player._position_generation
        player._report_position(12.0, previous_generation)

        player.seek(90.0)
        player._report_position(12.1, previous_generation)
        player._report_position(90.1, player._position_generation)

        self.assertEqual(positions, [12.0, 90.0, 90.1])

    def test_sound_position_reports_are_coalesced_to_thirty_hz(self) -> None:
        positions: list[float] = []
        player = MidiSoundPlayer(on_position=positions.append)
        generation = player._position_generation

        with patch(
            "sound_player.time.perf_counter",
            side_effect=(1.0, 1.01, 1.04),
        ):
            player._report_position_if_due(1.0, generation)
            player._report_position_if_due(1.01, generation)
            player._report_position_if_due(1.04, generation)

        self.assertEqual(positions, [1.0, 1.04])

    def test_sound_player_switch_uses_new_events_without_reopening_player(self) -> None:
        player = RecordingSoundPlayer()
        original_events = [MidiEvent(time=5.0, kind="note_on", channel=0, note=60, velocity=64)]
        switched_events = [MidiEvent(time=0.0, kind="note_on", channel=1, note=64, velocity=80)]

        player.play(original_events)
        time.sleep(0.05)
        player.switch(switched_events, start_time=0.0)
        player.wait_until_stopped(timeout=1.0)

        self.assertIn((1, 64, 80), player.sent_notes)
        self.assertNotIn((0, 60, 64), player.sent_notes)

    def test_stopped_sound_player_does_not_send_next_event(self) -> None:
        player = RecordingSoundPlayer()
        events = [MidiEvent(time=0.2, kind="note_on", channel=0, note=60, velocity=64)]

        player.play(events)
        time.sleep(0.02)
        player.stop()
        player.wait_until_stopped(timeout=1.0)

        self.assertEqual(player.sent_notes, [])

    def test_auto_fit_overlapping_sound_notes_keep_note_on_until_all_are_off(self) -> None:
        player = RecordingShortMessageSoundPlayer()

        player._handle_event(MidiEvent(time=0.0, kind="note_on", channel=0, note=72, velocity=64))
        player._handle_event(MidiEvent(time=0.0, kind="note_on", channel=0, note=84, velocity=64))
        player._handle_event(MidiEvent(time=0.1, kind="note_off", channel=0, note=72, velocity=0))
        player._handle_event(MidiEvent(time=0.2, kind="note_off", channel=0, note=84, velocity=0))

        self.assertEqual(
            player.messages,
            [
                (0x90, 72, 64),
                (0x80, 72, 0),
                (0x90, 72, 64),
                (0x80, 72, 0),
                (0x90, 72, 64),
                (0x80, 72, 0),
            ],
        )

    def test_sound_release_all_clears_sustain_and_all_notes(self) -> None:
        player = RecordingShortMessageSoundPlayer()

        player._handle_event(MidiEvent(time=0.0, kind="sustain", channel=0, value=127))
        player._handle_event(MidiEvent(time=0.0, kind="note_on", channel=0, note=60, velocity=64))
        player.release_all()

        self.assertIn((0xB0, 64, 0), player.messages)
        self.assertIn((0xB0, 123, 0), player.messages)
        self.assertEqual(player._sustain_channels, set())

    def test_sound_player_reports_the_notes_sent_to_the_synth(self) -> None:
        displayed: list[tuple[int, bool]] = []
        player = RecordingShortMessageSoundPlayer(
            on_output_note=lambda note, pressed: displayed.append((note, pressed))
        )

        player._handle_event(MidiEvent(time=0.0, kind="note_on", channel=0, note=60, velocity=64))
        player._handle_event(MidiEvent(time=0.1, kind="note_off", channel=0, note=60, velocity=0))

        self.assertEqual(displayed, [(60, True), (60, False)])

    def test_sound_player_reports_the_full_piano_note_range(self) -> None:
        displayed: list[tuple[int, bool]] = []
        player = RecordingShortMessageSoundPlayer(
            auto_fit_note_range=False,
            on_output_note=lambda note, pressed: displayed.append((note, pressed))
        )

        for note in (21, 108):
            player._handle_event(
                MidiEvent(time=0.0, kind="note_on", channel=0, note=note, velocity=64)
            )
            player._handle_event(
                MidiEvent(time=0.1, kind="note_off", channel=0, note=note, velocity=0)
            )

        self.assertEqual(
            displayed,
            [(21, True), (21, False), (108, True), (108, False)],
        )

    def test_zero_volume_still_reports_keyboard_display_notes(self) -> None:
        displayed: list[tuple[int, bool]] = []
        player = RecordingShortMessageSoundPlayer(
            volume=0,
            on_output_note=lambda note, pressed: displayed.append((note, pressed)),
        )

        player._handle_event(MidiEvent(time=0.0, kind="note_on", channel=0, note=60, velocity=64))
        player._handle_event(MidiEvent(time=0.1, kind="note_off", channel=0, note=60, velocity=0))

        self.assertEqual(displayed, [(60, True), (60, False)])
        self.assertEqual(player.messages, [])

    def test_sound_display_keeps_same_pitch_active_across_channels(self) -> None:
        displayed: list[tuple[int, bool]] = []
        player = RecordingShortMessageSoundPlayer(
            on_output_note=lambda note, pressed: displayed.append((note, pressed))
        )

        player._handle_event(MidiEvent(time=0.0, kind="note_on", channel=0, note=60, velocity=64))
        player._handle_event(MidiEvent(time=0.0, kind="note_on", channel=1, note=60, velocity=64))
        player._handle_event(MidiEvent(time=0.1, kind="note_off", channel=0, note=60, velocity=0))
        player._handle_event(MidiEvent(time=0.1, kind="note_off", channel=1, note=60, velocity=0))

        self.assertEqual(displayed, [(60, True), (60, True), (60, False)])

    def test_sound_player_forwards_auto_sustain_to_the_software_synth(self) -> None:
        messages: list[tuple[int, int, int]] = []
        player = MidiSoundPlayer(auto_sustain=True)
        player._synth = RecordingSynthClient(messages)

        player._handle_event(
            MidiEvent(
                time=0.1,
                kind=AUTO_SUSTAIN_EVENT_KIND,
                channel=2,
                value=127,
                track=0,
            )
        )
        player._handle_event(
            MidiEvent(
                time=0.5,
                kind=AUTO_SUSTAIN_EVENT_KIND,
                channel=2,
                value=0,
                track=0,
            )
        )

        self.assertEqual(messages, [(0xB2, 64, 127), (0xB2, 64, 0)])
        self.assertEqual(player._active_notes, set())

    def test_sound_repeat_prevention_ignores_rapid_note_and_matching_note_off(self) -> None:
        player = RecordingShortMessageSoundPlayer(repeat_prevention=True)

        player._handle_event(
            MidiEvent(time=0.0, kind="note_on", channel=0, note=60, velocity=64),
            emitted_at=1.0,
        )
        player._handle_event(MidiEvent(time=0.01, kind="note_off", channel=0, note=60, velocity=0))
        player._handle_event(
            MidiEvent(time=0.02, kind="note_on", channel=0, note=60, velocity=64),
            emitted_at=1.02,
        )
        player._handle_event(MidiEvent(time=0.03, kind="note_off", channel=0, note=60, velocity=0))
        player._handle_event(
            MidiEvent(time=0.05, kind="note_on", channel=0, note=60, velocity=64),
            emitted_at=1.05,
        )

        self.assertEqual(
            player.messages,
            [
                (0x90, 60, 64),
                (0x80, 60, 0),
                (0x90, 60, 64),
            ],
        )

    def test_sound_repeat_prevention_uses_output_interval_after_speed_change(self) -> None:
        player = RecordingShortMessageSoundPlayer(repeat_prevention=True)

        player._handle_event(
            MidiEvent(time=0.0, kind="note_on", channel=0, note=60, velocity=64),
            emitted_at=10.0,
        )
        player._handle_event(MidiEvent(time=0.04, kind="note_off", channel=0, note=60, velocity=0))
        player._handle_event(
            MidiEvent(time=0.08, kind="note_on", channel=0, note=60, velocity=64),
            emitted_at=10.04,
        )
        player._handle_event(MidiEvent(time=0.12, kind="note_off", channel=0, note=60, velocity=0))

        self.assertEqual(player.messages, [(0x90, 60, 64), (0x80, 60, 0)])

    def test_sound_player_filters_same_channel_by_track(self) -> None:
        enabled_sources = {(0, 0)}
        player = RecordingShortMessageSoundPlayer(
            enabled_sources=lambda: enabled_sources,
        )

        player._handle_event(
            MidiEvent(
                time=0.0,
                kind="note_on",
                channel=0,
                note=60,
                velocity=64,
                track=0,
            )
        )
        player._handle_event(
            MidiEvent(
                time=0.1,
                kind="note_off",
                channel=0,
                note=60,
                velocity=0,
                track=1,
            )
        )
        player._handle_event(
            MidiEvent(
                time=0.2,
                kind="note_off",
                channel=0,
                note=60,
                velocity=0,
                track=0,
            )
        )

        self.assertEqual(
            player.messages,
            [
                (0x90, 60, 64),
                (0x80, 60, 0),
            ],
        )

    def test_sound_player_applies_transpose_and_octave_shift(self) -> None:
        player = RecordingShortMessageSoundPlayer(
            auto_fit_note_range=False,
            transpose_semitones=2,
            octave_shift=1,
        )

        player._handle_event(MidiEvent(time=0.0, kind="note_on", channel=0, note=48, velocity=64))
        player._handle_event(MidiEvent(time=0.1, kind="note_off", channel=0, note=48, velocity=0))

        self.assertEqual(player.messages, [(0x90, 62, 64), (0x80, 62, 0)])

    def test_sound_player_uses_the_same_wide_chord_optimization_plan(self) -> None:
        player = RecordingShortMessageSoundPlayer(
            auto_fit_note_range=False,
            chord_optimization=True,
        )
        note_ons = [
            MidiEvent(time=0.0, kind="note_on", channel=0, note=note, velocity=64, track=0)
            for note in (36, 64, 79, 96)
        ]
        note_offs = [
            MidiEvent(time=1.0, kind="note_off", channel=0, note=note, velocity=0, track=0)
            for note in (36, 64, 79, 96)
        ]
        events = [*note_ons, *note_offs]
        player._refresh_chord_optimization_plan(events, force=True)

        for event in events:
            player._handle_event(event)

        self.assertEqual(
            player.messages,
            [
                (0x90, 48, 64),
                (0x90, 64, 64),
                (0x90, 67, 64),
                (0x90, 72, 64),
                (0x80, 48, 0),
                (0x80, 64, 0),
                (0x80, 67, 0),
                (0x80, 72, 0),
            ],
        )

    def test_speed_change_rebuilds_sound_chord_optimization_plan(self) -> None:
        player = RecordingShortMessageSoundPlayer(
            chord_optimization=True,
            playback_speed_percent=100,
        )
        events = [MidiEvent(time=0.0, kind="note_on", channel=0, note=84, velocity=80)]
        player._refresh_chord_optimization_plan(events, force=True)

        self.assertFalse(player._chord_optimization_plan_dirty)
        self.assertEqual(player._chord_optimization_plan_speed, 100)

        player.set_playback_speed(137)

        self.assertTrue(player._chord_optimization_plan_dirty)
        player._refresh_chord_optimization_plan(events)
        player._optimization_planner.wait(timeout=1.0)
        self.assertEqual(player._chord_optimization_plan_speed, 137)


if __name__ == "__main__":
    unittest.main()
