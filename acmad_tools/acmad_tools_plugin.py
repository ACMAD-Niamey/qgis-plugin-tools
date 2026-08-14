# -*- coding: utf-8 -*-
"""ACMAD Tools plugin: shared toolbar/menu wiring (initGui / unload).

This module's only job is to give QGIS a single "ACMAD Tools" toolbar and
Plugins-menu entry point, and to drive the small registry of individual
tools (see ``tools/``) that each add their own action(s) into that shared
toolbar/menu. All tool-specific logic (dialogs, network calls, ...) lives
inside each tool's own subpackage -- this module deliberately knows
nothing about what any given tool does.
"""

from .tools.forecast_ingest.tool import ForecastIngestTool

# Passed straight through to iface.addPluginToMenu()/removePluginMenu(), same
# mechanism the original single-feature plugin used -- just renamed to the
# toolbox's name so every tool's action lands under one Plugins menu entry.
PLUGIN_MENU_NAME = "&ACMAD Tools"


class AcmadToolsPlugin:
    """QGIS plugin entry point (the object ``classFactory()`` returns).

    Holds the registry of available tools as a plain list. Adding a future
    tool means importing its ``tool.py`` class and appending one line to
    ``self._tools`` below -- no other changes to this file are needed.
    """

    def __init__(self, iface) -> None:
        self.iface = iface
        self._toolbar = None

        # The tool registry. Each entry implements the small duck-typed
        # interface documented in the README ("Adding a new tool"):
        # __init__(iface), name, icon(), initGui(menu, toolbar), unload().
        self._tools = [
            ForecastIngestTool(iface),
        ]

    def initGui(self) -> None:  # noqa: N802 -- QGIS-mandated method name
        """Create the shared toolbar, then let each tool wire itself in."""
        self._toolbar = self.iface.addToolBar("ACMAD Tools")
        self._toolbar.setObjectName("ACMADToolsToolbar")

        for tool in self._tools:
            tool.initGui(PLUGIN_MENU_NAME, self._toolbar)

    def unload(self) -> None:
        """Remove all traces of the plugin from the QGIS UI. Called on unload/uninstall."""
        for tool in self._tools:
            tool.unload()

        if self._toolbar is not None:
            del self._toolbar
            self._toolbar = None
