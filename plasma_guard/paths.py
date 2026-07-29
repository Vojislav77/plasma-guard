"""Path and filesystem layout for PlasmaGuard.

All paths follow XDG Base Directory spec where applicable.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _xdg_path(env: str, default: str) -> Path:
    raw = os.environ.get(env, "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(default).expanduser()


# User-level XDG directories
XDG_DATA_HOME = _xdg_path("XDG_DATA_HOME", "~/.local/share")
XDG_CONFIG_HOME = _xdg_path("XDG_CONFIG_HOME", "~/.config")
XDG_CACHE_HOME = _xdg_path("XDG_CACHE_HOME", "~/.cache")
XDG_STATE_HOME = _xdg_path("XDG_STATE_HOME", "~/.local/state")

APP_ID = "plasma-guard"
APP_NAME = "PlasmaGuard"

# PlasmaGuard directories
APP_DATA_DIR = XDG_DATA_HOME / APP_ID
APP_CONFIG_DIR = XDG_CONFIG_HOME / APP_ID
APP_CACHE_DIR = XDG_CACHE_HOME / APP_ID
APP_STATE_DIR = XDG_STATE_HOME / APP_ID
APP_LOG_DIR = APP_STATE_DIR / "logs"

# Sub-directories
QUARANTINE_DIR = APP_DATA_DIR / "quarantine"
REPORTS_DIR = APP_DATA_DIR / "reports"
SIGNATURES_DIR = APP_DATA_DIR / "signatures"

# File paths
CONFIG_FILE = APP_CONFIG_DIR / "config.json"
LOG_FILE = APP_LOG_DIR / "plasma-guard.log"
LAST_SCAN_FILE = APP_STATE_DIR / "last_scan.json"
SETTINGS_FILE = APP_CONFIG_DIR / "settings.json"


def ensure_dirs() -> None:
    """Create all required directories."""
    for d in (APP_DATA_DIR, APP_CONFIG_DIR, APP_CACHE_DIR, APP_STATE_DIR,
              APP_LOG_DIR, QUARANTINE_DIR, REPORTS_DIR, SIGNATURES_DIR):
        d.mkdir(parents=True, exist_ok=True)


def is_frozen() -> bool:
    """Return True if running from a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def app_root() -> Path:
    """Return the root directory of the PlasmaGuard install.

    Inside a PyInstaller bundle this is the directory containing the binary.
    Otherwise it's the repo root (parent of the `plasma_guard` package).
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def asset_path(name: str) -> Path:
    """Return the path to a packaged asset (icon, desktop file, etc.)."""
    return app_root() / "assets" / name


def _desktop_file_target() -> Path:
    return Path.home() / ".local" / "share" / "applications" / f"{APP_ID}.desktop"


def ensure_desktop_file() -> None:
    """Install the desktop file so the app shows up in the application menu.

    Uses the ``Path=`` key to set the working directory, so the app can be
    moved without breaking — the next launch from the terminal will re-write
    the desktop file with the new location.
    """
    target = _desktop_file_target()
    src = app_root() / "packaging" / f"{APP_ID}.desktop"
    if not src.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    content = src.read_text()
    if is_frozen():
        content = content.replace("Exec=plasma-guard",
                                  f"Exec={sys.executable}")
    else:
        content = content.replace("Exec=plasma-guard",
                                  f"Exec=python3 -m plasma_guard")
        if "Path=" not in content:
            # Insert Path= right after Exec= so the working directory is set.
            content = content.replace(
                "Exec=python3 -m plasma_guard",
                f"Exec=python3 -m plasma_guard\nPath={app_root()}",
            )
    icon_pkg = asset_path("icon.svg")
    if not icon_pkg.exists():
        icon_pkg = asset_path("icon-256.png")
    if icon_pkg.exists():
        content = content.replace("@ICON_PATH@", str(icon_pkg.resolve()))
    # Always re-write so paths stay correct after a move.
    target.write_text(content)
