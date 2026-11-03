"""
gui/credentials_view.py

Credentials screen: enter/edit api_id, api_hash and phone number, with
inline validation, a one-click link to my.telegram.org, and a "Login"
button that logs in for real (prompting for the login code and, if needed,
a 2FA password) before saving anything -- credentials are only persisted
and only hand off to the next screen once that real login actually
succeeds, so a typo can never leave the app pointed at chat selection with
nothing behind it.

All Telegram-facing logic lives in credentials.py; this module only wires
those pure functions to widgets.
"""

from __future__ import annotations

import asyncio
import webbrowser

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import credentials
from credentials import Credentials, CredentialsError


class CredentialsView(QWidget):
    """Form for entering, saving, and test-connecting Telegram API credentials."""

    credentials_ready = Signal(object)  # emits a Credentials instance

    def __init__(self, session: str, parent: QWidget | None = None) -> None:
        assert isinstance(session, str) and session, "session must be a non-empty string"
        super().__init__(parent)
        self._session = session

        self._api_id_edit = QLineEdit()
        self._api_id_edit.setPlaceholderText("e.g. 12345678")

        self._api_hash_edit = QLineEdit()
        self._api_hash_edit.setPlaceholderText("32-character hex string")
        self._api_hash_edit.setEchoMode(QLineEdit.EchoMode.Password)

        self._show_hash_checkbox = QCheckBox("Show")
        self._show_hash_checkbox.toggled.connect(self._on_show_hash_toggled)

        self._phone_edit = QLineEdit()
        self._phone_edit.setPlaceholderText("+15551234567")

        self._error_label = QLabel("")
        self._error_label.setStyleSheet("color: #c0392b;")
        self._error_label.setWordWrap(True)
        self._error_label.hide()

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.hide()

        help_html = credentials.CREDENTIALS_HELP_TEXT.replace("\n", "<br>")
        help_html = help_html.replace("https://my.telegram.org", '<a href="https://my.telegram.org">https://my.telegram.org</a>')
        help_label = QLabel(help_html)
        help_label.setWordWrap(True)
        help_label.setTextFormat(Qt.TextFormat.RichText)
        help_label.setOpenExternalLinks(True)

        open_browser_button = QPushButton("Open my.telegram.org")
        open_browser_button.clicked.connect(self._on_open_browser_clicked)

        self._login_button = QPushButton("Login")
        self._login_button.clicked.connect(self._on_login_clicked)

        hash_row = QHBoxLayout()
        hash_row.addWidget(self._api_hash_edit)
        hash_row.addWidget(self._show_hash_checkbox)

        form = QFormLayout()
        form.addRow("api_id", self._api_id_edit)
        form.addRow("api_hash", hash_row)
        form.addRow("Phone number", self._phone_edit)

        button_row = QHBoxLayout()
        button_row.addWidget(self._login_button)
        button_row.addWidget(open_browser_button)

        layout = QVBoxLayout()
        layout.addWidget(help_label)
        layout.addLayout(form)
        layout.addLayout(button_row)
        layout.addWidget(self._error_label)
        layout.addWidget(self._status_label)
        layout.addStretch(1)
        self.setLayout(layout)

        self._load_existing_credentials()

    def _load_existing_credentials(self) -> None:
        existing = credentials.load_credentials()
        if existing is None:
            return
        self._api_id_edit.setText(str(existing.api_id))
        self._api_hash_edit.setText(existing.api_hash)
        self._phone_edit.setText(existing.phone)

    def clear(self) -> None:
        """Reset the form to blank, e.g. after logging out."""
        self._api_id_edit.clear()
        self._api_hash_edit.clear()
        self._phone_edit.clear()
        self._error_label.hide()
        self._status_label.hide()

    def _on_show_hash_toggled(self, checked: bool) -> None:
        self._api_hash_edit.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password)

    def _on_open_browser_clicked(self) -> None:
        webbrowser.open(credentials.MY_TELEGRAM_ORG_APPS_URL)

    def _read_and_validate(self) -> Credentials | None:
        self._error_label.hide()
        try:
            return credentials.validate_credentials(
                self._api_id_edit.text(),
                self._api_hash_edit.text(),
                self._phone_edit.text(),
            )
        except CredentialsError as exc:
            self._error_label.setText(str(exc))
            self._error_label.show()
            return None

    def _on_login_clicked(self) -> None:
        creds = self._read_and_validate()
        if creds is None:
            return

        self._status_label.setText("Connecting...")
        self._status_label.show()
        self._login_button.setEnabled(False)
        self.repaint()

        client = credentials.create_client(creds, self._session)
        try:
            message = asyncio.run(
                credentials.test_connection(
                    client,
                    creds.phone,
                    request_code=lambda: self._prompt("Login code", "Enter the login code Telegram sent you:"),
                    request_password=lambda: self._prompt(
                        "2FA password", "Enter your Telegram two-factor password:", is_password=True
                    ),
                )
            )
        except Exception as exc:  # noqa: BLE001 -- shown to the user, not swallowed silently
            self._status_label.setText(f"Login failed: {exc}")
            return
        finally:
            self._login_button.setEnabled(True)

        # Only save and hand off once a real login actually succeeded --
        # otherwise a typo'd credential would move on to chat selection
        # with nothing behind it and no way to tell something was wrong.
        credentials.save_credentials(creds)
        self._status_label.setText(message)
        self.credentials_ready.emit(creds)

    def _prompt(self, title: str, label: str, *, is_password: bool = False) -> str:
        echo_mode = QLineEdit.EchoMode.Password if is_password else QLineEdit.EchoMode.Normal
        text, ok = QInputDialog.getText(self, title, label, echo_mode)
        if not ok:
            raise CredentialsError(f"{title} entry was cancelled")
        return text
