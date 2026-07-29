"""Dashboard view: status, quick actions, recent scans."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import paths, quarantine, reports
from ..icons import icon
from ..scanner import ClamAVScanner, default_targets, detect_usb_mounts
from ..updater import database_info


class StatCard(QFrame):
    """A small stat tile."""

    def __init__(self, title: str, value: str, sub: str = "",
                 object_name: str = "card") -> None:
        super().__init__()
        self.setObjectName(object_name)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(96)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(4)
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        self.value = QLabel(value)
        self.value.setObjectName("cardBig")
        # Allow long values to wrap rather than clip
        self.value.setWordWrap(True)
        self.value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.sub = QLabel(sub)
        self.sub.setObjectName("cardSub")
        self.sub.setWordWrap(True)
        lay.addWidget(self.title)
        lay.addWidget(self.value)
        lay.addWidget(self.sub)

    def set(self, value: str, sub: str = "") -> None:
        self.value.setText(value)
        if sub:
            self.sub.setText(sub)


class DashboardView(QWidget):
    """First page the user sees when opening the app."""

    scan_requested = Signal(str, str)  # path, label
    update_requested = Signal()
    open_quarantine_requested = Signal()
    open_logs_requested = Signal()
    open_settings_requested = Signal()

    def __init__(self, scanner: ClamAVScanner, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.scanner = scanner
        self._build_ui()
        # Refresh on construction and every 30s.
        self.refresh()
        self._timer = QTimer(self)
        self._timer.setInterval(30_000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Wrap everything in a scroll area so the dashboard always fits,
        # even on smaller screens or with many USB drives.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        body = QWidget()
        scroll.setWidget(body)
        body_outer = QVBoxLayout(body)
        body_outer.setContentsMargins(28, 24, 28, 24)
        body_outer.setSpacing(18)

        # Header
        header = QHBoxLayout()
        title = QLabel("Plasma Guard")
        title.setObjectName("titleLabel")
        sub = QLabel("Modern ClamAV-powered protection for Linux")
        sub.setObjectName("subtitleLabel")
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_box.addWidget(title)
        title_box.addWidget(sub)
        header.addLayout(title_box)
        header.addStretch()
        self.status_label = QLabel("●")
        self.status_label.setObjectName("statusDot")
        header.addWidget(self.status_label)
        body_outer.addLayout(header)

        # Stat cards (2 rows x 3 cols)
        cards = QGridLayout()
        cards.setSpacing(14)
        self.card_db = StatCard("Virus database", "—", "Checking…", "card")
        self.card_status = StatCard("Protection", "On-demand", "Manual scans only", "cardOk")
        self.card_last = StatCard("Last scan", "—", "No scans yet", "card")
        self.card_quarantine = StatCard("Quarantine", "0", "items", "card")
        cards.addWidget(self.card_db, 0, 0)
        cards.addWidget(self.card_status, 0, 1)
        cards.addWidget(self.card_last, 0, 2)
        cards.addWidget(self.card_quarantine, 1, 0)
        cards.addWidget(self._build_engine_card(), 1, 1)
        cards.addWidget(self._build_usb_card(), 1, 2)
        body_outer.addLayout(cards)

        # Quick actions
        actions_box = QVBoxLayout()
        actions_box.setSpacing(10)
        a_title = QLabel("Quick actions")
        a_title.setObjectName("cardTitle")
        actions_box.addWidget(a_title)
        a_row = QHBoxLayout()
        a_row.setSpacing(10)
        self.btn_update = QPushButton("  Update database")
        self.btn_update.setIcon(icon("system-software-update"))
        self.btn_update.setObjectName("primary")
        self.btn_update.setMinimumHeight(50)
        self.btn_update.clicked.connect(self.update_requested.emit)
        a_row.addWidget(self.btn_update)

        self.btn_quarantine = QPushButton("  Quarantine")
        self.btn_quarantine.setIcon(icon("emblem-warning"))
        self.btn_quarantine.setMinimumHeight(50)
        self.btn_quarantine.clicked.connect(self.open_quarantine_requested.emit)
        a_row.addWidget(self.btn_quarantine)

        self.btn_logs = QPushButton("  View logs")
        self.btn_logs.setIcon(icon("text-x-generic"))
        self.btn_logs.setMinimumHeight(50)
        self.btn_logs.clicked.connect(self.open_logs_requested.emit)
        a_row.addWidget(self.btn_logs)

        self.btn_settings = QPushButton("  Settings")
        self.btn_settings.setIcon(icon("preferences-system"))
        self.btn_settings.setMinimumHeight(50)
        self.btn_settings.clicked.connect(self.open_settings_requested.emit)
        a_row.addWidget(self.btn_settings)
        actions_box.addLayout(a_row)
        body_outer.addLayout(actions_box)

        # Quick scan targets
        targets_box = QVBoxLayout()
        targets_box.setSpacing(8)
        t_title = QLabel("Quick scan")
        t_title.setObjectName("cardTitle")
        targets_box.addWidget(t_title)

        self.actions_row = QHBoxLayout()
        self.actions_row.setSpacing(10)
        for target in default_targets():
            btn = QPushButton(f"  {target.label}")
            btn.setIcon(icon("folder"))
            btn.setMinimumHeight(44)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.clicked.connect(lambda checked=False, p=target.path, l=target.label:
                                self.scan_requested.emit(p, l))
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
        targets_box.addLayout(self.actions_row)

        # USB row
        self.usb_row = QHBoxLayout()
        self.usb_row.setSpacing(10)
        targets_box.addLayout(self.usb_row)
        body_outer.addLayout(targets_box)

        # Recent scans
        recent_box = QVBoxLayout()
        recent_box.setSpacing(6)
        r_title = QLabel("Recent scans")
        r_title.setObjectName("cardTitle")
        recent_box.addWidget(r_title)
        self.recent_list = QListWidget()
        self.recent_list.setMinimumHeight(180)
        self.recent_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.recent_list.itemDoubleClicked.connect(self._open_recent)
        recent_box.addWidget(self.recent_list, stretch=1)
        body_outer.addLayout(recent_box, stretch=1)

    def _build_engine_card(self) -> QFrame:
        self.card_engine = StatCard("ClamAV engine", "—", "Detecting…", "card")
        return self.card_engine

    def _build_usb_card(self) -> QFrame:
        self.card_usb = StatCard("Removable drives", "0", "Detecting…", "card")
        return self.card_usb

    # ------------------------------------------------------------------ actions

    def _pick_file(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "Choose a file to scan",
                                              str(Path.home()))
        if path:
            self.scan_requested.emit(path, Path(path).name)

    def _pick_dir(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(self, "Choose a folder to scan",
                                                str(Path.home()))
        if path:
            self.scan_requested.emit(path, Path(path).name)

    def _open_recent(self, item: QListWidgetItem) -> None:
        scan_id = item.data(Qt.UserRole)
        if not scan_id:
            return
        # Forward to the logs view via the main window.
        main = self.window()
        if hasattr(main, "open_recent_scan"):
            main.open_recent_scan(scan_id)

    # ------------------------------------------------------------------ refresh

    def refresh(self) -> None:
        # Engine version
        ver = self.scanner.version()
        if ver.startswith("not installed"):
            self.card_engine.set("Not installed", "Run: sudo dnf install clamav")
        else:
            short = ver.split("/")[0] if "/" in ver else ver
            self.card_engine.set(short, "Engine ready")
        # Database
        info = database_info()
        if info.get("exists") == "no":
            self.card_db.set("Empty", "Run an update")
        else:
            age = float(info.get("age_hours", 0))
            self.card_db.set(info.get("newest_file", "—"),
                             f"updated {age:.1f} h ago • {info.get('total_size_mb', '0')} MB")
            if age > 72:
                self.card_db.setObjectName("cardDanger")
        # Quarantine
        stats = quarantine.quarantine_stats()
        self.card_quarantine.set(str(stats["count"]), "items stored safely")
        # USB
        usb = detect_usb_mounts()
        self.card_usb.set(str(len(usb)),
                          ", ".join(Path(t.path).name for t in usb) if usb else "No drives mounted")
        # Rebuild USB row
        self._rebuild_usb_row(usb)
        # Recent scans
        self._rebuild_recent()

    def _rebuild_usb_row(self, usb) -> None:
        # Clear existing
        while self.usb_row.count():
            item = self.usb_row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for t in usb:
            btn = QPushButton(f"  {t.label}")
            btn.setIcon(icon("drive-harddisk-usb"))
            btn.setMinimumHeight(44)
            btn.setObjectName("outline")
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.clicked.connect(lambda checked=False, p=t.path, l=t.label:
                                self.scan_requested.emit(p, l))
            self.usb_row.addWidget(btn, stretch=1)
        self.usb_row.addStretch()

    def _rebuild_recent(self) -> None:
        self.recent_list.clear()
        for r in reports.list_reports(limit=15):
            ts = time.strftime("%d/%m/%Y %H:%M", time.localtime(r["started_at"]))
            label = f"{ts} — {r['target']} — {r['scanned_files']} files, {r['infected_files']} infected"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, r["id"])
            self.recent_list.addItem(item)
        if not self.recent_list.count():
            self.recent_list.addItem("(no scans yet)")

    @staticmethod
    def _human_size(path: str) -> str:
        try:
            total = 0
            p = Path(path)
            if p.is_file():
                total = p.stat().st_size
            else:
                for f in p.rglob("*"):
                    if f.is_file():
                        try:
                            total += f.stat().st_size
                        except OSError:
                            pass
            for unit in ("B", "KB", "MB", "GB", "TB"):
                if total < 1024:
                    return f"{total:.0f}{unit}"
                total /= 1024
            return f"{total:.1f}PB"
        except OSError:
            return "?"
