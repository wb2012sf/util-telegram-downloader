"""
gui/app.py

Entry point for the Telegram downloader GUI: wires the credentials screen
and the chat selection screen together behind a QStackedWidget, and
launches the Qt event loop.
"""

from __future__ import annotations

import sys
import traceback
from types import TracebackType

from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QStackedWidget

import credentials
from credentials import Credentials
from gui.chat_selection_view import ChatSelectionView
from gui.credentials_view import CredentialsView

DEFAULT_SESSION = "telegram_export"  # shared with telegram_export.py's CLI default


def _install_exception_hook() -> None:
    """Show uncaught exceptions in a dialog instead of only printing to stderr.

    PySide6 routes a Python exception raised inside a Qt slot to
    sys.excepthook rather than letting it crash the app -- the default hook
    just prints to stderr, which is invisible if the app wasn't launched
    from a terminal, making the failure look like nothing happened at all.
    """

    def _hook(exc_type: type[BaseException], exc_value: BaseException, exc_tb: TracebackType | None) -> None:
        message = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        print(message, file=sys.stderr)
        QMessageBox.critical(None, "Unexpected error", message[-4000:])

    sys.excepthook = _hook


class MainWindow(QMainWindow):
    def __init__(self, session: str = DEFAULT_SESSION) -> None:
        super().__init__()
        self.setWindowTitle("Telegram Downloader")
        self.resize(900, 600)

        self._credentials_view = CredentialsView(session=session)
        self._chat_selection_view = ChatSelectionView(session=session)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._credentials_view)
        self._stack.addWidget(self._chat_selection_view)
        self.setCentralWidget(self._stack)

        self._credentials_view.credentials_ready.connect(self._on_credentials_ready)
        self._chat_selection_view.logged_out.connect(self._on_logged_out)

        existing = credentials.load_credentials()
        if existing is not None:
            self._on_credentials_ready(existing)

    def _on_credentials_ready(self, creds: Credentials) -> None:
        assert isinstance(creds, Credentials), "creds must be a Credentials instance"
        self._stack.setCurrentWidget(self._chat_selection_view)
        self._chat_selection_view.start(creds)

    def _on_logged_out(self) -> None:
        self._credentials_view.clear()
        self._stack.setCurrentWidget(self._credentials_view)


def main() -> None:
    _install_exception_hook()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
