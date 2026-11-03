"""
gui/chat_selection_view.py

Chat selection screen: lists the user's Telegram dialogs in a searchable,
multi-select table and downloads the selected chats via the existing
telegram_export.export_chat().

Participant names are not fetched for every chat up front (slow and
rate-limited). Each row has a "Load members" link the user clicks to fetch
and cache that one chat's participant names for the session -- after that,
the search box also matches against them. This is a deliberate, narrower
reading of "fetch lazily... on expanded or searched": fetching on every
keystroke for every chat that doesn't already match by name/ID would mean
firing participant requests for most of the list on most keystrokes, which
is exactly the eager-pull behaviour the spec asks to avoid.

The "Load members" link is a plain QTableWidgetItem styled to look
clickable (rather than an embedded QPushButton via setCellWidget)
specifically because the table is sortable: QTableWidget's built-in sort
reorders QTableWidgetItems as part of a row, but cell widgets set via
setCellWidget are not moved along with the row they were set on, so a
widget-per-cell approach silently mismatches after the first sort.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import credentials
import telegram_export
from chat_filter import ChatSummary, chat_summary_from_dialog, filter_chats
from credentials import Credentials
from gui.async_bridge import AsyncBridge

COL_SELECT, COL_NAME, COL_ID, COL_TYPE, COL_PARTICIPANTS, COL_MEMBERS, COL_STATUS = range(7)
COLUMN_HEADERS = ["", "Name", "ID", "Type", "Participants", "Members", "Status"]

_LOAD_MEMBERS_COLOR = QColor("#2563eb")
_LOADED_MEMBERS_COLOR = QColor("#16a34a")


class ChatSelectionView(QWidget):
    """Searchable, multi-select table of Telegram dialogs, with a download action."""

    # object, not int: Qt's int is 32-bit and channel ids like -1001234567890 overflow it
    _download_progress = Signal(object, str)
    logged_out = Signal()

    def __init__(self, session: str, parent: QWidget | None = None) -> None:
        assert isinstance(session, str) and session, "session must be a non-empty string"
        super().__init__(parent)
        self._session = session
        self._bridge = AsyncBridge(self)

        self._creds: Credentials | None = None
        self._client: Any = None
        self._all_chats: list[ChatSummary] = []
        self._filtered_chats: list[ChatSummary] = []
        self._participants_cache: dict[int, tuple[str, ...]] = {}
        self._selected_ids: set[int] = set()
        self._status_by_id: dict[int, str] = {}

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search by name, chat ID, or a loaded member's name")
        self._search_edit.textChanged.connect(self._on_search_changed)

        self._hide_empty_names_checkbox = QCheckBox("Hide chats with no name")
        self._hide_empty_names_checkbox.toggled.connect(self._on_search_changed)

        self._status_label = QLabel("Not connected yet.")
        self._status_label.setWordWrap(True)

        self._logout_button = QPushButton("Log out")
        self._logout_button.setEnabled(False)
        self._logout_button.clicked.connect(self._on_logout_clicked)

        self._table = QTableWidget(0, len(COLUMN_HEADERS))
        self._table.setHorizontalHeaderLabels(COLUMN_HEADERS)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.cellClicked.connect(self._on_cell_clicked)
        self._table.setSortingEnabled(True)

        # A plain checkbox floated on top of the Select column's (blank)
        # header, so it reads as "select all" for the checkbox column right
        # below it rather than a separate, disconnected control elsewhere.
        # QHeaderView has no native slot for an embedded widget, so this is
        # a child widget positioned by hand and kept in place on resize.
        self._select_all_checkbox = QCheckBox(self._table.horizontalHeader())
        self._select_all_checkbox.setToolTip("Select all / none of the visible chats")
        self._select_all_checkbox.toggled.connect(self._on_select_all_toggled)
        self._table.horizontalHeader().sectionResized.connect(self._reposition_select_all_checkbox)

        # Every column stays user-resizable (Interactive is the default
        # resize mode); resizeColumnsToContents() below just picks sensible
        # starting widths once, it doesn't lock them.
        self._table.setStyleSheet("QTableWidget::item { padding: 4px 10px; }")

        self._out_dir_edit = QLineEdit("export")
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._on_browse_clicked)

        self._html_checkbox = QCheckBox("Also write HTML")

        self._limit_spin = QSpinBox()
        self._limit_spin.setRange(0, 10_000_000)
        self._limit_spin.setSpecialValueText("All messages")
        self._limit_spin.setValue(0)

        self._download_button = QPushButton("Download selected")
        self._download_button.setEnabled(False)
        self._download_button.clicked.connect(self._on_download_clicked)

        self._download_progress.connect(self._on_download_progress)

        out_dir_row = QHBoxLayout()
        out_dir_row.addWidget(QLabel("Output directory:"))
        out_dir_row.addWidget(self._out_dir_edit)
        out_dir_row.addWidget(browse_button)

        options_row = QHBoxLayout()
        options_row.addWidget(self._html_checkbox)
        options_row.addWidget(QLabel("Message limit:"))
        options_row.addWidget(self._limit_spin)
        options_row.addStretch(1)
        options_row.addWidget(self._download_button)

        status_row = QHBoxLayout()
        status_row.addWidget(self._status_label, stretch=1)
        status_row.addWidget(self._logout_button)

        search_row = QHBoxLayout()
        search_row.addWidget(self._search_edit, stretch=1)
        search_row.addWidget(self._hide_empty_names_checkbox)

        layout = QVBoxLayout()
        layout.addLayout(status_row)
        layout.addLayout(search_row)
        layout.addWidget(self._table)
        layout.addLayout(out_dir_row)
        layout.addLayout(options_row)
        self.setLayout(layout)

        self._reposition_select_all_checkbox()

    def _reposition_select_all_checkbox(self, *_args: object) -> None:
        header = self._table.horizontalHeader()
        x = header.sectionViewportPosition(COL_SELECT)
        width = header.sectionSize(COL_SELECT)
        margin = 4
        self._select_all_checkbox.setGeometry(
            x + margin, margin, max(width - 2 * margin, 12), header.height() - 2 * margin
        )

    def start(self, creds: Credentials) -> None:
        """Connect using `creds` and load the dialog list. Safe to call again to refresh."""
        assert isinstance(creds, Credentials), "creds must be a Credentials instance"
        self._creds = creds
        self._status_label.setText("Connecting and loading chats...")
        self._download_button.setEnabled(False)
        # Enabled here, not only on a successful fetch: if the saved
        # credentials are wrong, the fetch below fails and this screen
        # would otherwise be a dead end -- no chats, and no way back to
        # the credentials form to fix them, even across a restart (they'd
        # just be reloaded from storage and fail again).
        self._logout_button.setEnabled(True)
        self._bridge.submit(self._connect_and_fetch(creds), self._on_fetch_done, self._on_fetch_error)

    async def _connect_and_fetch(self, creds: Credentials) -> list[ChatSummary]:
        self._client = credentials.create_client(creds, self._session)
        await self._client.connect()
        if not await self._client.is_user_authorized():
            raise RuntimeError("Not authorized yet -- use Test connection on the credentials screen first.")

        chats = []
        async for dialog in self._client.iter_dialogs():
            chats.append(chat_summary_from_dialog(dialog))
        return chats

    def _on_fetch_done(self, chats: list[ChatSummary]) -> None:
        self._all_chats = chats
        self._status_label.setText(f"Loaded {len(chats)} chats.")
        self._download_button.setEnabled(True)
        self._apply_filter()
        self._table.resizeColumnsToContents()

    def _on_fetch_error(self, exc: BaseException) -> None:
        self._status_label.setText(f"Failed to load chats: {exc}")

    def _on_search_changed(self, _value: object) -> None:
        # Shared by the search box's textChanged (str) and the hide-empty-
        # names checkbox's toggled (bool) signals; both just re-filter.
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self._search_edit.text()
        self._filtered_chats = filter_chats(
            self._all_chats,
            query,
            self._participants_cache,
            exclude_empty_names=self._hide_empty_names_checkbox.isChecked(),
        )
        self._refresh_table()

    def _refresh_table(self) -> None:
        # setRowCount() below resets the scrollbar to the top, which is
        # jarring when a refresh was triggered by something like clicking
        # "Load members" on a row well down the list -- restore the
        # scroll position afterward instead of just losing it.
        scroll_bar = self._table.verticalScrollBar()
        scroll_position = scroll_bar.value()

        # Sorting must be off while populating: QTableWidget re-sorts on
        # every individual setItem() call when it's on, which scrambles a
        # row's cells across the wrong rows mid-population.
        was_sorting = self._table.isSortingEnabled()
        self._table.setSortingEnabled(False)
        self._table.blockSignals(True)
        try:
            self._table.setRowCount(len(self._filtered_chats))
            for row, chat in enumerate(self._filtered_chats):
                self._populate_row(row, chat)
        finally:
            self._table.blockSignals(False)
            self._table.setSortingEnabled(was_sorting)

        # A real windowed backend recalculates the scrollbar's range on the
        # next event-loop iteration, not synchronously here -- setting the
        # value immediately can be clamped against the *old* (pre-refresh)
        # range and then get silently overwritten once Qt catches up.
        # Deferring by one tick applies it after that recalculation.
        QTimer.singleShot(0, lambda: scroll_bar.setValue(min(scroll_position, scroll_bar.maximum())))

    def _populate_row(self, row: int, chat: ChatSummary) -> None:
        select_item = QTableWidgetItem()
        select_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        select_item.setCheckState(Qt.CheckState.Checked if chat.id in self._selected_ids else Qt.CheckState.Unchecked)
        select_item.setData(Qt.ItemDataRole.UserRole, chat.id)
        self._table.setItem(row, COL_SELECT, select_item)

        self._table.setItem(row, COL_NAME, QTableWidgetItem(chat.name))

        id_item = QTableWidgetItem()
        id_item.setData(Qt.ItemDataRole.DisplayRole, chat.id)  # numeric, so the column sorts numerically
        self._table.setItem(row, COL_ID, id_item)

        self._table.setItem(row, COL_TYPE, QTableWidgetItem(chat.type))

        participants_item = QTableWidgetItem()
        if chat.participant_count is not None:
            participants_item.setData(Qt.ItemDataRole.DisplayRole, chat.participant_count)
        self._table.setItem(row, COL_PARTICIPANTS, participants_item)

        members_item = QTableWidgetItem()
        members_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        if chat.id in self._participants_cache:
            members_item.setText(f"Loaded ({len(self._participants_cache[chat.id])})")
            members_item.setForeground(_LOADED_MEMBERS_COLOR)
        else:
            members_item.setText("Load members")
            members_item.setForeground(_LOAD_MEMBERS_COLOR)
            font = members_item.font()
            font.setUnderline(True)
            members_item.setFont(font)
        members_item.setData(Qt.ItemDataRole.UserRole, chat.id)
        self._table.setItem(row, COL_MEMBERS, members_item)

        self._table.setItem(row, COL_STATUS, QTableWidgetItem(self._status_by_id.get(chat.id, "")))

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != COL_SELECT:
            return
        chat_id = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() == Qt.CheckState.Checked:
            self._selected_ids.add(chat_id)
        else:
            self._selected_ids.discard(chat_id)

    def _on_cell_clicked(self, row: int, column: int) -> None:
        if column != COL_MEMBERS:
            return
        chat_id = self._table.item(row, COL_MEMBERS).data(Qt.ItemDataRole.UserRole)
        if chat_id in self._participants_cache:
            return  # already loaded, nothing to do
        self._load_members(chat_id)

    def _on_select_all_toggled(self, checked: bool) -> None:
        for chat in self._filtered_chats:
            if checked:
                self._selected_ids.add(chat.id)
            else:
                self._selected_ids.discard(chat.id)
        self._refresh_table()

    def _load_members(self, chat_id: int) -> None:
        assert self._client is not None, "not connected yet"
        self._bridge.submit(
            self._fetch_participants(chat_id),
            lambda names: self._on_members_loaded(chat_id, names),
            lambda exc: self._on_members_failed(chat_id, exc),
        )

    async def _fetch_participants(self, chat_id: int) -> tuple[str, ...]:
        entity = await self._client.get_entity(chat_id)
        names_by_id = await telegram_export.build_sender_names(self._client, entity)
        return tuple(names_by_id.values())

    def _on_members_loaded(self, chat_id: int, names: tuple[str, ...]) -> None:
        self._participants_cache[chat_id] = names
        self._apply_filter()

    def _on_members_failed(self, chat_id: int, exc: BaseException) -> None:
        self._status_label.setText(f"Failed to load members for chat {chat_id}: {exc}")

    def _on_browse_clicked(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose output directory", self._out_dir_edit.text())
        if chosen:
            self._out_dir_edit.setText(chosen)

    def _on_download_clicked(self) -> None:
        selected = [chat for chat in self._all_chats if chat.id in self._selected_ids]
        if not selected:
            QMessageBox.information(self, "Nothing selected", "Select at least one chat to download.")
            return
        assert self._creds is not None, "not connected yet"

        limit = self._limit_spin.value() or None
        if len(selected) > 1:
            limit_text = "all messages" if limit is None else f"up to {limit} messages"
            reply = QMessageBox.question(
                self,
                "Confirm download",
                f"Download {len(selected)} chats ({limit_text} per chat)?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._download_button.setEnabled(False)
        self._search_edit.setEnabled(False)
        self._bridge.submit(
            self._run_downloads(selected, self._out_dir_edit.text(), self._html_checkbox.isChecked(), limit),
            self._on_downloads_done,
            self._on_downloads_error,
        )

    async def _run_downloads(
        self, chats: list[ChatSummary], out_dir: str, make_html: bool, limit: int | None
    ) -> None:
        assert self._creds is not None, "not connected yet"
        # Share the one already-connected browsing client across the whole
        # batch instead of letting export_chat open a fresh client per
        # chat: reconnecting to the same local session file back-to-back is
        # slow and, in practice, can stall on the second connection.
        for chat in chats:
            self._download_progress.emit(chat.id, "Downloading...")
            try:
                await telegram_export.export_chat(
                    chat=str(chat.id),
                    api_id=self._creds.api_id,
                    api_hash=self._creds.api_hash,
                    session=self._session,
                    out_dir=Path(out_dir),
                    make_html=make_html,
                    limit=limit,
                    client=self._client,
                )
            except Exception as exc:  # noqa: BLE001 -- reported per-chat, rest of the batch continues
                self._download_progress.emit(chat.id, f"Failed: {exc}")
            else:
                self._download_progress.emit(chat.id, "Done")

    def _on_download_progress(self, chat_id: int, status: str) -> None:
        self._status_by_id[chat_id] = status
        row = self._find_row_for_chat_id(chat_id)
        if row is not None:
            # Sorting can reorder rows out from under a plain row-index
            # lookup; setItem() here is safe regardless since it's a plain
            # value replacement, not a structural change that needs a sort.
            self._table.setItem(row, COL_STATUS, QTableWidgetItem(status))

    def _find_row_for_chat_id(self, chat_id: int) -> int | None:
        for row in range(self._table.rowCount()):
            item = self._table.item(row, COL_SELECT)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == chat_id:
                return row
        return None

    def _on_downloads_done(self, _result: None) -> None:
        self._download_button.setEnabled(True)
        self._search_edit.setEnabled(True)
        self._status_label.setText("Download finished.")

    def _on_downloads_error(self, exc: BaseException) -> None:
        self._download_button.setEnabled(True)
        self._search_edit.setEnabled(True)
        self._status_label.setText(f"Download failed: {exc}")

    def _on_logout_clicked(self) -> None:
        assert self._client is not None, "not connected yet"
        self._logout_button.setEnabled(False)
        self._download_button.setEnabled(False)
        self._status_label.setText("Logging out...")
        # Both outcomes lead to the same cleanup: this button is the user's
        # only way back to the credentials form (e.g. to fix a typo'd
        # api_hash), including when the account was never actually
        # authorized in the first place -- exactly the case where
        # log_out()'s server-side revocation call is expected to fail.
        self._bridge.submit(self._perform_logout(), self._on_logout_finished, self._on_logout_finished)

    async def _perform_logout(self) -> None:
        try:
            await self._client.log_out()
        except Exception:
            # log_out() failed (e.g. this session was never authorized) --
            # it won't have disconnected on this path, so do it ourselves;
            # the session file can't be safely deleted while still open.
            await self._client.disconnect()

    def _on_logout_finished(self, _result: object) -> None:
        credentials.delete_credentials()
        Path(f"{self._session}.session").unlink(missing_ok=True)
        self._client = None
        self._creds = None
        self._all_chats = []
        self._filtered_chats = []
        self._participants_cache = {}
        self._selected_ids = set()
        self._status_by_id = {}
        self._search_edit.clear()
        self._table.setRowCount(0)
        self._status_label.setText("Not connected yet.")
        self.logged_out.emit()
