# -*- coding: utf-8 -*-
"""Main upload dialog: pick a shapefile, fill in forecast metadata, upload."""

import os
import re
import shutil
import tempfile
from typing import List, Optional

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsMapLayerProxyModel,
    QgsProject,
    QgsVectorFileWriter,
)
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt import uic
from qgis.PyQt.QtCore import QDate
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QRadioButton,
)

from ...core.settings_manager import SettingsManager
from . import shapefile_utils
from .network_client import NetworkClient
from .settings_dialog import SettingsDialog

# Field the backend maps to `forecast_category_code` when ingesting a
# forecast polygon layer (see the backend's data_api/load.py
# layer_mapping_forecast_polygon dict -- not duplicated here beyond this
# field name, kept in sync by convention since the two repos ship
# independently).
FCST_CAT_FIELD = "fcst_cat"

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

# First entry in categoryFieldCombo when it's populated -- not a real field
# name, just a prompt. Validation treats currentIndex() <= 0 as "nothing
# chosen yet" so this always occupies index 0.
CATEGORY_FIELD_PLACEHOLDER = "-- Select column --"


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
        # Set only while a "Loaded layer" upload's temp-exported shapefile
        # directory is on disk and still needs cleaning up (mirrors how
        # NetworkClient tracks/cleans its own zip temp dir).
        self._layer_export_dir: Optional[str] = None

        # Attribute field names detected on the currently-selected source
        # (file or loaded layer), and whether FCST_CAT_FIELD is among them.
        # Updated by _update_category_field_options() whenever the source
        # selection or the underlying file/layer changes; consulted by
        # _validate_form() and on_upload_clicked() so the "which column
        # holds the forecast category" decision is made in one place.
        self._current_field_names: List[str] = []
        self._fcst_cat_present: bool = True

        self._init_source_widgets()
        self._init_widgets()
        self._connect_signals()

    # -- Setup --------------------------------------------------------

    def _init_source_widgets(self) -> None:
        """Build the file-vs-loaded-layer source toggle in code.

        Constructed programmatically (rather than hand-edited into the
        .ui) so we don't need a QgsMapLayerComboBox custom-widget
        promotion block in the XML, which would be harder to get right
        without a QGIS instance to test against. Inserted into the
        existing ``shapefileGroupLayout`` (see upload_dialog_base.ui)
        alongside the current file-picker row.
        """
        self.sourceFileRadio = QRadioButton("File on disk")
        self.sourceLayerRadio = QRadioButton("Loaded layer")
        self.sourceFileRadio.setChecked(True)

        source_radio_layout = QHBoxLayout()
        source_radio_layout.addWidget(self.sourceFileRadio)
        source_radio_layout.addWidget(self.sourceLayerRadio)
        source_radio_layout.addStretch(1)

        self.noPolygonLayersLabel = QLabel(
            "No polygon layers are currently loaded in this project."
        )
        self.noPolygonLayersLabel.setWordWrap(True)
        self.noPolygonLayersLabel.setVisible(False)
        # Matches the existing crsWarningLabel's inline-warning style.
        self.noPolygonLayersLabel.setStyleSheet(
            "color: #8a6d00; background-color: #fff3cd; border: 1px solid "
            "#ffe69c; padding: 4px; border-radius: 3px;"
        )

        self.layerCombo = QgsMapLayerComboBox()
        self.layerCombo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.layerCombo.setVisible(False)

        # Shown only when the selected source's fields don't include
        # FCST_CAT_FIELD -- see _update_category_field_options(). Plain
        # QComboBox (not a QGIS-specific widget) since it just lists
        # detected field-name strings.
        self.categoryFieldLabel = QLabel("Forecast category field:")
        self.categoryFieldLabel.setVisible(False)
        self.categoryFieldCombo = QComboBox()
        self.categoryFieldCombo.setVisible(False)

        # shapefileGroupLayout is the QVBoxLayout named in
        # upload_dialog_base.ui that currently holds (in order):
        #   [0] shapefilePickerLayout (QHBoxLayout: shpLineEdit + browseButton)
        #   [1] crsWarningLabel
        # We insert the new source-toggle row and "no layers" notice above
        # the file picker, the layer combo directly below it, and the
        # category-field label/combo at the very end, giving:
        #   [0] source_radio_layout (new)
        #   [1] noPolygonLayersLabel (new)
        #   [2] shapefilePickerLayout (existing)
        #   [3] layerCombo (new)
        #   [4] crsWarningLabel (existing, shifted down)
        #   [5] categoryFieldLabel (new)
        #   [6] categoryFieldCombo (new)
        self.shapefileGroupLayout.insertLayout(0, source_radio_layout)
        self.shapefileGroupLayout.insertWidget(1, self.noPolygonLayersLabel)
        self.shapefileGroupLayout.insertWidget(3, self.layerCombo)
        self.shapefileGroupLayout.addWidget(self.categoryFieldLabel)
        self.shapefileGroupLayout.addWidget(self.categoryFieldCombo)

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

        self._refresh_layer_source_availability()

    def _connect_signals(self) -> None:
        self.browseButton.clicked.connect(self.browse_shapefile)
        self.settingsButton.clicked.connect(self.open_settings)
        self.uploadButton.clicked.connect(self.on_upload_clicked)
        self.cancelButton.clicked.connect(self.on_cancel_clicked)

        self.sourceFileRadio.toggled.connect(self._on_source_toggled)
        self.layerCombo.layerChanged.connect(self._on_layer_combo_changed)

    # -- Source toggle (file on disk vs. loaded layer) -----------------

    def _on_source_toggled(self, _checked: bool) -> None:
        """Show/hide the file-picker widgets vs. the layer combo box.

        Connected to sourceFileRadio.toggled only: since the two radio
        buttons share a parent widget (auto-exclusive in Qt), whichever
        one changes state the other flips too, so reading
        sourceFileRadio.isChecked() here is always accurate regardless of
        which radio the user actually clicked.
        """
        is_file = self.sourceFileRadio.isChecked()
        self.shpLineEdit.setVisible(is_file)
        self.browseButton.setVisible(is_file)
        self.layerCombo.setVisible(not is_file)

        self._hide_validation_error()
        if is_file:
            self._update_shapefile_checks()
            field_names = (
                shapefile_utils.get_shapefile_field_names(self._shp_path)
                if self._shp_path
                else []
            )
        else:
            self.crsWarningLabel.setVisible(False)
            self.crsWarningLabel.setText("")
            layer = self.layerCombo.currentLayer()
            field_names = [] if layer is None else [f.name() for f in layer.fields()]

        # Re-derive for whichever source is now active -- otherwise the
        # category-field dropdown would keep showing state left over from
        # the previously active source (e.g. a file's fields while "Loaded
        # layer" is now selected).
        self._update_category_field_options(field_names)

    def _on_layer_combo_changed(self, layer) -> None:
        """Update field-based UI whenever the selected loaded layer changes.

        QgsMapLayerComboBox tracks the project's layers regardless of its
        own visibility, so layerChanged can fire while "File on disk" is
        the active source -- guard on sourceLayerRadio so it doesn't
        clobber the file-derived field state in that case.
        """
        self._hide_validation_error()
        if not self.sourceLayerRadio.isChecked():
            return
        field_names = [] if layer is None else [f.name() for f in layer.fields()]
        self._update_category_field_options(field_names)

    def _update_category_field_options(self, field_names: List[str]) -> None:
        """Show/hide + populate the "Forecast category field" dropdown.

        Called whenever the active source's attribute fields might have
        changed (file browsed, layer combo changed, source toggled). When
        FCST_CAT_FIELD is present we behave exactly as before this feature
        existed -- no extra UI, nothing extra sent beyond the default. When
        it's absent, the user must explicitly pick a column, so the combo
        is always reset to the placeholder (index 0) rather than trying to
        carry a selection over from a different shapefile/layer.
        """
        self._current_field_names = field_names
        self._fcst_cat_present = FCST_CAT_FIELD in field_names

        if self._fcst_cat_present:
            self.categoryFieldLabel.setVisible(False)
            self.categoryFieldCombo.setVisible(False)
            self.categoryFieldCombo.clear()
            return

        self.categoryFieldLabel.setVisible(True)
        self.categoryFieldCombo.setVisible(True)
        self.categoryFieldCombo.clear()
        self.categoryFieldCombo.addItem(CATEGORY_FIELD_PLACEHOLDER)
        self.categoryFieldCombo.addItems(field_names)
        self.categoryFieldCombo.setCurrentIndex(0)

    def _refresh_layer_source_availability(self) -> None:
        """Disable the "Loaded layer" option when no polygon layers exist.

        QgsMapLayerComboBox keeps itself in sync with the project's
        layers, so checking its count() here (called on init and whenever
        the dialog is (re)shown) is enough -- no manual layer-added/
        -removed signal wiring needed.
        """
        has_polygon_layers = self.layerCombo.count() > 0
        self.sourceLayerRadio.setEnabled(has_polygon_layers)
        self.noPolygonLayersLabel.setVisible(not has_polygon_layers)
        if not has_polygon_layers and self.sourceLayerRadio.isChecked():
            self.sourceFileRadio.setChecked(True)

    def showEvent(self, event) -> None:  # noqa: N802 -- Qt override
        super().showEvent(event)
        self._refresh_layer_source_availability()

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
        self._update_category_field_options(shapefile_utils.get_shapefile_field_names(path))

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
        if self.sourceLayerRadio.isChecked():
            layer = self.layerCombo.currentLayer()
            if layer is None:
                return False, "Select a loaded polygon layer to upload."
        else:
            if not self._shp_path or not os.path.isfile(self._shp_path):
                return False, "Select a shapefile (.shp) to upload."

            is_complete, missing = shapefile_utils.validate_shapefile_complete(self._shp_path)
            if not is_complete:
                return False, (
                    "Shapefile is missing required companion file(s): " + ", ".join(missing)
                )

        # Forecast category column: shared across both source branches
        # above. If fcst_cat wasn't detected, the user must explicitly
        # pick a column via categoryFieldCombo -- see
        # _update_category_field_options().
        if not self._fcst_cat_present:
            if not self._current_field_names:
                return False, (
                    "Could not read attribute fields from the selected shapefile/layer."
                )
            if self.categoryFieldCombo.currentIndex() <= 0:
                return False, "Select which attribute column holds the forecast category code."

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

    # -- Loaded-layer export --------------------------------------------

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Turn a layer name into a safe base filename for the export."""
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")
        return safe or "export"

    def _export_layer_to_temp_shapefile(self, layer) -> Optional[str]:
        """Export ``layer`` to a temp ESRI Shapefile reprojected to EPSG:4326.

        Uses ``writeAsVectorFormatV2`` (not V3, which needs a newer QGIS
        than this plugin's declared qgisMinimumVersion=3.16 floor -- V2
        has been available since QGIS 3.10). Setting SaveVectorOptions'
        destCRS to a CRS different from the layer's own is what triggers
        on-the-fly reprojection during the write.

        Returns the path to the exported .shp on success. On failure, an
        inline validation error is shown (via the dialog's existing
        mechanism) and any temp dir already created is removed; returns
        None in that case.
        """
        temp_dir = tempfile.mkdtemp(prefix="acmad_forecast_ingest_export_")
        shp_path = os.path.join(temp_dir, f"{self._sanitize_filename(layer.name())}.shp")

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "ESRI Shapefile"
        options.destCRS = QgsCoordinateReferenceSystem("EPSG:4326")

        result = QgsVectorFileWriter.writeAsVectorFormatV2(
            layer, shp_path, QgsProject.instance().transformContext(), options
        )
        # writeAsVectorFormatV2 returns a (WriterError, error_message) tuple
        # (some QGIS point releases append extra elements) -- unpack
        # defensively rather than assuming an exact tuple length.
        error_code = result[0] if isinstance(result, tuple) else result
        error_message = result[1] if isinstance(result, tuple) and len(result) > 1 else ""

        if error_code != QgsVectorFileWriter.NoError:
            shutil.rmtree(temp_dir, ignore_errors=True)
            self._show_validation_error(
                f"Failed to export layer '{layer.name()}' to shapefile: "
                + (error_message or "unknown error")
            )
            return None

        self._layer_export_dir = temp_dir
        return shp_path

    def _cleanup_layer_export_dir(self) -> None:
        """Remove the temp dir created by _export_layer_to_temp_shapefile."""
        if self._layer_export_dir:
            shutil.rmtree(self._layer_export_dir, ignore_errors=True)
            self._layer_export_dir = None

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

        if self.sourceLayerRadio.isChecked():
            shp_path = self._export_layer_to_temp_shapefile(self.layerCombo.currentLayer())
            if shp_path is None:
                # _export_layer_to_temp_shapefile already showed the error
                # and cleaned up its own temp dir -- don't proceed to zip/
                # POST a partial or failed export.
                return
        else:
            shp_path = self._shp_path

        fields = {
            "forecast_period": self.forecastPeriodCombo.currentText(),
            "forecast_lead_name": self.forecastLeadNameEdit.text().strip(),
            "date_produced": self.dateProducedEdit.date().toString("yyyy-MM-dd"),
            "year": str(self.yearSpinBox.value()),
            "cleanup": "true" if self.cleanupCheckBox.isChecked() else "false",
            "update_latest": "true" if self.updateLatestCheckBox.isChecked() else "false",
            "forecast_category_code_column": (
                FCST_CAT_FIELD if self._fcst_cat_present else self.categoryFieldCombo.currentText()
            ),
        }

        self._set_busy(True)

        base_url = self._settings.get_base_url()
        token = self._settings.get_token()

        # Parented to self so the client (and its in-flight QNetworkReply)
        # is not garbage collected while the async request is running.
        self._network_client = NetworkClient(base_url, token, parent=self)
        self._network_client.uploadProgress.connect(self._on_upload_progress)
        self._network_client.uploadFinished.connect(self._on_upload_finished)
        self._network_client.upload_forecast(shp_path, fields)

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

        # Whether the "Loaded layer" export succeeded, failed server-side,
        # or was aborted, its temp export dir (distinct from NetworkClient's
        # own zip temp dir, which it cleans up itself) is no longer needed.
        self._cleanup_layer_export_dir()

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
            self.sourceFileRadio,
            self.sourceLayerRadio,
            self.layerCombo,
            self.categoryFieldCombo,
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

        self.categoryFieldLabel.setVisible(False)
        self.categoryFieldCombo.setVisible(False)
        self.categoryFieldCombo.clear()
        self._current_field_names = []
        self._fcst_cat_present = True
