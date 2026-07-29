"""Persistent JSON-backed configuration & settings.

Two layers:

* `Config`  - the engine's view: paths, log files, defaults from paths.py.
* `Settings` - the user's view: scan options, schedule, behaviour.

Both are stored under the XDG config dir as plain JSON so users can inspect
and back them up.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import paths

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scan settings (user-tweakable)
# ---------------------------------------------------------------------------


@dataclass
class ScanSettings:
    """Persistent user settings for scanning behaviour."""

    # Default locations exposed as quick-scan buttons.
    scan_home: bool = True
    scan_downloads: bool = True
    scan_documents: bool = True
    scan_usb_on_mount: bool = True

    # clamscan flags
    recursive: bool = True
    scan_archives: bool = True
    scan_mail: bool = True
    heuristic_alerts: bool = True
    max_file_size_mb: int = 100  # 0 = unlimited
    max_scan_time_s: int = 0     # 0 = unlimited
    enable_logging: bool = True

    # Quarantine behaviour
    auto_quarantine: bool = True
    quarantine_password: str = "infected"

    # Scheduler
    schedule_enabled: bool = False
    schedule_frequency: str = "weekly"  # daily | weekly | monthly
    schedule_day_of_week: int = 0       # 0=Monday ... 6=Sunday
    schedule_day_of_month: int = 1
    schedule_hour: int = 3              # 0-23
    schedule_minute: int = 0            # 0-59
    schedule_targets: list[str] = field(default_factory=lambda: ["HOME"])

    # UI
    start_minimized_to_tray: bool = False
    close_to_tray: bool = False          # OFF by default - the X button exits
    show_notifications: bool = True
    enable_tray_icon: bool = False       # OFF by default - opt-in to avoid crashes
    enable_drop_zone: bool = True        # Drop target in sidebar

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScanSettings":
        # Filter unknown keys (forward-compat) and missing ones get defaults.
        valid = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in data.items() if k in valid}
        return cls(**clean)


# ---------------------------------------------------------------------------
# Loader / saver
# ---------------------------------------------------------------------------


def _read_json(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not read %s: %s", path, exc)
        return {}


def _write_json(path: Path | str, data: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except OSError as exc:
        log.error("Could not write %s: %s", path, exc)


class SettingsManager:
    """Manages persistent user settings."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.SETTINGS_FILE
        self._settings = self._load()

    # ---- public ----------------------------------------------------------

    @property
    def settings(self) -> ScanSettings:
        return self._settings

    def save(self) -> None:
        _write_json(self.path, self._settings.to_dict())
        log.info("Settings saved to %s", self.path)

    def update(self, **kwargs: Any) -> None:
        """Update one or more settings in-place and persist."""
        for key, value in kwargs.items():
            if not hasattr(self._settings, key):
                log.warning("Ignoring unknown setting: %s", key)
                continue
            setattr(self._settings, key, value)
        self.save()

    def reset(self) -> None:
        self._settings = ScanSettings()
        self.save()

    # ---- internal --------------------------------------------------------

    def _load(self) -> ScanSettings:
        data = _read_json(self.path)
        if not data:
            return ScanSettings()
        return ScanSettings.from_dict(data)
