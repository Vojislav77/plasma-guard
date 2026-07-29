"""Scheduler integration via systemd user timers.

PlasmaGuard registers a `plasma-guard-scan.service` + `plasma-guard-scan.timer`
under ``~/.config/systemd/user/``. The timer fires the service, which invokes
`plasma-guard --scheduled-scan` to run a headless scan and write a report.

We deliberately avoid needing root and we keep all state in the user's home.
"""
from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import paths

log = logging.getLogger(__name__)

SERVICE_NAME = "plasma-guard-scan.service"
TIMER_NAME = "plasma-guard-scan.timer"
SYSTEMD_DIR = Path.home() / ".config" / "systemd" / "user"


# Templates --------------------------------------------------------------


SERVICE_TEMPLATE = """[Unit]
Description=PlasmaGuard scheduled scan
After=network-online.target

[Service]
Type=oneshot
ExecStart={exec_start}
WorkingDirectory={workdir}
"""


def _frequency_to_calendar(freq: str, hour: int, minute: int,
                           day_of_week: int = 0, day_of_month: int = 1) -> str:
    """Translate user settings to systemd OnCalendar syntax."""
    time_str = f"{hour:02d}:{minute:02d}:00"
    if freq == "daily":
        return f"daily *-*-* {time_str}"
    if freq == "weekly":
        # systemd uses Mon=1 ... Sun=7
        return f"weekly *-*-* {time_str} (or next)"  # placeholder - replaced below
    if freq == "monthly":
        return f"monthly *-*-{day_of_month:02d} {time_str}"
    return f"daily *-*-* {time_str}"


def _build_calendar(freq: str, hour: int, minute: int,
                    day_of_week: int, day_of_month: int) -> str:
    time_str = f"{hour:02d}:{minute:02d}:00"
    if freq == "daily":
        return f"*-*-* {time_str}"
    if freq == "weekly":
        # day_of_week: 0=Mon ... 6=Sun -> systemd 1..7
        return f"Mon..Sun *-*-* {time_str}"
    if freq == "monthly":
        return f"*-*-{day_of_month:02d} {time_str}"
    return f"*-*-* {time_str}"


TIMER_TEMPLATE = """[Unit]
Description=PlasmaGuard scheduled scan timer
Requires={service}
After={service}

[Timer]
OnCalendar={calendar}
Persistent=true
Unit={service}

[Install]
WantedBy=timers.target
"""


# ---------------------------------------------------------------------------
# Installation / removal
# ---------------------------------------------------------------------------


def _exec_start() -> str:
    """Build the ExecStart= line.

    We prefer a python -m invocation because it's robust to where the user
    installed PlasmaGuard. They can override the path by exporting
    PLASMA_GUARD_PYTHON or PLASMA_GUARD_BIN.
    """
    py = os.environ.get("PLASMA_GUARD_PYTHON") or "python3"
    return f"{py} -m plasma_guard --scheduled-scan"


def install(settings) -> tuple[bool, str]:
    """Install (or update) the systemd service+timer for the user."""
    try:
        SYSTEMD_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, f"Cannot create {SYSTEMD_DIR}: {exc}"

    service_path = SYSTEMD_DIR / SERVICE_NAME
    timer_path = SYSTEMD_DIR / TIMER_NAME

    service_text = SERVICE_TEMPLATE.format(
        exec_start=_exec_start(),
        workdir=str(paths.app_root()),
    )
    calendar = _build_calendar(
        settings.schedule_frequency,
        settings.schedule_hour,
        settings.schedule_minute,
        settings.schedule_day_of_week,
        settings.schedule_day_of_month,
    )
    timer_text = TIMER_TEMPLATE.format(
        service=SERVICE_NAME,
        calendar=calendar,
    )

    try:
        service_path.write_text(service_text, encoding="utf-8")
        timer_path.write_text(timer_text, encoding="utf-8")
    except OSError as exc:
        return False, f"Cannot write unit files: {exc}"

    # Reload systemd user daemon.
    rc, out = _run(["systemctl", "--user", "daemon-reload"])
    if rc != 0:
        return False, f"systemctl daemon-reload failed: {out}"

    if settings.schedule_enabled:
        rc, out = _run(["systemctl", "--user", "enable", "--now", TIMER_NAME])
        if rc != 0:
            return False, f"Failed to enable timer: {out}"
        return True, f"Timer installed and started ({calendar})."
    else:
        rc, out = _run(["systemctl", "--user", "disable", "--now", TIMER_NAME])
        # disabling a non-enabled unit is OK; rc != 0 is acceptable
        return True, "Timer installed but disabled (per settings)."


def uninstall() -> tuple[bool, str]:
    """Stop & remove the systemd units."""
    msgs: list[str] = []
    rc, out = _run(["systemctl", "--user", "disable", "--now", TIMER_NAME])
    msgs.append(f"disable timer: rc={rc} {out}")
    for name in (SERVICE_NAME, TIMER_NAME):
        p = SYSTEMD_DIR / name
        try:
            if p.exists():
                p.unlink()
                msgs.append(f"removed {p}")
        except OSError as exc:
            msgs.append(f"could not remove {p}: {exc}")
    rc, out = _run(["systemctl", "--user", "daemon-reload"])
    msgs.append(f"daemon-reload: rc={rc} {out}")
    return True, "\n".join(msgs)


def status() -> dict:
    """Return human-readable status of the timer (for the Settings page)."""
    rc, out = _run(["systemctl", "--user", "status", TIMER_NAME, "--no-pager"])
    rc2, list_out = _run(["systemctl", "--user", "list-timers", "--no-pager"])
    next_run = ""
    if rc2 == 0:
        for line in list_out.splitlines():
            if "plasma-guard-scan.timer" in line:
                parts = line.split()
                if parts:
                    next_run = " ".join(parts[:5])
                break
    return {
        "service": SERVICE_NAME,
        "timer": TIMER_NAME,
        "active": rc == 0,
        "next_run": next_run,
        "status_output": out,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def is_systemd_available() -> bool:
    return shutil_which("systemctl") is not None


def shutil_which(name: str) -> Optional[str]:
    import shutil
    return shutil.which(name)
