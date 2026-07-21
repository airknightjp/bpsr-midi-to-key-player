from __future__ import annotations

import unittest
from unittest.mock import patch

from chord_optimization import ChordOptimizationPlan
from chord_optimization_planner import (
    ChordOptimizationPlanner,
    ChordOptimizationRequest,
)
from midi_parser import MidiEvent


class ChordOptimizationPlannerTests(unittest.TestCase):
    def test_rapid_changes_are_debounced_to_the_latest_request(self) -> None:
        event = MidiEvent(time=0.0, kind="note_on", channel=0, note=60, velocity=80)
        state = {"generation": 1, "dirty": True, "speed": 100}
        committed: list[int] = []
        built_speeds: list[int] = []

        def request_provider() -> ChordOptimizationRequest | None:
            if not state["dirty"]:
                return None
            return ChordOptimizationRequest(
                generation=state["generation"],
                events=[event],
                options={
                    "auto_fit_note_range": False,
                    "playback_speed_percent": state["speed"],
                },
            )

        def commit(
            request: ChordOptimizationRequest,
            _plan: ChordOptimizationPlan,
        ) -> bool:
            if request.generation != state["generation"]:
                return False
            committed.append(request.generation)
            state["dirty"] = False
            return True

        def fake_build(_events, **options):
            built_speeds.append(int(options["playback_speed_percent"]))
            options["progress_callback"](0)
            options["progress_callback"](100)
            return ChordOptimizationPlan({}, {})

        planner = ChordOptimizationPlanner(
            request_provider=request_provider,
            request_is_current=lambda generation: generation == state["generation"],
            commit_plan=commit,
            should_stop=lambda: False,
            debounce_seconds=0.03,
        )

        with patch("chord_optimization_planner.build_chord_optimization_plan", fake_build):
            planner.schedule()
            state.update(generation=2, speed=73)
            state.update(generation=3, speed=137)
            planner.wait(timeout=1.0)

        self.assertEqual(built_speeds, [137])
        self.assertEqual(committed, [3])
