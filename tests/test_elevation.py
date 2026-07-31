from __future__ import annotations

import unittest
from unittest.mock import patch

import elevation


class ElevationTests(unittest.TestCase):
    def test_disabled_preference_does_not_request_elevation(self) -> None:
        with patch.object(
            elevation,
            "is_running_as_administrator",
        ) as is_administrator:
            self.assertFalse(
                elevation.relaunch_as_administrator_if_requested(False)
            )
        is_administrator.assert_not_called()

    def test_already_elevated_process_continues_without_relaunch(self) -> None:
        with (
            patch.object(
                elevation,
                "is_running_as_administrator",
                return_value=True,
            ),
            patch.object(elevation, "launch_as_administrator") as launch,
        ):
            self.assertFalse(
                elevation.relaunch_as_administrator_if_requested(True)
            )
        launch.assert_not_called()

    def test_requested_elevation_exits_launcher_after_success(self) -> None:
        with (
            patch.object(
                elevation,
                "is_running_as_administrator",
                return_value=False,
            ),
            patch.object(
                elevation,
                "launch_as_administrator",
                return_value=True,
            ) as launch,
        ):
            self.assertTrue(
                elevation.relaunch_as_administrator_if_requested(True)
            )
        launch.assert_called_once_with()

    def test_cancelled_elevation_keeps_normal_launch_running(self) -> None:
        with (
            patch.object(
                elevation,
                "is_running_as_administrator",
                return_value=False,
            ),
            patch.object(
                elevation,
                "launch_as_administrator",
                return_value=False,
            ),
        ):
            self.assertFalse(
                elevation.relaunch_as_administrator_if_requested(True)
            )
