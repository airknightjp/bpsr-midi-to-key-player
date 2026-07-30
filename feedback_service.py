from __future__ import annotations

import json
import os
import platform
import uuid
from typing import Any

from PySide6.QtCore import QByteArray, QObject, QSettings, QTimer, QUrl, Signal
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)


DEFAULT_FEEDBACK_ENDPOINT = os.environ.get(
    "BPSR_FEEDBACK_ENDPOINT",
    "https://whale-midi-to-key-player-support.jntozw.chatgpt.site/api/feedback",
)
FEEDBACK_TIMEOUT_MS = 15_000


def build_feedback_payload(
    *,
    kind: str,
    subject: str,
    message: str,
    contact: str,
    app_version: str,
    language: str,
    client_id: str,
) -> dict[str, str]:
    os_name = f"{platform.system()} {platform.release()}".strip()
    return {
        "kind": kind.strip(),
        "subject": subject.strip(),
        "message": message.strip(),
        "contact": contact.strip(),
        "appVersion": app_version.strip(),
        "osName": os_name,
        "language": language.strip(),
        "clientId": client_id.strip(),
        "website": "",
    }


def response_error_code(status: int, body: dict[str, Any]) -> str:
    code = body.get("code")
    if code in {"duplicate", "rate_limited"}:
        return str(code)
    if status == 429:
        return "rate_limited"
    if status == 409:
        return "duplicate"
    return "server"


class FeedbackService(QObject):
    submission_succeeded = Signal(str)
    submission_failed = Signal(str, int)
    submission_progress = Signal(int)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        endpoint: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.endpoint = (
            DEFAULT_FEEDBACK_ENDPOINT if endpoint is None else endpoint
        )
        self.network = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._timed_out = False
        self._progress = 0
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._abort_timed_out_request)

    @property
    def is_sending(self) -> bool:
        return self._reply is not None

    def client_id(self) -> str:
        settings = QSettings()
        value = str(settings.value("feedback/client_id", "") or "").strip()
        if len(value) < 16:
            value = str(uuid.uuid4())
            settings.setValue("feedback/client_id", value)
        return value

    def submit(
        self,
        *,
        kind: str,
        subject: str,
        message: str,
        contact: str,
        app_version: str,
        language: str,
    ) -> bool:
        if self.is_sending:
            return False
        if not self.endpoint:
            self.submission_failed.emit("unavailable", 0)
            return False

        payload = build_feedback_payload(
            kind=kind,
            subject=subject,
            message=message,
            contact=contact,
            app_version=app_version,
            language=language,
            client_id=self.client_id(),
        )
        request = QNetworkRequest(QUrl(self.endpoint))
        request.setHeader(
            QNetworkRequest.KnownHeaders.ContentTypeHeader,
            "application/json; charset=utf-8",
        )
        request.setRawHeader(
            QByteArray(b"Accept"),
            QByteArray(b"application/json"),
        )
        request.setRawHeader(
            QByteArray(b"User-Agent"),
            QByteArray(
                f"BPSR-MIDI-to-KEY-Player/{app_version}".encode("ascii")
            ),
        )
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self._timed_out = False
        self._set_progress(0)
        self._reply = self.network.post(request, QByteArray(encoded))
        self._reply.uploadProgress.connect(self._upload_progress)
        self._reply.downloadProgress.connect(self._download_progress)
        self._reply.metaDataChanged.connect(
            self._response_metadata_changed
        )
        self._reply.finished.connect(self._request_finished)
        self._timeout.start(FEEDBACK_TIMEOUT_MS)
        return True

    def _set_progress(self, value: int) -> None:
        value = max(0, min(100, int(value)))
        if value == self._progress and value != 0:
            return
        if value != 0 and value < self._progress:
            return
        self._progress = value
        self.submission_progress.emit(value)

    def _upload_progress(self, sent: int, total: int) -> None:
        if total > 0:
            self._set_progress(round((sent / total) * 75))
        elif sent > 0:
            self._set_progress(75)

    def _download_progress(self, received: int, total: int) -> None:
        if received <= 0:
            return
        if total > 0:
            self._set_progress(75 + round((received / total) * 24))
        else:
            self._set_progress(95)

    def _response_metadata_changed(self) -> None:
        reply = self._reply
        if reply is None:
            return
        status_value = reply.attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute
        )
        status = int(status_value or 0)
        if not 200 <= status < 300:
            return
        reference_id = bytes(
            reply.rawHeader("X-Feedback-Id")
        ).decode("utf-8", errors="replace").strip()
        if not reference_id:
            return

        self._reply = None
        self._timeout.stop()
        self._set_progress(100)
        reply.abort()
        reply.deleteLater()
        self.submission_succeeded.emit(reference_id)

    def _abort_timed_out_request(self) -> None:
        reply = self._reply
        if reply is None:
            return
        self._timed_out = True
        self._reply = None
        self._timeout.stop()
        self._set_progress(0)
        reply.abort()
        reply.deleteLater()
        self.submission_failed.emit("timeout", 0)

    def _request_finished(self) -> None:
        reply = self._reply
        if reply is None:
            return
        self._reply = None
        self._timeout.stop()

        status_value = reply.attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute
        )
        status = int(status_value or 0)
        retry_value = bytes(reply.rawHeader("Retry-After"))
        try:
            retry_after = max(0, int(retry_value or b"0"))
        except ValueError:
            retry_after = 0
        raw_body = bytes(reply.readAll()).decode("utf-8", errors="replace")
        try:
            body = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            body = {}

        if self._timed_out:
            self.submission_failed.emit("timeout", 0)
        elif (
            reply.error() != QNetworkReply.NetworkError.NoError
            and status == 0
        ):
            self.submission_failed.emit("network", 0)
        elif 200 <= status < 300:
            reference_id = str(body.get("id", "")).strip()
            if not reference_id:
                reference_id = bytes(
                    reply.rawHeader("X-Feedback-Id")
                ).decode("utf-8", errors="replace").strip()
            self._set_progress(100)
            self.submission_succeeded.emit(reference_id)
        else:
            self._set_progress(0)
            self.submission_failed.emit(
                response_error_code(status, body),
                retry_after or int(body.get("retryAfter", 0) or 0),
            )
        reply.deleteLater()
