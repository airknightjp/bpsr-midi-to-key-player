from __future__ import annotations

import unittest
import time
import tempfile
import queue
from pathlib import Path
from unittest.mock import patch

from main import MIDI_LIST_COLUMNS, App
from midi_parser import MidiEvent, MidiSummary
from sound_player import MidiSoundPlayer


class FakeTree:
    def __init__(self, selection: str = "1"):
        self._selection = (selection,)
        self.focused: str | None = None
        self.duration_updates: list[tuple[str, str, str]] = []
        self.items: list[tuple[str, str, tuple[str, ...]]] = []

    def get_children(self) -> tuple[str, ...]:
        return tuple(item[0] for item in self.items)

    def delete(self, item: str) -> None:
        self.items = [stored for stored in self.items if stored[0] != item]

    def insert(self, parent: str, index: str, iid: str, text: str, values: tuple[str, ...]) -> None:
        self.items.append((iid, text, values))

    def selection(self) -> tuple[str, ...]:
        return self._selection

    def selection_set(self, item: str) -> None:
        self._selection = (item,)

    def focus(self, item: str) -> None:
        self.focused = item

    def set(self, item: str, column: str, value: str) -> None:
        self.duration_updates.append((item, column, value))

    def exists(self, item: str) -> bool:
        return any(stored[0] == item for stored in self.items)


class FakeScale:
    def __init__(self):
        self.configs: list[dict[str, float]] = []

    def configure(self, **kwargs: float) -> None:
        self.configs.append(kwargs)


class FakeStringVar:
    def __init__(self):
        self.values: list[str] = []

    def set(self, value: str) -> None:
        self.values.append(value)


class FakeTabs:
    def __init__(self):
        self.selected = None

    def select(self, tab: object) -> None:
        self.selected = tab


class FakeSoundPlayer:
    is_playing = True

    def __init__(self):
        self.switched_to: tuple[list[MidiEvent], float] | None = None
        self.stopped = False

    def switch(self, events: list[MidiEvent], start_time: float = 0.0) -> None:
        self.switched_to = (events, start_time)

    def stop(self) -> None:
        self.stopped = True

    def wait_until_stopped(self, timeout: float = 1.0) -> None:
        pass


class RecordingSoundPlayer(MidiSoundPlayer):
    def __init__(self):
        super().__init__()
        self.sent_notes: list[tuple[int, int, int]] = []

    def _open_midi(self) -> bool:
        return True

    def _close_midi(self) -> None:
        pass

    def _send_note_on(self, channel: int, note: int, velocity: int, owner_note: int | None = None) -> None:
        self.sent_notes.append((channel, note, velocity))
        self._active_notes.add((channel, note))

    def _send_note_off(self, channel: int, note: int) -> None:
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
        self._midi_handle = object()

    def _send_short_message(self, status: int, data1: int, data2: int) -> None:
        self.messages.append((status, data1, data2))


class ConfiguredSoundPlayer:
    instance = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.played: tuple[list[MidiEvent], float] | None = None
        ConfiguredSoundPlayer.instance = self

    def play(self, events: list[MidiEvent], start_time: float = 0.0) -> None:
        self.played = (events, start_time)


class MidiSwitchTests(unittest.TestCase):
    def test_midi_list_places_duration_before_note_range(self) -> None:
        self.assertEqual(MIDI_LIST_COLUMNS, ("duration", "note_range"))

    def make_app(self) -> App:
        app = object.__new__(App)
        app.midi_tree = FakeTree()
        app.midi_files = [Path("old.mid"), Path("new.mid")]
        app.current_play_mode = "sound"
        app.sound_player = FakeSoundPlayer()
        app.position_slider = FakeScale()
        app.state_var = FakeStringVar()
        app.duration_seconds = 0.0
        app.events = [MidiEvent(time=10.0, kind="note_on", channel=0, note=60, velocity=64)]
        app.summary = MidiSummary(Path("old.mid"), 10.0, (0,), 1)
        app.midi_note_range_labels = {}
        app.midi_duration_labels = {}
        app.updating_midi_selection = False
        app._set_channels = lambda _channels: None
        app._set_position = lambda position: setattr(app, "last_position", position)
        app._log = lambda _message: None
        app._text = lambda key: key
        app._format_time = lambda seconds: f"{seconds:.1f}"
        app.after_idle_callback = None
        app.after_idle = lambda callback: setattr(app, "after_idle_callback", callback)
        app.stop = lambda wait=False: (_ for _ in ()).throw(AssertionError("stop should not be called"))
        return app

    def test_selecting_midi_while_sound_is_playing_switches_without_stop(self) -> None:
        app = self.make_app()
        new_events = [MidiEvent(time=0.0, kind="note_on", channel=1, note=64, velocity=80)]
        new_summary = MidiSummary(Path("new.mid"), 3.0, (1,), 1)

        with patch("main.parse_midi", return_value=(new_events, new_summary)):
            App._on_midi_selected(app, None)

        self.assertEqual(app.events, new_events)
        self.assertEqual(app.summary, new_summary)
        self.assertEqual(app.sound_player.switched_to, (new_events, 0.0))
        self.assertEqual(app.last_position, 0.0)

    def test_populate_midi_list_shows_cached_durations(self) -> None:
        app = object.__new__(App)
        app.midi_tree = FakeTree()
        first = Path("first.mid")
        second = Path("second.mid")
        app.midi_files = [first, second]
        app.midi_note_range_labels = {
            first: "C3-B5",
            second: "A2-C6",
        }
        app.midi_duration_labels = {
            first: "01:23",
            second: "04:56",
        }

        App._populate_midi_list(app)

        self.assertEqual(
            app.midi_tree.items,
            [
                ("0", "first.mid", ("01:23", "C3-B5")),
                ("1", "second.mid", ("04:56", "A2-C6")),
            ],
        )

    def test_background_metadata_result_updates_matching_row(self) -> None:
        app = object.__new__(App)
        path = Path("first.mid")
        app.midi_tree = FakeTree()
        app.midi_tree.insert(
            "",
            "end",
            iid="0",
            text=path.name,
            values=("--:--", "--"),
        )
        app.midi_files = [path]
        app.midi_note_range_labels = {path: "--"}
        app.midi_duration_labels = {path: "--:--"}
        app.midi_duration_scan_id = 3
        app.midi_duration_queue = queue.Queue()
        app.midi_duration_queue.put((3, path, "C3-B5", "01:23"))
        app.exiting = True

        App._drain_midi_duration_queue(app)

        self.assertEqual(app.midi_note_range_labels[path], "C3-B5")
        self.assertEqual(app.midi_duration_labels[path], "01:23")
        self.assertEqual(
            app.midi_tree.duration_updates,
            [
                ("0", "note_range", "C3-B5"),
                ("0", "duration", "01:23"),
            ],
        )

    def test_reloading_folder_while_sound_is_playing_preserves_current_selection(self) -> None:
        app = self.make_app()
        app.midi_tree = FakeTree(selection="0")
        app.detail_tabs = FakeTabs()
        app.midi_list_tab = object()
        app._clear_log = lambda: None
        app._save_current_settings = lambda: None
        scanned_paths: list[Path] = []
        app._start_midi_duration_scan = lambda paths: scanned_paths.extend(paths)
        app._on_midi_selected = lambda _event: (_ for _ in ()).throw(
            AssertionError("folder refresh should not switch or stop playback")
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            current_path = folder / "old.mid"
            current_path.write_bytes(b"")
            (folder / "next.mid").write_bytes(b"")
            app.summary = MidiSummary(current_path, 10.0, (0,), 1)
            App._load_midi_folder(
                app,
                folder,
                save_folder=False,
                show_empty_message=True,
                preserve_sound_playback=True,
            )

        self.assertEqual(app.sound_player.switched_to, None)
        self.assertEqual(
            app.midi_tree.items,
            [
                ("0", "next.mid", ("--:--", "--")),
                ("1", "old.mid", ("--:--", "--")),
            ],
        )
        self.assertEqual([path.name for path in scanned_paths], ["next.mid", "old.mid"])
        self.assertEqual(app.midi_tree.selection(), ("1",))
        self.assertEqual(app.midi_tree.focused, "1")
        self.assertTrue(app.updating_midi_selection)
        self.assertIs(app.after_idle_callback.__self__, app)
        self.assertIs(app.after_idle_callback.__func__, App._finish_midi_selection_update)
        self.assertIs(app.detail_tabs.selected, app.midi_list_tab)

    def test_note_range_uses_standard_midi_note_names(self) -> None:
        self.assertEqual(App._format_note_range((48, 83)), "C3-B5")
        self.assertEqual(App._format_note_range((54, 61)), "F#3-C#4")
        self.assertEqual(App._format_note_range(None), "--")

    def test_midi_selection_restore_suppresses_selection_handler(self) -> None:
        app = self.make_app()
        app.updating_midi_selection = True

        with patch("main.parse_midi") as parse:
            App._on_midi_selected(app, None)

        parse.assert_not_called()

    def test_midi_selection_restore_suppresses_deferred_tree_select_event(self) -> None:
        app = self.make_app()
        app.midi_files = [Path("old.mid")]

        self.assertTrue(App._select_midi_path(app, Path("old.mid")))

        with patch("main.parse_midi") as parse:
            App._on_midi_selected(app, None)

        parse.assert_not_called()
        app.after_idle_callback()
        self.assertFalse(app.updating_midi_selection)

    def test_selecting_current_sound_midi_does_not_reload_or_log_loaded(self) -> None:
        app = self.make_app()
        app.midi_tree = FakeTree(selection="0")
        logs: list[str] = []
        app._log = logs.append

        with patch("main.parse_midi") as parse:
            App._on_midi_selected(app, None)

        parse.assert_not_called()
        self.assertEqual(logs, [])

    def test_stopping_sound_playback_logs_stopped_message(self) -> None:
        app = self.make_app()
        logs: list[str] = []
        app.playback_id = 0
        app.player = None
        app._log = logs.append
        app._text = lambda key: {
            "sound_playback_stopped": "MIDI sound playback stopped",
        }.get(key, key)
        app._refresh_playback_buttons = lambda: None
        app._refresh_midi_input_button = lambda: None
        app._refresh_option_states = lambda: None

        App.stop(app)

        self.assertTrue(app.sound_player is None)
        self.assertEqual(logs, ["MIDI sound playback stopped"])
        self.assertEqual(app.state_var.values[-1], "sound stopped")

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
        self.assertEqual(player._active_notes, set())

    def test_sound_repeat_prevention_ignores_rapid_note_and_matching_note_off(self) -> None:
        player = RecordingShortMessageSoundPlayer(repeat_prevention=True)

        player._handle_event(MidiEvent(time=0.0, kind="note_on", channel=0, note=60, velocity=64))
        player._handle_event(MidiEvent(time=0.01, kind="note_off", channel=0, note=60, velocity=0))
        player._handle_event(MidiEvent(time=0.02, kind="note_on", channel=0, note=60, velocity=64))
        player._handle_event(MidiEvent(time=0.03, kind="note_off", channel=0, note=60, velocity=0))
        player._handle_event(MidiEvent(time=0.05, kind="note_on", channel=0, note=60, velocity=64))

        self.assertEqual(
            player.messages,
            [
                (0x90, 60, 64),
                (0x80, 60, 0),
                (0x90, 60, 64),
            ],
        )

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

    def test_sound_playback_receives_chord_strum_and_speed_settings(self) -> None:
        app = object.__new__(App)
        app.current_play_mode = None
        app.summary = MidiSummary(Path("song.mid"), 3.0, (0,), 1)
        app.events = [MidiEvent(time=0.0, kind="note_on", channel=0, note=60, velocity=64)]
        app.log_queue = queue.Queue()
        app.playback_id = 0
        app.ignore_player_position_until = 0.0
        app.sound_volume_var = type("Var", (), {"get": lambda self: 80})()
        app.auto_fit_note_range_var = type("Var", (), {"get": lambda self: False})()
        app.transpose_semitones_var = type("Var", (), {"get": lambda self: 7})()
        app.octave_shift_var = type("Var", (), {"get": lambda self: -1})()
        app.humanize_timing_var = type("Var", (), {"get": lambda self: True})()
        app.chord_strum_var = type("Var", (), {"get": lambda self: True})()
        app.repeat_prevention_var = type("Var", (), {"get": lambda self: True})()
        app.playback_speed_var = type("Var", (), {"get": lambda self: 140})()
        app._play_start_position = lambda: 0.0
        app._next_playback_id = lambda: 1
        app._enabled_channels = lambda: {0}
        app._refresh_playback_buttons = lambda: None
        app._text = lambda key: key

        with patch("main.MidiSoundPlayer", ConfiguredSoundPlayer):
            App.play_sound(app)

        self.assertIsNotNone(ConfiguredSoundPlayer.instance)
        self.assertTrue(ConfiguredSoundPlayer.instance.kwargs["chord_strum"])
        self.assertTrue(ConfiguredSoundPlayer.instance.kwargs["repeat_prevention"])
        self.assertEqual(ConfiguredSoundPlayer.instance.kwargs["transpose_semitones"], 7)
        self.assertEqual(ConfiguredSoundPlayer.instance.kwargs["octave_shift"], -1)
        self.assertEqual(
            ConfiguredSoundPlayer.instance.kwargs["playback_speed_percent"],
            140,
        )


if __name__ == "__main__":
    unittest.main()
