from __future__ import annotations

from PySide6.QtGui import QIcon

from .paths import asset_path


def custom_icon(name: str) -> QIcon | None:
    for ext in ("svg", "png", "jpg"):
        p = asset_path(f"{name}.{ext}")
        if p.exists():
            return QIcon(str(p))
    return None


def icon(name: str) -> QIcon:
    return custom_icon(name) or QIcon.fromTheme(name)
