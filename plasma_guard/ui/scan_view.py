"""Scan view: in-progress scan, live progress, live threats list, log stream."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton,
    QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..icons import icon
from ..scanner import ClamAVScanner, ScanResult, ScanTarget, default_targets, detect_usb_mounts
from ..updater import FreshclamUpdater
from ..workers import start_scan, start_update


class _CountersCard(QFrame):
    """Three counters in a row: scanned / infected / errors."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(20)
        self.lbl_scanned = self._make_pair(lay, "Scanned", "0")
        self.lbl_infected = self._make_pair(lay, "Infected", "0")
        self.lbl_errors = self._make_pair(lay, "Errors", "0")
        self.lbl_data = self._make_pair(lay, "Data", "0 MB")

    def _make_pair(self, parent_lay: QHBoxLayout, title: str, value: str) -> QLabel:
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("cardSub")
        v = QLabel(value)
        v.setObjectName("cardBig")
        col.addWidget(t)
        col.addWidget(v)
        wrapper = QWidget()
        wrapper.setLayout(col)
        parent_lay.addWidget(wrapper)
        return v

    def set_counts(self, scanned: int, infected: int, errors: int, data_mb: float) -> None:
        self.lbl_scanned.setText(f"{scanned:,}")
        self.lbl_infected.setText(f"{infected:,}")
        self.lbl_errors.setText(f"{errors:,}")
        if data_mb >= 1024:
            self.lbl_data.setText(f"{data_mb/1024:.2f} GB")
        else:
            self.lbl_data.setText(f"{data_mb:.1f} MB")


class ScanView(QWidget):
    """Active scan UI: target, progress, log stream, live threats."""

    cancelled = Signal()
    finished = Signal(object)  # ScanResult
    start_update_requested = Signal()
    scan_started = Signal()

    def __init__(self, scanner: ClamAVScanner, updater: FreshclamUpdater,
                 settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.scanner = scanner
        self.updater = updater
        self.settings = settings
        self._thread: QThread | None = None
        self._worker = None
        self._result: ScanResult | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(14)

        # Title
        self.title = QLabel("Scan")
        self.title.setObjectName("titleLabel")
        self.subtitle = QLabel("Select a target below to start scanning")
        self.subtitle.setObjectName("subtitleLabel")
        outer.addWidget(self.title)
        outer.addWidget(self.subtitle)

        # --- Scan starter section (shown when idle) ---
        self.starters = QWidget()
        starter_lay = QVBoxLayout(self.starters)
        starter_lay.setSpacing(10)

        q_label = QLabel("Quick scan")
        q_label.setObjectName("cardTitle")
        starter_lay.addWidget(q_label)

        self.actions_row = QHBoxLayout()
        self.actions_row.setSpacing(10)

        for target in default_targets():
            btn = QPushButton(f"  {target.label}")
            btn.setIcon(icon("folder"))
            btn.setMinimumHeight(44)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.clicked.connect(lambda checked=False, p=target.path, l=target.label:
                                self._start_scan_from_button(p, l))
            self.actions_row.addWidget(btn, stretch=1)

        self.btn_pick_file = QPushButton("  Scan a file…")
        self.btn_pick_file.setIcon(icon("document-open"))
        self.btn_pick_file.setMinimumHeight(44)
        self.btn_pick_file.clicked.connect(self._pick_file)
        self.actions_row.addWidget(self.btn_pick_file)

        self.btn_pick_dir = QPushButton("  Scan a folder…")
        self.btn_pick_dir.setIcon(icon("folder-open"))
        self.btn_pick_dir.setMinimumHeight(44)
        self.btn_pick_dir.clicked.connect(self._pick_dir)
        self.actions_row.addWidget(self.btn_pick_dir)

        starter_lay.addLayout(self.actions_row)

        self.usb_row = QHBoxLayout()
        self.usb_row.setSpacing(10)
        starter_lay.addLayout(self.usb_row)
        self._refresh_usb_row()

        outer.addWidget(self.starters)

        # Status row
        self.lbl_status = QLabel("Idle")
        self.lbl_status.setObjectName("scanBold")
        outer.addWidget(self.lbl_status)

        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setFormat("Scanning…")
        self.progress.setValue(0)
        outer.addWidget(self.progress)

        self.lbl_current = QLabel(" ")
        self.lbl_current.setObjectName("cardSub")
        self.lbl_current.setWordWrap(True)
        outer.addWidget(self.lbl_current)

        # Counters
        self.counters = _CountersCard()
        outer.addWidget(self.counters)

        # Threats table
        threats_box = QVBoxLayout()
        threats_box.setSpacing(4)
        t_title = QLabel("Threats found")
        t_title.setObjectName("cardTitle")
        threats_box.addWidget(t_title)
        self.threats = QTableWidget(0, 2)
        self.threats.setHorizontalHeaderLabels(["File", "Signature"])
        self.threats.horizontalHeader().setStretchLastSection(True)
        self.threats.verticalHeader().setVisible(False)
        self.threats.setSelectionBehavior(QTableWidget.SelectRows)
        self.threats.setEditTriggers(QTableWidget.NoEditTriggers)
        self.threats.setMinimumHeight(160)
        threats_box.addWidget(self.threats)
        outer.addLayout(threats_box, stretch=1)

        # Log
        log_title = QLabel("Live log")
        log_title.setObjectName("cardTitle")
        outer.addWidget(log_title)
        self.log = QPlainTextEdit()
        self.log.setObjectName("logView")
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(180)
        outer.addWidget(self.log)

        # Actions
        actions = QHBoxLayout()
        self.btn_cancel = QPushButton("  Cancel scan")
        self.btn_cancel.setIcon(icon("process-stop"))
        self.btn_cancel.setObjectName("danger")
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_cancel.setEnabled(False)
        actions.addWidget(self.btn_cancel)

        self.btn_update = QPushButton("  Update database")
        self.btn_update.setIcon(icon("system-software-update"))
        self.btn_update.clicked.connect(self.start_update_requested.emit)
        actions.addWidget(self.btn_update)

        actions.addStretch()
        self.btn_done = QPushButton("  Done")
        self.btn_done.setIcon(icon("dialog-ok"))
        self.btn_done.clicked.connect(lambda: self.finished.emit(self._result))
        self.btn_done.setEnabled(False)
        actions.addWidget(self.btn_done)
        outer.addLayout(actions)

    # -------------------------------------------------------------- control

    def _cleanup_thread(self) -> None:
        self._thread = None
        self._worker = None

    def start_scan(self, target: ScanTarget) -> None:
        if self._thread:
            try:
                if self._thread.isRunning():
                    return
            except RuntimeError:
                self._cleanup_thread()
        self._result = None
        self.log.clear()
        self.threats.setRowCount(0)
        self.counters.set_counts(0, 0, 0, 0.0)
        self.progress.setRange(0, 0)
        self.progress.setFormat("Scanning…")
        self.lbl_status.setText(f"Scanning: {target.label or target.path}")
        self.title.setText(f"Scan: {target.label or target.path}")
        self.subtitle.setText("Live progress and threats")
        self.lbl_current.setText(" ")
        self.starters.hide()
        self.btn_cancel.setEnabled(True)
        self.btn_done.setEnabled(False)
        self.btn_update.setEnabled(False)
        self._append_log(f"=== Starting scan of {target.path} ===")

        self._thread, self._worker = start_scan(self.scanner, target, self.settings, parent=self)
        self._worker.started.connect(lambda p: self.lbl_status.setText(f"Started: {p}"))
        self._worker.progress.connect(self._on_progress)
        self._worker.threat_found.connect(self._on_threat)
        self._worker.log_line.connect(self._append_log)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_finished)
        self._worker.cancelled.connect(self._on_cancelled)
        self._thread.start()
        self.scan_started.emit()

    def start_update(self) -> None:
        if self._thread:
            try:
                if self._thread.isRunning():
                    return
            except RuntimeError:
                self._cleanup_thread()
        self.log.clear()
        self.threats.setRowCount(0)
        self.progress.setRange(0, 0)
        self.progress.setFormat("Updating database…")
        self.lbl_status.setText("Updating ClamAV virus database…")
        self.title.setText("Update virus database")
        self.lbl_current.setText(" ")
        self.btn_cancel.setEnabled(True)
        self.btn_done.setEnabled(False)
        self.btn_update.setEnabled(False)
        self._append_log("=== Running freshclam ===")

        self._thread, self._worker = start_update(self.updater, parent=self)
        self._worker.log_line.connect(self._append_log)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_update_finished)
        self._thread.start()

    def _on_cancel(self) -> None:
        if self._worker and hasattr(self._worker, "cancel"):
            self._worker.cancel()
        self.btn_cancel.setEnabled(False)
        self.lbl_status.setText("Cancelling…")

    def _on_progress(self, line: str) -> None:
        # Use the most recent file as the "current" line, truncated.
        if len(line) > 100:
            line = "…" + line[-99:]
        self.lbl_current.setText(line)
        # Make the progress bar appear active by ticking.
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 0)

    def _on_threat(self, path: str, sig: str) -> None:
        r = self.threats.rowCount()
        self.threats.insertRow(r)
        self.threats.setItem(r, 0, QTableWidgetItem(path))
        self.threats.setItem(r, 1, QTableWidgetItem(sig))
        self.threats.scrollToBottom()

    def _on_error(self, msg: str) -> None:
        self.lbl_status.setText(f"Error: {msg}")

    def _append_log(self, line: str) -> None:
        self.log.appendPlainText(line)
        # Trim log to last 5000 lines to avoid runaway memory.
        if self.log.blockCount() > 5000:
            cursor = self.log.textCursor()
            cursor.movePosition(QTextCursor.Start)
            cursor.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor, 1000)
            cursor.removeSelectedText()
            cursor.deleteChar()

    def _on_finished(self, result: ScanResult) -> None:
        self._cleanup_thread()
        self._result = result
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.counters.set_counts(
            result.scanned_files, result.infected_files, result.errors,
            result.data_scanned_mb,
        )
        if result.threats:
            self.lbl_status.setText(
                f"⚠ {len(result.threats)} threat(s) found in "
                f"{result.scanned_files} files ({result.duration_s:.1f} s)"
            )
        else:
            self.lbl_status.setText(
                f"✓ No threats found — {result.scanned_files} files clean "
                f"({result.duration_s:.1f} s)"
            )
        self.title.setText("Scan complete")
        self.subtitle.setText("Select a target below to start another scan")
        self.starters.show()
        self.btn_cancel.setEnabled(False)
        self.btn_done.setEnabled(True)
        self.btn_update.setEnabled(True)
        self.finished.emit(result)

    def _on_cancelled(self) -> None:
        self._cleanup_thread()
        self.lbl_status.setText("Scan cancelled by user")
        self.title.setText("Scan cancelled")
        self.subtitle.setText("Select a target below to start another scan")
        self.starters.show()
        self.btn_cancel.setEnabled(False)
        self.btn_done.setEnabled(True)
        self.btn_update.setEnabled(True)

    def _on_update_finished(self, result) -> None:
        self._cleanup_thread()
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.lbl_status.setText(result.message or "Update finished")
        self.title.setText("Update complete")
        self.subtitle.setText("Select a target below to start another scan")
        self.starters.show()
        self.btn_cancel.setEnabled(False)
        self.btn_done.setEnabled(True)
        self.btn_update.setEnabled(True)

    # --- internal scan starters ---

    def _start_scan_from_button(self, path: str, label: str) -> None:
        self.start_scan(ScanTarget(path=path, label=label))

    def _pick_file(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "Choose a file to scan",
                                              str(Path.home()))
        if path:
            self._start_scan_from_button(path, Path(path).name)

    def _pick_dir(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(self, "Choose a folder to scan",
                                                str(Path.home()))
        if path:
            self._start_scan_from_button(path, Path(path).name)

    def _refresh_usb_row(self) -> None:
        while self.usb_row.count():
            item = self.usb_row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for t in detect_usb_mounts():
            btn = QPushButton(f"  {t.label}")
            btn.setIcon(icon("drive-harddisk-usb"))
            btn.setMinimumHeight(44)
            btn.setObjectName("outline")
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.clicked.connect(lambda checked=False, p=t.path, l=t.label:
                                self._start_scan_from_button(p, l))
            self.usb_row.addWidget(btn, stretch=1)
        self.usb_row.addStretch()
