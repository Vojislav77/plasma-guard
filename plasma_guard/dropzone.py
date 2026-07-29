"""Drag-and-drop zone for quick file scanning."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QFont
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from .icons import icon


class DropZone(QFrame):
    """A small sidebar panel that accepts file drops and starts a scan."""

    file_dropped = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("dropZone")
        self.setMinimumHeight(110)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 10, 8, 10)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(4)

        self.icon = QLabel()
        self.icon.setPixmap(icon("document-open").pixmap(24, 24))
        self.icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.icon)

        self.label = QLabel("Drop files here\nto scan")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setObjectName("dropZoneLabel")
        lay.addWidget(self.label)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("drag-over", True)
            self.style().unpolish(self)
            self.style().polish(self)

    def dragLeaveEvent(self, event) -> None:
        self.setProperty("drag-over", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent) -> None:
        self.setProperty("drag-over", False)
        self.style().unpolish(self)
        self.style().polish(self)
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                p = Path(path)
                if p.exists():
                    self.file_dropped.emit(str(p.resolve()))
                    break
