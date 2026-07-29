"""Qt workers (run in QThreads) for long-running operations.

Signals are defined here so the UI can connect to them on the main thread.
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal

from . import quarantine
from .config import ScanSettings
from .scanner import ClamAVScanner, ScanResult, ScanTarget, Threat
from .updater import FreshclamUpdater, UpdateResult

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scan worker
# ---------------------------------------------------------------------------


class ScanWorker(QObject):
    """Runs a clamscan in a worker thread."""

    started = Signal(str)               # target path
    progress = Signal(str)              # current file
    threat_found = Signal(str, str)     # path, signature
    log_line = Signal(str)              # raw log line
    error = Signal(str)                 # error message
    finished = Signal(object)           # ScanResult
    cancelled = Signal()

    def __init__(self, scanner: ClamAVScanner, target: ScanTarget,
                 settings: ScanSettings) -> None:
        super().__init__()
        self.scanner = scanner
        self.target = target
        self.settings = settings
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        self.started.emit(self.target.path)
        opts = {
            "scan_archives": self.settings.scan_archives,
            "scan_mail": self.settings.scan_mail,
            "heuristic_alerts": self.settings.heuristic_alerts,
            "max_file_size_mb": self.settings.max_file_size_mb,
            "max_scan_time_s": self.settings.max_scan_time_s,
            "enable_logging": self.settings.enable_logging,
        }
        result = self.scanner.scan(
            target=self.target,
            options=opts,
            on_progress=lambda p: self.progress.emit(p),
            on_threat=lambda t: self.threat_found.emit(t.path, t.signature),
            on_log=lambda l: self.log_line.emit(l),
            on_error=lambda e: self.error.emit(e),
            cancel=lambda: self._cancel,
        )

        # Auto-quarantine if requested.
        if self.settings.auto_quarantine and result.threats:
            for t in result.threats:
                try:
                    quarantine.quarantine_file(
                        t.path, t.signature,
                        note=f"auto-quarantined by scan at {time.strftime('%Y-%m-%d %H:%M:%S')}",
                        password=self.settings.quarantine_password,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.error("auto-quarantine failed for %s: %s", t.path, exc)
                    self.error.emit(f"quarantine failed for {t.path}: {exc}")

        if self._cancel:
            self.cancelled.emit()
        self.finished.emit(result)


def start_scan(scanner: ClamAVScanner, target: ScanTarget, settings: ScanSettings,
               parent: QObject | None = None) -> tuple[QThread, ScanWorker]:
    """Wire up a scan worker to a QThread. Returns (thread, worker)."""
    thread = QThread(parent)
    worker = ScanWorker(scanner, target, settings)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.cancelled.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    return thread, worker


# ---------------------------------------------------------------------------
# Update worker
# ---------------------------------------------------------------------------


class UpdateWorker(QObject):
    progress = Signal(str)
    log_line = Signal(str)
    error = Signal(str)
    finished = Signal(object)  # UpdateResult

    def __init__(self, updater: FreshclamUpdater) -> None:
        super().__init__()
        self.updater = updater
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        result = self.updater.update(
            on_log=lambda l: self.log_line.emit(l),
            on_progress=lambda p: self.progress.emit(p),
            cancel=lambda: self._cancel,
        )
        self.finished.emit(result)


def start_update(updater: FreshclamUpdater, parent: QObject | None = None
                 ) -> tuple[QThread, UpdateWorker]:
    thread = QThread(parent)
    worker = UpdateWorker(updater)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    return thread, worker
