# -*- coding: utf-8 -*-
"""ACMAD Forecast Ingest plugin: toolbar/menu wiring (initGui / unload).

All actual upload logic lives in ``upload_dialog.py`` / ``network_client.py``
-- this module's only job is to give QGIS a toolbar icon and menu entry that
open that dialog, and to clean up after itself on unload.
"""

from qgis.core import QgsApplication
from qgis.PyQt.QtWidgets import QAction

PLUGIN_MENU_NAME = "&ACMAD Forecast Ingest"


class AcmadForecastIngestPlugin:
    """QGIS plugin entry point (the object ``classFactory()`` returns)."""

    def __init__(self, iface) -> None:
        self.iface = iface
        self._actions = []
        self._toolbar = None
        self._dialog = None

    def initGui(self) -> None:  # noqa: N802 -- QGIS-mandated method name
        """Create the toolbar icon and menu entry. Called once by QGIS at load time."""
        self._toolbar = self.iface.addToolBar("ACMAD Forecast Ingest")
        self._toolbar.setObjectName("ACMADForecastIngestToolbar")

        # No bundled icon.png ships with this initial version of the
        # plugin (no image-generation tooling was available while
        # building it), so we fall back to a built-in QGIS theme icon --
        # this keeps the toolbar/menu entry visually sensible without a
        # custom asset. "mActionSharingExport.svg" reads reasonably as
        # "send data out"; swap for a bundled icon.png + QIcon(icon_path)
        # once a proper plugin icon is designed.
        icon = QgsApplication.getThemeIcon("/mActionSharingExport.svg")

        action = QAction(icon, "Upload Forecast to ACMAD...", self.iface.mainWindow())
        action.setObjectName("acmadForecastIngestUploadAction")
        action.setWhatsThis("Upload a drought forecast shapefile to the ACMAD backend")
        action.setStatusTip("Upload a drought forecast shapefile to the ACMAD backend")
        action.triggered.connect(self.run)

        self._toolbar.addAction(action)
        self.iface.addPluginToMenu(PLUGIN_MENU_NAME, action)
        self._actions.append(action)

    def unload(self) -> None:
        """Remove all traces of the plugin from the QGIS UI. Called on unload/uninstall."""
        for action in self._actions:
            self.iface.removePluginMenu(PLUGIN_MENU_NAME, action)
            self.iface.removeToolBarIcon(action)
        self._actions = []

        if self._toolbar is not None:
            del self._toolbar
            self._toolbar = None

        if self._dialog is not None:
            self._dialog.close()
            self._dialog = None

    def run(self) -> None:
        """Open (or raise) the forecast upload dialog."""
        # Imported lazily so that initGui() (called at QGIS startup for
        # every installed plugin) stays cheap and doesn't need PyQt
        # network/widget classes loaded until the user actually opens the
        # dialog.
        from .upload_dialog import ForecastUploadDialog

        if self._dialog is None:
            self._dialog = ForecastUploadDialog(self.iface, self.iface.mainWindow())

        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()
