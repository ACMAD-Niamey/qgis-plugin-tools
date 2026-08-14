# -*- coding: utf-8 -*-
"""Main upload dialog: pick a shapefile, fill in forecast metadata, upload."""

import os
from typing import Optional

from qgis.core import Qgis
from qgis.PyQt import uic
from qgis.PyQt.QtCore import QDate
from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QMessageBox

from . import shapefile_utils
from .network_client import NetworkClient
from .settings_dialog import SettingsDialog
from .settings_manager import SettingsManager

UI_PATH = os.path.join(os.path.dirname(__file__), "upload_dialog_base.ui")
FORM_CLASS, _ = uic.loadUiType(UI_PATH)

# The 12 rolling 3-month seasonal forecast period codes accepted by the
# backend (data_api.serializers.VALID_FORECAST_PERIODS). Duplicated here
# (rather than imported) since this plugin ships and installs independently
# of the Django backend repository.
FORECAST_PERIOD_CODES = [
    "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA",
    "JAS", "ASO", "SON", "OND", "NDJ", "DJF",
]


class ForecastUploadDialog(QDialog, FORM_CLASS):
    """Non-modal dialog for uploading a drought forecast shapefile."""

    def __init__(self, iface, parent=None) -> None:
        super().__init__(parent)
        self.setupUi(self)

        self.iface = iface
        self._settings = SettingsManager()
        self._shp_path: Optional[str] = None
        self._network_client: Optional[NetworkClient] = None
        self._busy = False

        self._init_widgets()
        self._connect_signals()

    # -- Setup --------------------------------------------------------

    def _init_widgets(self) -> None:
        self.forecastPeriodCombo.clear()
        self.forecastPeriodCombo.addItems(FORECAST_PERIOD_CODES)

        self.dateProducedEdit.setDate(QDate.currentDate())
        self.yearSpinBox.setValue(QDate.currentDate().year())

        self.cleanupCheckBox.setChecked(True)
        self.updateLatestCheckBox.setChecked(False)

        self.crsWarningLabel.setVisible(False)
        self.validationErrorLabel.setVisible(False)
        self.uploadProgressBar.setVisible(False)

    def _connect_signals(self) -> None:
        self.browseButton.clicked.connect(self.browse_shapefile)
        self.settingsButton.clicked.connect(self.open_settings)
        self.uploadButton.clicked.connect(self.on_upload_clicked)
        self.cancelButton.clicked.connect(self.on_cancel_clicked)

    # -- Shapefile selection & CRS check -------------------------------

    def browse_shapefile(self) -> None:
        start_dir = os.path.dirname(self._shp_path) if self._shp_path else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select forecast shapefile", start_dir, "Shapefiles (*.shp)"
        )
        if not path:
            return

        self._shp_path = path
        self.shpLineEdit.setText(path)
        self._hide_validation_error()
        self._update_shapefile_checks()

    def _update_shapefile_checks(self) -> None:
        """Warn (inline, non-blocking) about missing sidecars or a non-4326 CRS."""
        if not self._shp_path:
            return

        is_complete, missing = shapefile_utils.validate_shapefile_complete(self._shp_path)
        if not is_complete:
            QMessageBox.warning(
                self,
                "Incomplete shapefile",
                "The selected shapefile is missing required companion file(s): "
                + ", ".join(missing)
                + ".\n\nSelect a .shp file that has matching .shx/.dbf/.prj files "
                "in the same folder.",
            )

        parts = shapefile_utils.get_shapefile_parts(self._shp_path)
        prj_path = parts.get(".prj")
        is_wgs84, authid, error = shapefile_utils.check_crs_is_wgs84(prj_path)

        if error:
            self.crsWarningLabel.setText(
                f"Warning: could not verify the shapefile's CRS ({error}). "
                "The backend expects EPSG:4326 (WGS84); this plugin does not reproject."
            )
            self.crsWarningLabel.setVisible(True)
        elif not is_wgs84:
            self.crsWarningLabel.setText(
                f"Warning: shapefile CRS is {authid or 'unknown'}, not EPSG:4326 (WGS84). "
                "The backend stores geometry as WGS84 and this plugin does not reproject -- "
                "upload will still proceed, but coordinates may be misplaced."
            )
            self.crsWarningLabel.setVisible(True)
        else:
            self.crsWarningLabel.setVisible(False)
            self.crsWarningLabel.setText("")

    # -- Settings -------------------------------------------------------

    def open_settings(self) -> None:
        dialog = SettingsDialog(self)
        dialog.exec_()

    # -- Validation -------------------------------------------------------

    def _validate_form(self):
        """Return (is_valid, error_message)."""
        if not self._shp_path or not os.path.isfile(self._shp_path):
            return False, "Select a shapefile (.shp) to upload."

        is_complete, missing = shapefile_utils.validate_shapefile_complete(self._shp_path)
        if not is_complete:
            return False, (
                "Shapefile is missing required companion file(s): " + ", ".join(missing)
            )

        if not self.forecastPeriodCombo.currentText():
            return False, "Select a forecast period."

        if not self.forecastLeadNameEdit.text().strip():
            return False, "Enter a forecast lead name."

        if not self.dateProducedEdit.date().isValid():
            return False, "Set a valid date produced."

        year = self.yearSpinBox.value()
        if year < self.yearSpinBox.minimum() or year > self.yearSpinBox.maximum():
            return False, (
                f"Year must be between {self.yearSpinBox.minimum()} "
                f"and {self.yearSpinBox.maximum()}."
            )

        if not self._settings.is_configured():
            return False, (
                "Server base URL and/or API token are not configured. "
                "Open Settings to set them up."
            )

        return True, ""

    def _show_validation_error(self, message: str) -> None:
        self.validationErrorLabel.setText(message)
        self.validationErrorLabel.setVisible(True)

    def _hide_validation_error(self) -> None:
        self.validationErrorLabel.setVisible(False)
        self.validationErrorLabel.setText("")

    # -- Upload -------------------------------------------------------

    def on_upload_clicked(self) -> None:
        is_valid, error_message = self._validate_form()
        if not is_valid:
            self._show_validation_error(error_message)
            if not self._settings.is_configured():
                answer = QMessageBox.question(
                    self,
                    "Settings required",
                    "The server base URL and/or API token are not configured yet.\n\n"
                    "Open Settings now?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if answer == QMessageBox.Yes:
                    self.open_settings()
            return

        self._hide_validation_error()

        fields = {
            "forecast_period": self.forecastPeriodCombo.currentText(),
            "forecast_lead_name": self.forecastLeadNameEdit.text().strip(),
            "date_produced": self.dateProducedEdit.date().toString("yyyy-MM-dd"),
            "year": str(self.yearSpinBox.value()),
            "cleanup": "true" if self.cleanupCheckBox.isChecked() else "false",
            "update_latest": "true" if self.updateLatestCheckBox.isChecked() else "false",
        }

        self._set_busy(True)

        base_url = self._settings.get_base_url()
        token = self._settings.get_token()

        # Parented to self so the client (and its in-flight QNetworkReply)
        # is not garbage collected while the async request is running.
        self._network_client = NetworkClient(base_url, token, parent=self)
        self._network_client.uploadProgress.connect(self._on_upload_progress)
        self._network_client.uploadFinished.connect(self._on_upload_finished)
        self._network_client.upload_forecast(self._shp_path, fields)

    def _on_upload_progress(self, bytes_sent: int, bytes_total: int) -> None:
        if bytes_total > 0:
            self.uploadProgressBar.setMaximum(100)
            self.uploadProgressBar.setValue(int(bytes_sent * 100 / bytes_total))
        else:
            # Total size unknown (or not yet known) -- fall back to a
            # "busy" indeterminate bar rather than showing a stuck 0%.
            self.uploadProgressBar.setMaximum(0)

    def _on_upload_finished(self, success: bool, message: str, status_code) -> None:
        self._set_busy(False)
        self._network_client = None

        level = Qgis.Success if success else Qgis.Critical
        self.iface.messageBar().pushMessage(
            "ACMAD Forecast Ingest", message, level=level, duration=8
        )

        if success:
            self._clear_form()

    def on_cancel_clicked(self) -> None:
        if self._busy and self._network_client is not None:
            self._network_client.abort()
            return
        self.reject()

    def closeEvent(self, event) -> None:  # noqa: N802 -- Qt override
        if self._busy:
            answer = QMessageBox.question(
                self,
                "Upload in progress",
                "An upload is still in progress. Abort it and close?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            if self._network_client is not None:
                self._network_client.abort()
        event.accept()

    # -- Busy state / form reset -------------------------------------------------------

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.uploadButton.setEnabled(not busy)
        self.uploadProgressBar.setVisible(busy)
        if busy:
            self.uploadProgressBar.setMaximum(0)
            self.uploadProgressBar.setValue(0)

        for widget in (
            self.browseButton,
            self.forecastPeriodCombo,
            self.forecastLeadNameEdit,
            self.dateProducedEdit,
            self.yearSpinBox,
            self.cleanupCheckBox,
            self.updateLatestCheckBox,
            self.settingsButton,
        ):
            widget.setEnabled(not busy)

    def _clear_form(self) -> None:
        """Reset the shapefile picker (and lead name) after a successful upload."""
        self._shp_path = None
        self.shpLineEdit.clear()
        self.crsWarningLabel.setVisible(False)
        self.crsWarningLabel.setText("")
        self.forecastLeadNameEdit.clear()
        self._hide_validation_error()
