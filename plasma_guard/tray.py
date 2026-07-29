"""System tray icon for PlasmaGuard.

Plasma 6 fully supports the StatusNotifierItem protocol that Qt's
QSystemTrayIcon implements, so this works out of the box.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import paths

log = logging.getLogger(__name__)


class TrayController(QObject):
    """Wraps QSystemTrayIcon + a context menu."""

    show_requested = Signal()
    scan_requested = Signal()
    update_requested = Signal()
    quit_requested = Signal()
    open_quarantine = Signal()
    open_logs = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.tray = QSystemTrayIcon(self._load_icon(), self)
        self.tray.setToolTip("Plasma Guard — your system is protected")
        self._build_menu()
        self.tray.activated.connect(self._on_activated)

    # ----------------------------------------------------------- public

    def show(self) -> None:
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        else:
            log.warning("System tray is not available on this session")

    def hide(self) -> None:
        self.tray.hide()

    def notify(self, title: str, message: str, icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.Information) -> None:
        self.tray.showMessage(title, message, icon, 5000)

    def set_tooltip(self, text: str) -> None:
        self.tray.setToolTip(text)

    def set_icon_scanning(self, active: bool) -> None:
        """Swap between idle and 'scanning' iconography."""
        if active:
            pix = self._load_pixmap()
            painter = QPainter(pix)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(QColor("#FFB300"))
            painter.setPen(QColor("#B27100"))
            painter.drawEllipse(pix.width() * 0.66, pix.height() * 0.05,
                                pix.width() * 0.28, pix.height() * 0.28)
            painter.end()
            self.tray.setIcon(QIcon(pix))
        else:
            self.tray.setIcon(self._load_icon())

    # ----------------------------------------------------------- private

    def _load_icon(self) -> QIcon:
        # Prefer the multi-resolution SVG
        for name in ("icon.svg", "icon-128.png", "icon-64.png", "icon-48.png",
                     "icon-32.png", "icon.png"):
            p = paths.asset_path(name)
            if p.exists():
                return QIcon(str(p))
        return QIcon.fromTheme("security-high")

    def _load_pixmap(self) -> QPixmap:
        for name in ("icon-128.png", "icon-64.png", "icon-48.png", "icon-32.png",
                     "icon.png", "icon.svg"):
            p = paths.asset_path(name)
            if p.exists():
                pix = QPixmap(str(p))
                if not pix.isNull():
                    return pix
        return QPixmap(64, 64)

    def _build_menu(self) -> None:
        m = QMenu()
        act_show = QAction("Open Plasma Guard", m)
        act_show.triggered.connect(self.show_requested.emit)
        m.addAction(act_show)

        m.addSeparator()
        act_scan = QAction("Quick scan (Home)", m)
        act_scan.triggered.connect(self.scan_requested.emit)
        m.addAction(act_scan)

        act_update = QAction("Update database", m)
        act_update.triggered.connect(self.update_requested.emit)
        m.addAction(act_update)

        m.addSeparator()
        act_q = QAction("Open quarantine", m)
        act_q.triggered.connect(self.open_quarantine.emit)
        m.addAction(act_q)
        act_l = QAction("View logs", m)
        act_l.triggered.connect(self.open_logs.emit)
        m.addAction(act_l)

        m.addSeparator()
        act_quit = QAction("Quit", m)
        act_quit.triggered.connect(self.quit_requested.emit)
        m.addAction(act_quit)
        self.menu = m
        self.tray.setContextMenu(m)

    def _on_activated(self, reason) -> None:
        # Single click = show window. Double click = open window. Right click
        # handled by the context menu automatically.
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_requested.emit()
