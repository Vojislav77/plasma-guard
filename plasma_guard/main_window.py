"""Main window: sidebar with views."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPushButton, QStackedWidget, QStatusBar,
    QStyle, QToolBar, QVBoxLayout, QWidget,
)

from . import notifications, paths, quarantine, reports
from .config import SettingsManager
from .dropzone import DropZone
from .icons import custom_icon
from .scanner import ClamAVScanner, ScanTarget
from .updater import FreshclamUpdater
from .ui import dashboard as dash_mod
from .ui import logs_view as logs_mod
from .ui import quarantine_view as qview_mod
from .ui import scan_view as sview_mod
from .ui import settings_view as setv_mod

log = logging.getLogger(__name__)

# Page IDs
PAGE_DASHBOARD = 0
PAGE_SCAN = 1
PAGE_QUARANTINE = 2
PAGE_LOGS = 3
PAGE_SETTINGS = 4


class MainWindow(QMainWindow):
    """The single top-level window."""

    quit_app = Signal()

    def __init__(self, scanner: ClamAVScanner, updater: FreshclamUpdater,
                 settings_manager: SettingsManager, tray) -> None:
        super().__init__()
        self.scanner = scanner
        self.updater = updater
        self.sm = settings_manager
        self.settings = settings_manager.settings
        self.tray = tray
        self._closing = False
        self._hidden_to_tray = False   # only notify once per hide
        self._active_threads: list = [] # all running worker threads
        self._build_ui()
        self._wire()
        self._apply_window_settings()
        self._refresh_statusbar()
        self._apply_drop_zone_visibility()
        # Connect to QApplication.aboutToQuit for safe shutdown
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._safe_shutdown)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        self.setWindowTitle("Plasma Guard")
        self.setWindowIcon(self._load_app_icon())
        self.resize(1320, 960)
        self.setMinimumSize(QSize(1080, 780))

        # Central split
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)


        # Sidebar
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        sbl = QVBoxLayout(sidebar)
        sbl.setContentsMargins(12, 18, 12, 12)
        sbl.setSpacing(6)

        brand = QHBoxLayout()
        brand.setSpacing(8)
        self.brand_icon = QLabel()
        self.brand_icon.setPixmap(self._load_app_icon().pixmap(36, 36))
        self.brand_icon.setFixedSize(36, 36)
        brand.addWidget(self.brand_icon)
        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)
        title = QLabel("Plasma Guard")
        title.setObjectName("titleLabel")
        title.setStyleSheet("font-size:18px;")
        ver = QLabel("v" + __import__("plasma_guard", fromlist=["__version__"]).__version__)
        ver.setObjectName("cardSub")
        brand_box.addWidget(title)
        brand_box.addWidget(ver)
        brand.addLayout(brand_box)
        brand.addStretch()
        sbl.addLayout(brand)

        sbl.addSpacing(14)

        self.list = QListWidget()
        self.list.setObjectName("sidebar")
        self._add_nav("Dashboard", "go-home", PAGE_DASHBOARD)
        self._add_nav("Scan", "system-search", PAGE_SCAN)
        self._add_nav("Quarantine", "emblem-warning", PAGE_QUARANTINE)
        self._add_nav("Logs", "text-x-generic", PAGE_LOGS)
        self._add_nav("Settings", "preferences-system", PAGE_SETTINGS)
        self.list.setCurrentRow(PAGE_DASHBOARD)
        sbl.addWidget(self.list, stretch=1)

        # Drop zone
        self.drop_zone = DropZone()
        self.drop_zone.file_dropped.connect(self._on_file_dropped)
        sbl.addWidget(self.drop_zone)

        # Footer / status
        self.sidebar_status = QLabel("● Protected")
        self.sidebar_status.setObjectName("sidebarStatus")
        self.sidebar_status.setStyleSheet("color: #2E7D32;")
        sbl.addWidget(self.sidebar_status)

        outer.addWidget(sidebar)

        # Pages
        self.stack = QStackedWidget()
        self.dashboard = dash_mod.DashboardView(self.scanner)
        self.scan_view = sview_mod.ScanView(self.scanner, self.updater, self.settings)
        self.quarantine_view = qview_mod.QuarantineView(self.settings)
        self.logs_view = logs_mod.LogsView()
        self.settings_view = setv_mod.SettingsView(self.sm)

        for w in (self.dashboard, self.scan_view, self.quarantine_view,
                  self.logs_view, self.settings_view):
            self.stack.addWidget(w)
        outer.addWidget(self.stack, stretch=1)

        # Status bar
        self.setStatusBar(QStatusBar())
        self._status_label = QLabel("")
        self.statusBar().addPermanentWidget(self._status_label)
        self._engine_label = QLabel("")
        self.statusBar().addPermanentWidget(self._engine_label)

    def _add_nav(self, label: str, icon_name: str, page_id: int) -> None:
        icon = custom_icon(f"nav-{icon_name}") or QIcon.fromTheme(icon_name)
        item = QListWidgetItem(icon, "  " + label)
        item.setData(Qt.UserRole, page_id)
        self.list.addItem(item)

    def _wire(self) -> None:
        self.list.currentRowChanged.connect(self.stack.setCurrentIndex)
        # Dashboard -> scan / update / etc.
        self.dashboard.scan_requested.connect(self._start_scan_path)
        self.dashboard.update_requested.connect(self._start_update)
        self.dashboard.open_quarantine_requested.connect(lambda: self.list.setCurrentRow(PAGE_QUARANTINE))
        self.dashboard.open_logs_requested.connect(lambda: self.list.setCurrentRow(PAGE_LOGS))
        self.dashboard.open_settings_requested.connect(lambda: self.list.setCurrentRow(PAGE_SETTINGS))
        # Scan view
        self.scan_view.finished.connect(self._on_scan_finished)
        self.scan_view.start_update_requested.connect(self._start_update)
        self.scan_view.scan_started.connect(self._on_scan_started)
        # Tray signals
        if self.tray:
            self.tray.show_requested.connect(self._show_from_tray)
            self.tray.scan_requested.connect(self._start_quick_scan)
            self.tray.update_requested.connect(self._start_update)
            self.tray.quit_requested.connect(self._on_quit)
            self.tray.open_quarantine.connect(lambda: self.list.setCurrentRow(PAGE_QUARANTINE))
            self.tray.open_logs.connect(lambda: self.list.setCurrentRow(PAGE_LOGS))
        # Shortcuts
        QShortcut(QKeySequence("Ctrl+Q"), self, self._on_quit)
        QShortcut(QKeySequence("Ctrl+1"), self, lambda: self.list.setCurrentRow(PAGE_DASHBOARD))
        QShortcut(QKeySequence("Ctrl+2"), self, lambda: self.list.setCurrentRow(PAGE_SCAN))
        QShortcut(QKeySequence("Ctrl+3"), self, lambda: self.list.setCurrentRow(PAGE_QUARANTINE))
        QShortcut(QKeySequence("Ctrl+4"), self, lambda: self.list.setCurrentRow(PAGE_LOGS))
        QShortcut(QKeySequence("Ctrl+5"), self, lambda: self.list.setCurrentRow(PAGE_SETTINGS))

    # ------------------------------------------------------------- scan

    def _track_thread(self, thread, worker) -> None:
        """Add a worker thread to the cleanup registry (idempotent)."""
        if thread is None or worker is None:
            return
        for th, _ in self._active_threads:
            if th is thread:
                return
        self._active_threads.append((thread, worker))

        def _cleanup(tt=thread):
            self._active_threads[:] = [
                (th, w) for th, w in self._active_threads if th is not tt
            ]
        thread.finished.connect(_cleanup)

    def _on_scan_started(self) -> None:
        """Track threads and update tray icon when ScanView starts a scan."""
        self._track_thread(self.scan_view._thread, self.scan_view._worker)
        if self.tray:
            self.tray.set_icon_scanning(True)

    def _start_scan_path(self, path: str, label: str) -> None:
        target = ScanTarget(path=path, label=label or Path(path).name)
        self.list.setCurrentRow(PAGE_SCAN)
        self.scan_view.start_scan(target)
        # Tracking + tray icon is handled by scan_started signal

    def _on_file_dropped(self, path: str) -> None:
        name = Path(path).name
        self._start_scan_path(path, name)

    def _apply_drop_zone_visibility(self) -> None:
        self.drop_zone.setVisible(self.settings.enable_drop_zone)

    def _start_quick_scan(self) -> None:
        home = str(Path.home())
        self._show_from_tray()
        self._start_scan_path(home, "Home (quick)")

    def _start_update(self) -> None:
        self._show_from_tray()
        self.list.setCurrentRow(PAGE_SCAN)
        self.scan_view.start_update()
        self._track_thread(self.scan_view._thread, self.scan_view._worker)
        if self.tray:
            self.tray.set_icon_scanning(True)

    def _on_scan_finished(self, result) -> None:
        if self.tray:
            self.tray.set_icon_scanning(False)
        if result is None:
            return
        # Save report
        try:
            reports.save_report(result)
        except Exception as exc:  # noqa: BLE001
            log.error("save_report failed: %s", exc)
        # Refresh
        self.dashboard.refresh()
        self.logs_view.refresh()
        self.quarantine_view.refresh()
        self._refresh_statusbar()
        # Notify
        if self.settings.show_notifications:
            if result.threats:
                msg = (f"{len(result.threats)} threat(s) found in "
                       f"{result.scanned_files} files.")
                notifications.notify("Plasma Guard — threats found", msg, "dialog-warning")
                if self.tray:
                    self.tray.notify("Plasma Guard — threats found", msg,
                                     self.tray.tray.Critical)
            else:
                msg = f"No threats found in {result.scanned_files} files."
                notifications.notify("Plasma Guard — clean", msg, "dialog-information")
                if self.tray:
                    self.tray.notify("Plasma Guard — clean", msg,
                                     self.tray.tray.Information)

    # ------------------------------------------------------------- tray

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._hidden_to_tray = False

    def _on_quit(self) -> None:
        self._closing = True
        self.quit_app.emit()
        # Stop all running worker threads before quitting
        self._safe_shutdown()
        # Explicitly tear down the tray icon BEFORE we quit
        if self.tray is not None:
            try:
                self.tray.hide()
            except Exception:
                pass
            try:
                self.tray.deleteLater()
            except Exception:
                pass
            self.tray = None
        QApplication.instance().quit()

    def _safe_shutdown(self) -> None:
        """Cancel and wait for any running worker threads.

        Without this, subprocess.Popen objects and their pipes get
        destroyed mid-execution when the app quits, which causes
        Python segfaults and triggers plasma-drkonqi.
        """
        for entry in list(self._active_threads):
            try:
                thread, worker = entry
                if hasattr(worker, "cancel"):
                    worker.cancel()
                if thread.isRunning():
                    thread.quit()
                    thread.wait(3000)  # 3s timeout
            except Exception as exc:
                log.warning("safe_shutdown: %s", exc)
        self._active_threads.clear()

    # ------------------------------------------------------------- misc

    def open_recent_scan(self, scan_id: str) -> None:
        self.list.setCurrentRow(PAGE_LOGS)
        self.logs_view.load_scan(scan_id)

    def _refresh_statusbar(self) -> None:
        if self.scanner.is_installed():
            self._engine_label.setText(f"engine: {self.scanner.version().split('/')[0]}")
            self.sidebar_status.setText("● Protected")
            self.sidebar_status.setStyleSheet("color: #2E7D32;")
        else:
            self._engine_label.setText("engine: NOT INSTALLED")
            self.sidebar_status.setStyleSheet("color: #C62828;")

    def _apply_window_settings(self) -> None:
        if self.settings.start_minimized_to_tray:
            QTimer.singleShot(100, self.hide)

    # ------------------------------------------------------------- close

    def closeEvent(self, event) -> None:
        if (self.settings.close_to_tray and not self._closing
                and self.tray is not None):
            event.ignore()
            self.hide()
            self._hidden_to_tray = True
            # Only notify once per "hide to tray" so it doesn't spam.
            if self.settings.show_notifications and not getattr(self, "_tray_notice_shown", False):
                notifications.notify(
                    "Plasma Guard",
                    "Plasma Guard is still running in the system tray.",
                    "dialog-information",
                    timeout_ms=3500,
                )
                self._tray_notice_shown = True
            return
        # Normal close: shut down cleanly
        self._closing = True
        self._safe_shutdown()
        if self.tray is not None:
            try:
                self.tray.hide()
                self.tray.deleteLater()
            except Exception:
                pass
            self.tray = None
        self.quit_app.emit()
        event.accept()

    def _load_app_icon(self) -> QIcon:
        for name in ("icon.svg", "icon-128.png", "icon-64.png", "icon-48.png",
                     "icon-32.png", "icon.png"):
            p = paths.asset_path(name)
            if p.exists():
                return QIcon(str(p))
        return QIcon.fromTheme("security-high")
