# -*- coding: utf-8 -*-
"""Async HTTP client for the ACMAD forecast upload endpoint.

Built entirely on Qt's own network stack (``QNetworkAccessManager`` /
``QNetworkRequest`` / ``QHttpMultiPart``) rather than the ``requests``
library: QGIS's bundled Python does not reliably ship (or allow installing
into) third-party packages, whereas Qt's network classes are always
available and this is the standard, idiomatic PyQGIS pattern for
non-blocking HTTP from a plugin. All requests are asynchronous -- callers
connect to the ``*_finished`` signals rather than blocking the QGIS UI
thread.
"""

import json
import os
import shutil
from typing import Dict, Optional

from qgis.PyQt.QtCore import QByteArray, QFile, QIODevice, QObject, QUrl, pyqtSignal
from qgis.PyQt.QtNetwork import (
    QHttpMultiPart,
    QHttpPart,
    QNetworkAccessManager,
    QNetworkRequest,
)

from . import shapefile_utils

FORECAST_UPLOAD_PATH = "/api/data_api/data_upload/forecast/"


class NetworkClient(QObject):
    """Handles both the "test connection" probe and the forecast upload.

    Signals:
        uploadProgress(int, int): bytes sent, total bytes (upload only).
        uploadFinished(bool, str, object): success flag, user-facing
            message, HTTP status code (int) or None if the request never
            reached the server (network-level failure).
        testConnectionFinished(bool, str): success flag, user-facing
            message.
    """

    uploadProgress = pyqtSignal(int, int)
    uploadFinished = pyqtSignal(bool, str, object)
    testConnectionFinished = pyqtSignal(bool, str)

    def __init__(self, base_url: str, token: str, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._base_url = (base_url or "").strip().rstrip("/")
        self._token = (token or "").strip()

        # One QNetworkAccessManager per client instance, kept alive for the
        # instance's lifetime -- QNetworkReply objects it creates must not
        # outlive it.
        self._manager = QNetworkAccessManager(self)

        # Kept as instance attributes (not locals) so they are not garbage
        # collected while the async request is in flight.
        self._reply = None
        self._multipart = None
        self._temp_dir: Optional[str] = None

    def _endpoint_url(self) -> str:
        return f"{self._base_url}{FORECAST_UPLOAD_PATH}"

    def _auth_header_value(self) -> QByteArray:
        return QByteArray(f"Token {self._token}".encode("utf-8"))

    # -- Test connection -------------------------------------------------

    def test_connection(self) -> None:
        """Fire an authenticated OPTIONS request at the upload endpoint.

        DRF's ``IsAuthenticated`` permission is enforced on OPTIONS too, so
        a 200 response confirms both that the server is reachable and that
        the token is valid; 401/403 means the token is missing/invalid.
        """
        request = QNetworkRequest(QUrl(self._endpoint_url()))
        request.setRawHeader(b"Authorization", bytes(self._auth_header_value()))

        reply = self._manager.sendCustomRequest(request, b"OPTIONS")
        self._reply = reply
        reply.finished.connect(lambda: self._on_test_connection_finished(reply))

    def _on_test_connection_finished(self, reply) -> None:
        status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)

        if status_code is None:
            # No HTTP status at all => the request never got a response:
            # DNS failure, connection refused, TLS error, timeout, etc.
            self.testConnectionFinished.emit(
                False, f"Could not reach server: {reply.errorString()}"
            )
        elif status_code == 200:
            self.testConnectionFinished.emit(
                True, "Connection OK -- server reachable and token accepted."
            )
        elif status_code in (401, 403):
            self.testConnectionFinished.emit(
                False,
                f"Authentication failed (HTTP {status_code}). "
                "Check that the API token is correct.",
            )
        else:
            self.testConnectionFinished.emit(
                False, f"Unexpected response from server (HTTP {status_code})."
            )

        reply.deleteLater()
        self._reply = None

    # -- Forecast upload ---------------------------------------------------

    def upload_forecast(self, shp_path: str, fields: Dict[str, str]) -> None:
        """Zip the shapefile parts and POST them + metadata fields.

        Args:
            shp_path: Path to the selected .shp file.
            fields: Form field name -> string value, e.g. forecast_period,
                forecast_lead_name, date_produced, year, cleanup,
                update_latest. Values are sent as-is (already stringified
                by the caller).
        """
        try:
            zip_path, temp_dir = shapefile_utils.zip_shapefile(shp_path)
        except (OSError, FileNotFoundError) as exc:
            self.uploadFinished.emit(
                False, f"Failed to prepare shapefile archive: {exc}", None
            )
            return

        self._temp_dir = temp_dir

        multipart = QHttpMultiPart(QHttpMultiPart.FormDataType)

        for name, value in fields.items():
            part = QHttpPart()
            part.setHeader(
                QNetworkRequest.ContentDispositionHeader,
                f'form-data; name="{name}"',
            )
            part.setBody(str(value).encode("utf-8"))
            multipart.append(part)

        file_part = QHttpPart()
        file_part.setHeader(
            QNetworkRequest.ContentDispositionHeader,
            f'form-data; name="file"; filename="{os.path.basename(zip_path)}"',
        )
        file_part.setHeader(QNetworkRequest.ContentTypeHeader, "application/zip")

        zip_file = QFile(zip_path)
        if not zip_file.open(QIODevice.ReadOnly):
            self.uploadFinished.emit(
                False, f"Could not open zip archive for upload: {zip_path}", None
            )
            self._cleanup_temp_dir()
            return

        # Parenting the QFile to the multipart (and the multipart to the
        # reply, below) ties their C++ lifetimes to the request so they
        # stay alive until Qt deletes the reply -- the standard
        # QHttpMultiPart file-upload idiom.
        zip_file.setParent(multipart)
        file_part.setBodyDevice(zip_file)
        multipart.append(file_part)

        request = QNetworkRequest(QUrl(self._endpoint_url()))
        request.setRawHeader(b"Authorization", bytes(self._auth_header_value()))

        reply = self._manager.post(request, multipart)
        multipart.setParent(reply)

        self._reply = reply
        self._multipart = multipart

        reply.uploadProgress.connect(self.uploadProgress.emit)
        reply.finished.connect(lambda: self._on_upload_finished(reply))

    def abort(self) -> None:
        """Abort an in-flight upload or test-connection request, if any."""
        if self._reply is not None:
            self._reply.abort()

    def _on_upload_finished(self, reply) -> None:
        status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        raw_bytes = bytes(reply.readAll())

        parsed = None
        if raw_bytes:
            try:
                parsed = json.loads(raw_bytes.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                parsed = None

        server_message = None
        if isinstance(parsed, dict):
            server_message = parsed.get("message")

        if status_code is None:
            # Network-level failure: never reached the server, so this is
            # distinct from a server-side validation error and should read
            # differently to the user.
            message = f"Network error -- could not reach server: {reply.errorString()}"
            self.uploadFinished.emit(False, message, None)
        elif status_code == 200 and isinstance(parsed, dict) and parsed.get("status") == "success":
            self.uploadFinished.emit(
                True, server_message or "Forecast uploaded successfully.", status_code
            )
        else:
            fallback_message = (
                server_message
                or reply.errorString()
                or f"Upload failed (HTTP {status_code})."
            )
            self.uploadFinished.emit(False, fallback_message, status_code)

        reply.deleteLater()
        self._reply = None
        self._multipart = None
        self._cleanup_temp_dir()

    def _cleanup_temp_dir(self) -> None:
        """Remove the temporary directory holding the zipped shapefile."""
        if self._temp_dir:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None
