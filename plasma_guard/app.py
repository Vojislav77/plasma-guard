"""QApplication setup and main entry point.

This module wires together: the QApplication, the system tray, the main
window, the scanner / updater objects, settings, and signal connections.

It also handles the headless ``--scheduled-scan`` mode used by the
systemd user timer.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTimer, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __app_name__, __version__, notifications, paths, reports
from .config import SettingsManager
from .main_window import MainWindow
from .scanner import ClamAVScanner, ScanTarget, default_targets
from .tray import TrayController
from .updater import FreshclamUpdater


# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------

def _install_global_exception_hook() -> None:
    """Catch unhandled exceptions so the process never dies silently.

    Without this, an unhandled exception in a Qt slot kills the
    interpreter — which is what was happening on tray-exit and triggering
    plasma-drkonqi to file a crash report.
    """
    def excepthook(exc_type, exc_value, exc_tb):
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logging.error("UNHANDLED EXCEPTION:\n%s", msg)
        # Print to stderr so it's visible if launched from a terminal
        print("UNHANDLED EXCEPTION:", file=sys.stderr)
        print(msg, file=sys.stderr)
        # If Qt is up, show a dialog (non-blocking)
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                QMessageBox.critical(
                    None, "Plasma Guard - unexpected error",
                    f"An unexpected error occurred:\n\n{exc_value}\n\n"
                    f"See {paths.LOG_FILE} for details."
                )
        except Exception:
            pass

    sys.excepthook = excepthook

    # Qt slots can swallow exceptions otherwise
    try:
        from PySide6.QtCore import qInstallMessageHandler
        def qt_message_handler(mode, ctx, msg):
            # Log Qt warnings/errors so they show up in our log file
            # Suppress the harmless portal registration warning (KDE caches
            # .desktop files in ksycoca so a newly-installed one isn't seen).
            if "Failed to register with host portal" in msg:
                logging.debug("Qt portal: %s", msg)
            elif mode in (0, 1, 2):  # QtDebugMsg=0, QtInfoMsg=4, QtWarningMsg=1, QtCriticalMsg=2
                logging.warning("Qt[%s]: %s", mode, msg)
        qInstallMessageHandler(qt_message_handler)
    except Exception:
        pass


def _setup_logging() -> None:
    paths.ensure_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(paths.LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="plasma-guard",
                                description="Modern ClamAV frontend for KDE Plasma.")
    p.add_argument("--version", action="store_true", help="Print version and exit.")
    p.add_argument("--scheduled-scan", action="store_true",
                   help="Headless: run a scheduled scan and write a report, then exit.")
    p.add_argument("--scan", metavar="PATH", help="Start a GUI scan of PATH.")
    p.add_argument("--update", action="store_true", help="Run a database update, then exit.")
    p.add_argument("--diagnose", action="store_true",
                   help="Print a diagnostic report and exit.")
    p.add_argument("--minimized", action="store_true",
                   help="Start minimized to the system tray.")
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Headless modes
# ---------------------------------------------------------------------------


def _headless_update(updater: FreshclamUpdater) -> int:
    logging.info("Headless update starting")
    result = updater.update()
    logging.info("Update result: %s (rc=%s)", result.message, result.exit_code)
    return 0 if result.success else 1


def _headless_scan(scanner: ClamAVScanner, settings, targets: list[str]) -> int:
    """Run scans over the given targets and save a report. Returns exit code."""
    from .config import ScanSettings
    logging.info("Headless scheduled scan starting; targets=%s", targets)

    final_targets: list[ScanTarget] = []
    for t in targets:
        if t == "HOME":
            final_targets.extend(default_targets())
        elif t.startswith("USB:"):
            label = t[4:]
            for usb in _list_mounts():
                if label in usb.path:
                    final_targets.append(usb)
                    break
        else:
            p = Path(t).expanduser()
            if p.exists():
                final_targets.append(ScanTarget(str(p), p.name))
    if not final_targets:
        final_targets = default_targets()

    overall_threats = 0
    for tgt in final_targets:
        logging.info("Scanning %s", tgt.path)
        result = scanner.scan(
            target=tgt,
            options={
                "scan_archives": settings.scan_archives,
                "scan_mail": settings.scan_mail,
                "heuristic_alerts": settings.heuristic_alerts,
                "max_file_size_mb": settings.max_file_size_mb,
                "max_scan_time_s": settings.max_scan_time_s,
                "enable_logging": settings.enable_logging,
            },
        )
        try:
            reports.save_report(result)
        except Exception as exc:  # noqa: BLE001
            logging.error("save_report failed: %s", exc)
        if settings.auto_quarantine and result.threats:
            from . import quarantine
            for th in result.threats:
                quarantine.quarantine_file(
                    th.path, th.signature,
                    note="auto-quarantined by scheduled scan",
                    password=settings.quarantine_password,
                )
        overall_threats += len(result.threats)
        logging.info("  -> %s files, %s infected, %s errors, %s threats",
                     result.scanned_files, result.infected_files,
                     result.errors, len(result.threats))

    if overall_threats and settings.show_notifications:
        notifications.notify("Plasma Guard — scheduled scan",
                             f"{overall_threats} threat(s) found.",
                             "dialog-warning")
    return 0 if overall_threats == 0 else 1


def _list_mounts():
    from .scanner import detect_usb_mounts
    return detect_usb_mounts()


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------


def _run_gui(args: argparse.Namespace) -> int:
    _install_global_exception_hook()

    # Set app metadata BEFORE QApplication is created so the portal
    # registration uses the correct desktop file.  Without this KDE
    # logs: "Failed to register with host portal - Could not register
    # app ID: App info not found for '<binary-name>'"
    import os
    os.environ["DESKTOP_APP_ID"] = "plasma-guard"
    QApplication.setDesktopFileName("plasma-guard")
    QApplication.setApplicationName(__app_name__)

    # Install the .desktop file if missing so the portal can find it.
    paths.ensure_desktop_file()

    # KDE Plasma / Wayland note: the default icon theme lookup should
    # already work. Force the style only as a last resort.
    app = QApplication.instance() or QApplication(sys.argv)
    QApplication.setApplicationDisplayName(__app_name__)
    QApplication.setApplicationVersion(__version__)
    QApplication.setOrganizationName("Plasma Guard")

    # Load stylesheet
    from .ui import style
    app.setStyleSheet(style.QSS)

    # Set app icon globally
    icon = _load_app_icon()
    app.setWindowIcon(icon)

    # Models
    settings_manager = SettingsManager()
    scanner = ClamAVScanner()
    updater = FreshclamUpdater()

    # Engine missing warning
    if not scanner.is_installed():
        QTimer.singleShot(500, lambda: _warn_engine_missing(scanner))

    # Tray icon is opt-in. Only create when the user explicitly enables it.
    # Creating-and-hiding a tray icon on every launch causes DBus churn that
    # can confuse KDE's system tray daemon and disrupt other tray apps.
    tray = None
    if settings_manager.settings.enable_tray_icon:
        try:
            tray = TrayController()
            tray.show()
        except Exception as exc:
            log.warning("Could not create tray icon: %s", exc)
            tray = None

    # Window
    window = MainWindow(scanner, updater, settings_manager, tray)
    if not args.minimized and not settings_manager.settings.start_minimized_to_tray:
        window.show()
    else:
        # Hidden; user opens from tray
        pass

    # Optionally kick off a scan from CLI
    if args.scan:
        target = ScanTarget(args.scan, Path(args.scan).name)
        QTimer.singleShot(200, lambda: window._start_scan_path(target.path, target.label))

    return app.exec()


def _warn_engine_missing(scanner: ClamAVScanner) -> None:
    QMessageBox.warning(
        None,
        "ClamAV not found",
        "Plasma Guard could not find the `clamscan` binary.\n\n"
        "Install it with:\n\n"
        "    sudo dnf install clamav clamav-update\n\n"
        "Then re-open Plasma Guard.",
    )


def _load_app_icon() -> QIcon:
    for name in ("icon.svg", "icon-128.png", "icon-64.png", "icon-48.png",
                 "icon-32.png", "icon.png"):
        p = paths.asset_path(name)
        if p.exists():
            return QIcon(str(p))
    return QIcon.fromTheme("security-high")


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if args.version:
        print(f"{__app_name__} {__version__}")
        return 0

    if args.diagnose:
        from . import diagnose
        return diagnose.main()

    _setup_logging()
    paths.ensure_dirs()
    logging.info("PlasmaGuard %s starting", __version__)

    # Headless modes
    if args.update:
        updater = FreshclamUpdater()
        return _headless_update(updater)

    if args.scheduled_scan:
        sm = SettingsManager()
        return _headless_scan(ClamAVScanner(), sm.settings, sm.settings.schedule_targets)

    return _run_gui(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
