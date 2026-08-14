# -*- coding: utf-8 -*-
"""Forecast Ingest tool: QAction wiring + dialog-opening logic.

Implements the small duck-typed tool interface documented in the
repository README ("Adding a new tool"). This is the same action-creation
and dialog-opening logic that used to live directly in the old single-
feature plugin class's ``initGui``/``run`` -- moved here unchanged so a
future tool can follow the same pattern in its own ``tool.py``.
"""

from qgis.core import QgsApplication
from qgis.PyQt.QtWidgets import QAction


class ForecastIngestTool:
    """Upload a drought forecast shapefile to the ACMAD backend."""

    name = "Forecast Ingest"

    def __init__(self, iface) -> None:
        self.iface = iface
        self._action = None
        self._menu = None
        self._dialog = None

    def icon(self):
        """Return the QIcon used for this tool's QAction.

        No bundled icon.png ships with this initial version of the
        plugin (no image-generation tooling was available while building
        it), so we fall back to a built-in QGIS theme icon -- this keeps
        the toolbar/menu entry visually sensible without a custom asset.
        "mActionSharingExport.svg" reads reasonably as "send data out";
        swap for a bundled icon.png + QIcon(icon_path) once a proper
        plugin icon is designed.
        """
        return QgsApplication.getThemeIcon("/mActionSharingExport.svg")

    def initGui(self, menu, toolbar) -> None:
        """Create this tool's QAction and add it to the shared menu/toolbar.

        Args:
            menu: The Plugins-menu name (str) to pass to
                ``iface.addPluginToMenu``/``removePluginMenu`` -- the same
                mechanism, and the same shared menu, used by every tool in
                the toolbox.
            toolbar: The shared QToolBar (created once by
                ``AcmadToolsPlugin``) that every tool's action is added to.
        """
        self._menu = menu

        action = QAction(self.icon(), "Upload Forecast to ACMAD...", self.iface.mainWindow())
        action.setObjectName("acmadForecastIngestUploadAction")
        action.setWhatsThis("Upload a drought forecast shapefile to the ACMAD backend")
        action.setStatusTip("Upload a drought forecast shapefile to the ACMAD backend")
        action.triggered.connect(self.run)

        toolbar.addAction(action)
        self.iface.addPluginToMenu(menu, action)
        self._action = action

    def unload(self) -> None:
        """Remove this tool's action from the shared menu/toolbar."""
        if self._action is not None:
            self.iface.removePluginMenu(self._menu, self._action)
            self.iface.removeToolBarIcon(self._action)
            self._action = None

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
