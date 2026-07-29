"""Logs / scan history view."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from .. import reports
from .. import paths


class LogsView(QWidget):
    """Left: list of past scans. Right: details + raw log."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(14)

        title = QLabel("Scan logs")
        title.setObjectName("titleLabel")
        sub = QLabel("Browse every scan Plasma Guard has run. Click a row to see details.")
        sub.setObjectName("subtitleLabel")
        outer.addWidget(title)
        outer.addWidget(sub)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Left: list
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.itemSelectionChanged.connect(self._on_select)
        ll.addWidget(self.list, stretch=1)
        btn_row = QHBoxLayout()
        self.btn_refresh = QPushButton("  Refresh")
        self.btn_refresh.clicked.connect(self.refresh)
        btn_row.addWidget(self.btn_refresh)
        self.btn_open_dir = QPushButton("  Open reports folder")
        self.btn_open_dir.clicked.connect(self._open_dir)
        btn_row.addWidget(self.btn_open_dir)
        self.btn_clear = QPushButton("  Clear logs")
        self.btn_clear.clicked.connect(self._clear_logs)
        btn_row.addWidget(self.btn_clear)
        btn_row.addStretch()
        ll.addLayout(btn_row)
        splitter.addWidget(left)

        # Right: details
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        self.lbl_meta = QLabel("Select a scan to see details")
        self.lbl_meta.setObjectName("cardTitle")
        rl.addWidget(self.lbl_meta)
        self.log = QPlainTextEdit()
        self.log.setObjectName("logView")
        self.log.setReadOnly(True)
        rl.addWidget(self.log, stretch=1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        outer.addWidget(splitter, stretch=1)

    def refresh(self) -> None:
        self.list.clear()
        for r in reports.list_reports(limit=200):
            ts = time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(r["started_at"]))
            label = (f"{ts}  •  {r['scanned_files']} files  •  "
                     f"{r['infected_files']} infected  •  {r['target']}")
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, r["id"])
            self.list.addItem(item)
        if not self.list.count():
            self.list.addItem("(no scans yet)")

    def _on_select(self) -> None:
        items = self.list.selectedItems()
        if not items:
            return
        scan_id = items[0].data(Qt.UserRole)
        if not scan_id:
            return
        self.load_scan(scan_id)

    def load_scan(self, scan_id: str) -> None:
        data = reports.load_report(scan_id)
        if not data:
            self.lbl_meta.setText(f"Scan {scan_id} not found")
            self.log.clear()
            return

        # Build the meta line
        ts = time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(data.get("started_at", 0)))
        dur = data.get("finished_at", 0) - data.get("started_at", 0)
        ec = data.get("exit_code", -1)
        self.lbl_meta.setText(
            f"<b>{data.get('target', '?')}</b><br>"
            f"<span style='color:#666'>{ts} • duration {dur:.1f}s • exit {ec} • "
            f"{data.get('scanned_files', 0)} files, {data.get('infected_files', 0)} infected, "
            f"{data.get('errors', 0)} errors</span>"
        )

        # Pretty-print the full report as text
        lines: list[str] = []
        lines.append("=== Scan Report ===")
        lines.append(f"Scan ID     : {scan_id}")
        lines.append(f"Target      : {data.get('target')}")
        lines.append(f"Started     : {ts}")
        lines.append(f"Duration    : {dur:.2f} s")
        lines.append(f"Exit code   : {ec}")
        lines.append(f"Scanned     : {data.get('scanned_files')}")
        lines.append(f"Infected    : {data.get('infected_files')}")
        lines.append(f"Errors      : {data.get('errors')}")
        lines.append(f"Data MB     : {data.get('data_scanned_mb', 0):.2f}")
        lines.append("")
        lines.append("=== Threats ===")
        threats = data.get("threats", [])
        if threats:
            for t in threats:
                lines.append(f"  {t.get('path')}  ::  {t.get('signature')}")
        else:
            lines.append("  (none)")
        lines.append("")
        lines.append("=== Summary lines ===")
        for sl in data.get("summary_lines", []):
            lines.append(sl)
        if data.get("error_lines"):
            lines.append("")
            lines.append("=== Errors ===")
            for e in data["error_lines"]:
                lines.append(e)
        self.log.setPlainText("\n".join(lines))
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.Start)

    def _clear_logs(self) -> None:
        answer = QMessageBox.question(
            self, "Clear logs",
            "Delete all scan history? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            reports.clear_reports()
            self.refresh()
            self.lbl_meta.setText("Select a scan to see details")
            self.log.clear()

    def _open_dir(self) -> None:
        import subprocess
        try:
            subprocess.Popen(["xdg-open", str(paths.REPORTS_DIR)])
        except OSError as exc:
            QMessageBox.warning(self, "Open folder", str(exc))
