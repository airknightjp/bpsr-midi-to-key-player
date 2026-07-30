from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QByteArray
from PySide6.QtNetwork import QNetworkRequest

from feedback_service import (
    FeedbackService,
    build_feedback_payload,
    response_error_code,
)


class FeedbackServiceTests(unittest.TestCase):
    def test_payload_includes_only_expected_environment_fields(self) -> None:
        with (
            patch("feedback_service.platform.system", return_value="Windows"),
            patch("feedback_service.platform.release", return_value="11"),
        ):
            payload = build_feedback_payload(
                kind=" bug ",
                subject="  Notes hang  ",
                message="  Steps to reproduce  ",
                contact=" user@example.com ",
                app_version="1.7.2",
                language="ja",
                client_id="11111111-2222-3333-4444-555555555555",
            )

        self.assertEqual(payload["kind"], "bug")
        self.assertEqual(payload["subject"], "Notes hang")
        self.assertEqual(payload["osName"], "Windows 11")
        self.assertEqual(payload["website"], "")
        self.assertNotIn("midi", payload)
        self.assertNotIn("log", payload)

    def test_response_error_code_prefers_server_abuse_codes(self) -> None:
        self.assertEqual(
            response_error_code(429, {"code": "rate_limited"}),
            "rate_limited",
        )
        self.assertEqual(
            response_error_code(409, {"code": "duplicate"}),
            "duplicate",
        )
        self.assertEqual(response_error_code(500, {}), "server")

    def test_timeout_immediately_releases_sending_state(self) -> None:
        service = FeedbackService(endpoint="https://example.invalid")
        reply = Mock()
        failures: list[tuple[str, int]] = []
        service.submission_failed.connect(
            lambda code, retry_after: failures.append((code, retry_after))
        )
        service._reply = reply

        service._abort_timed_out_request()

        self.assertFalse(service.is_sending)
        self.assertEqual(failures, [("timeout", 0)])
        reply.abort.assert_called_once_with()
        reply.deleteLater.assert_called_once_with()

    def test_success_headers_immediately_complete_submission(self) -> None:
        service = FeedbackService(endpoint="https://example.invalid")
        reply = Mock()
        reply.attribute.return_value = 201
        reply.rawHeader.return_value = QByteArray(
            b"12345678-abcd-efgh-ijkl-123456789012"
        )
        successes: list[str] = []
        service.submission_succeeded.connect(successes.append)
        service._reply = reply

        service._response_metadata_changed()

        self.assertFalse(service.is_sending)
        self.assertEqual(
            successes,
            ["12345678-abcd-efgh-ijkl-123456789012"],
        )
        reply.attribute.assert_called_once_with(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute
        )
        reply.rawHeader.assert_called_once_with("X-Feedback-Id")
        reply.abort.assert_called_once_with()
        reply.deleteLater.assert_called_once_with()

    def test_progress_tracks_upload_and_download(self) -> None:
        service = FeedbackService(endpoint="https://example.invalid")
        progress: list[int] = []
        service.submission_progress.connect(progress.append)

        service._upload_progress(1, 2)
        service._download_progress(1, 2)

        self.assertEqual(progress, [38, 87])

        service._set_progress(100)
        service._upload_progress(1, 2)
        self.assertEqual(progress, [38, 87, 100])


if __name__ == "__main__":
    unittest.main()
