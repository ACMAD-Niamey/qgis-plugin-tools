# -*- coding: utf-8 -*-
"""Settings dialog: server base URL + API token, with a "Test Connection" check."""

import os

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog

from ...core.settings_manager import SettingsManager
from .network_client import NetworkClient

UI_PATH = os.path.join(os.path.dirname(__file__), "settings_dialog_base.ui")
FORM_CLASS, _ = uic.loadUiType(UI_PATH)


class SettingsDialog(QDialog, FORM_CLASS):
    """Modal dialog for configuring and testing the backend connection."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setupUi(self)

        self._settings = SettingsManager()
        # Kept alive across the async "Test Connection" round trip -- if
        # this were a local variable it could be garbage collected before
        # the reply's `finished` signal fires.
        self._test_client = None

        self.baseUrlEdit.setText(self._settings.get_base_url())
        self.tokenEdit.setText(self._settings.get_token())

        self.testConnectionButton.clicked.connect(self._on_test_connection_clicked)
        self.buttonBox.accepted.connect(self._on_save)

    def _on_save(self) -> None:
        """Persist settings when the dialog is accepted (Save button)."""
        self._settings.set_base_url(self.baseUrlEdit.text())
        self._settings.set_token(self.tokenEdit.text())

    def _on_test_connection_clicked(self) -> None:
        base_url = self.baseUrlEdit.text().strip()
        token = self.tokenEdit.text().strip()

        if not base_url or not token:
            self._show_result(False, "Enter both a server base URL and an API token first.")
            return

        self.testConnectionButton.setEnabled(False)
        self._show_result(None, "Testing connection...")

        self._test_client = NetworkClient(base_url, token, parent=self)
        self._test_client.testConnectionFinished.connect(self._on_test_connection_finished)
        self._test_client.test_connection()

    def _on_test_connection_finished(self, success: bool, message: str) -> None:
        self.testConnectionButton.setEnabled(True)
        self._show_result(success, message)
        self._test_client = None

    def _show_result(self, success, message: str) -> None:
        """Update the inline result label. ``success`` may be True/False/None."""
        self.testConnectionResultLabel.setVisible(True)
        self.testConnectionResultLabel.setText(message)
        if success is True:
            colour = "#1e7e34"  # green
        elif success is False:
            colour = "#c0392b"  # red
        else:
            colour = "#666666"  # neutral, "in progress"
        self.testConnectionResultLabel.setStyleSheet(f"color: {colour};")
