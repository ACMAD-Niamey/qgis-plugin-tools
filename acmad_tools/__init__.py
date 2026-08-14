# -*- coding: utf-8 -*-
"""ACMAD Tools -- QGIS plugin entry point.

This file must stay minimal: QGIS imports it purely to call
``classFactory()`` before the plugin's dependencies (PyQt, qgis.core, ...)
are necessarily ready, so the heavier plugin class is imported lazily
inside the factory function rather than at module scope.
"""


def classFactory(iface):  # noqa: N802 -- QGIS requires this exact name/case
    """Instantiate the plugin.

    Called by QGIS when the plugin is loaded.

    Args:
        iface: A ``QgisInterface`` instance, provided by QGIS at load time.

    Returns:
        AcmadToolsPlugin: The plugin instance QGIS will drive via
        ``initGui()`` / ``unload()``.
    """
    from .acmad_tools_plugin import AcmadToolsPlugin

    return AcmadToolsPlugin(iface)
