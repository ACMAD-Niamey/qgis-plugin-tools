# -*- coding: utf-8 -*-
"""Persisted plugin settings (server base URL + API token) via QSettings.

Kept as its own module (rather than scattering ``QSettings`` calls through
the dialogs) so there is exactly one place that knows the settings
organisation/application name and key layout -- separation of concerns
between "where settings live" and "how the UI collects them".
"""

from typing import Optional

from qgis.PyQt.QtCore import QSettings

# QSettings organisation/application identify the on-disk/registry location
# (e.g. ~/.config/ACMAD/ForecastIngestPlugin.conf on Linux). The "group"
# prefix namespaces our keys within that file so the plugin plays nicely
# if other ACMAD tools ever share the same QSettings application.
_ORGANIZATION = "ACMAD"
_APPLICATION = "ForecastIngestPlugin"
_GROUP = "ForecastIngest"

_KEY_BASE_URL = f"{_GROUP}/base_url"
_KEY_API_TOKEN = f"{_GROUP}/api_token"


class SettingsManager:
    """Thin, typed wrapper around QSettings for this plugin's settings."""

    def __init__(self) -> None:
        self._settings = QSettings(_ORGANIZATION, _APPLICATION)

    def get_base_url(self) -> str:
        """Return the configured server base URL, e.g. https://host.example.org.

        Trailing slashes are stripped at write time (see ``set_base_url``)
        so callers can safely do ``base_url + "/api/..."``.
        """
        return str(self._settings.value(_KEY_BASE_URL, "", type=str) or "")

    def set_base_url(self, value: str) -> None:
        """Persist the server base URL, normalised (trailing slash removed)."""
        self._settings.setValue(_KEY_BASE_URL, (value or "").strip().rstrip("/"))

    def get_token(self) -> str:
        """Return the configured DRF API token (empty string if unset)."""
        return str(self._settings.value(_KEY_API_TOKEN, "", type=str) or "")

    def set_token(self, value: str) -> None:
        """Persist the DRF API token."""
        self._settings.setValue(_KEY_API_TOKEN, (value or "").strip())

    def is_configured(self) -> bool:
        """True if both a base URL and a token have been set."""
        return bool(self.get_base_url()) and bool(self.get_token())

    def forecast_upload_url(self) -> Optional[str]:
        """Return the full forecast upload endpoint URL, or None if unset."""
        base_url = self.get_base_url()
        if not base_url:
            return None
        return f"{base_url}/api/data_api/data_upload/forecast/"
