"""Quarantine management view."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..icons import icon
from .. import quarantine
from ..config import ScanSettings


class QuarantineView(QWidget):
    """Browse, restore, or delete quarantined items."""

    def __init__(self, settings: ScanSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(14)

        title = QLabel("Quarantine")
        title.setObjectName("titleLabel")
        sub = QLabel("Infected files are stored here, zipped and password-protected.")
        sub.setObjectName("subtitleLabel")
        outer.addWidget(title)
        outer.addWidget(sub)

        # Stat row
        stats = QHBoxLayout()
        stats.setSpacing(10)
        self.lbl_count = self._stat_box(stats, "Items", "0")
        self.lbl_size = self._stat_box(stats, "Total size", "0 KB")
        self.lbl_oldest = self._stat_box(stats, "Oldest", "—")
        self.lbl_newest = self._stat_box(stats, "Newest", "—")
        outer.addLayout(stats)

        # Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Quarantined at", "Original path", "Signature", "Size", "Note"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(320)
        outer.addWidget(self.table, stretch=1)

        # Actions
        actions = QHBoxLayout()
        self.btn_refresh = QPushButton("  Refresh")
        self.btn_refresh.setIcon(icon("view-refresh"))
        self.btn_refresh.clicked.connect(self.refresh)
        actions.addWidget(self.btn_refresh)

        self.btn_restore = QPushButton("  Restore…")
        self.btn_restore.setIcon(icon("document-save-as"))
        self.btn_restore.clicked.connect(self._on_restore)
        actions.addWidget(self.btn_restore)

        self.btn_delete = QPushButton("  Delete")
        self.btn_delete.setIcon(icon("edit-delete"))
        self.btn_delete.clicked.connect(self._on_delete)
        actions.addWidget(self.btn_delete)

        self.btn_clear = QPushButton("  Empty quarantine")
        self.btn_clear.setIcon(icon("user-trash"))
        self.btn_clear.setObjectName("danger")
        self.btn_clear.clicked.connect(self._on_clear)
        actions.addWidget(self.btn_clear)
        actions.addStretch()
        outer.addLayout(actions)

    def _stat_box(self, parent_lay, title: str, value: str) -> QLabel:
        card = QFrame()
        card.setObjectName("card")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 10)
        t = QLabel(title)
        t.setObjectName("cardSub")
        v = QLabel(value)
        v.setObjectName("cardBig")
        lay.addWidget(t)
        lay.addWidget(v)
        parent_lay.addWidget(card)
        return v

    # ----------------------------------------------------------------- ops

    def refresh(self) -> None:
        entries = quarantine.list_entries()
        self.table.setRowCount(0)
        for e in entries:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(
                time.strftime("%d/%m/%Y %H:%M", time.localtime(e.quarantined_at))))
            self.table.setItem(r, 1, QTableWidgetItem(e.original_path))
            self.table.setItem(r, 2, QTableWidgetItem(e.signature))
            self.table.setItem(r, 3, QTableWidgetItem(self._human_size(e.size_bytes)))
            self.table.setItem(r, 4, QTableWidgetItem(e.note))
            # Stash id on the row
            self.table.item(r, 0).setData(Qt.UserRole, e.id)

        stats = quarantine.quarantine_stats()
        self.lbl_count.setText(str(stats["count"]))
        self.lbl_size.setText(self._human_size(stats["total_bytes"]))
        if stats["oldest"]:
            self.lbl_oldest.setText(time.strftime("%d/%m/%Y", time.localtime(stats["oldest"])))
        if stats["newest"]:
            self.lbl_newest.setText(time.strftime("%d/%m/%Y", time.localtime(stats["newest"])))

    def _selected_id(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        if not item:
            return None
        return item.data(Qt.UserRole)

    def _on_restore(self) -> None:
        eid = self._selected_id()
        if not eid:
            QMessageBox.information(self, "Restore", "Select an item first.")
            return
        target = QFileDialog.getExistingDirectory(self, "Restore to…", str(Path.home()))
        if not target:
            return
        confirm = QMessageBox.question(
            self, "Restore file",
            "Restoring an infected file is dangerous. Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        out = quarantine.restore_entry(
            eid, target_dir=target, password=self.settings.quarantine_password,
        )
        if out:
            QMessageBox.information(self, "Restored", f"Restored to:\n{out}")
        else:
            QMessageBox.warning(self, "Restore failed",
                                "Could not restore the file. See logs.")
        self.refresh()

    def _on_delete(self) -> None:
        eid = self._selected_id()
        if not eid:
            QMessageBox.information(self, "Delete", "Select an item first.")
            return
        confirm = QMessageBox.question(
            self, "Delete",
            "Permanently delete this quarantined file? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        quarantine.delete_entry(eid)
        self.refresh()

    def _on_clear(self) -> None:
        confirm = QMessageBox.question(
            self, "Empty quarantine",
            "Permanently delete ALL quarantined files?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        n = quarantine.clear_quarantine()
        QMessageBox.information(self, "Done", f"Deleted {n} item(s).")
        self.refresh()

    @staticmethod
    def _human_size(n: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.0f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"
