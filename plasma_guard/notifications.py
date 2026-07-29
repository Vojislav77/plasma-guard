"""KDE notification helper.

Priority: ``kdialog --passivepopup`` (auto-dismisses after timeout, native KDE),
then ``notify-send`` (libnotify). Both support a hard timeout.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import time
from typing import Optional

log = logging.getLogger(__name__)


def _which(*names: str) -> Optional[str]:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def notify(title: str, message: str, icon: str = "dialog-information",
           timeout_ms: int = 4000) -> bool:
    """Show a desktop notification. Returns True if a backend was used.

    We always pass a hard timeout so the notification auto-dismisses -
    KDE notifications otherwise stay open indefinitely.
    """
    kdialog = _which("kdialog")
    if kdialog:
        # kdialog --passivepopup always auto-dismisses after the timeout.
        # We use 'sleep' to enforce a hard kill in case the user's
        # notification settings override --passivepopup.
        try:
            proc = subprocess.Popen(
                [kdialog, "--passivepopup",
                 f"<b>{title}</b><br>{message}",
                 str(max(1, timeout_ms // 1000))],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            # kdialog sometimes holds the popup open if the timeout is
            # overridden - we kill it after timeout + 1s to be safe.
            timeout_s = max(1, timeout_ms // 1000) + 1
            try:
                proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                proc.terminate()
            return True
        except OSError as exc:
            log.warning("kdialog notify failed: %s", exc)

    notify_send = _which("notify-send")
    if notify_send:
        try:
            subprocess.Popen(
                [notify_send, "-a", "Plasma Guard", "-i", icon,
                 "-t", str(timeout_ms), title, message],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True
        except OSError as exc:
            log.warning("notify-send failed: %s", exc)

    log.info("notification (no backend): %s - %s", title, message)
    return False
