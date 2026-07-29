"""Scan report persistence.

Reports are stored as JSON in ``~/.local/share/plasma-guard/reports/`` so the
dashboard can show a "Recent scans" list and the user can browse history.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict
from pathlib import Path

from . import paths
from .scanner import ScanResult, Threat

log = logging.getLogger(__name__)


def _report_path(scan_id: str) -> Path:
    return paths.REPORTS_DIR / f"{scan_id}.json"


def _new_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.localtime())


def save_report(result: ScanResult, scan_id: str | None = None) -> str:
    """Persist a ScanResult. Returns the scan id used."""
    sid = scan_id or _new_id()
    payload = asdict(result)
    # Threats -> dicts (already dataclasses)
    payload["threats"] = [asdict(t) for t in result.threats]
    p = _report_path(sid)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2, sort_keys=True)
    os.replace(tmp, p)
    return sid


def list_reports(limit: int = 50) -> list[dict]:
    """Return summary metadata for the most recent reports."""
    out: list[dict] = []
    for p in sorted(paths.REPORTS_DIR.glob("*.json"), reverse=True):
        try:
            with p.open("r", encoding="utf-8") as fp:
                d = json.load(fp)
            out.append({
                "id": p.stem,
                "target": d.get("target", ""),
                "started_at": d.get("started_at", 0),
                "finished_at": d.get("finished_at", 0),
                "scanned_files": d.get("scanned_files", 0),
                "infected_files": d.get("infected_files", 0),
                "errors": d.get("errors", 0),
                "exit_code": d.get("exit_code", -1),
            })
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Bad report %s: %s", p, exc)
        if len(out) >= limit:
            break
    return out


def clear_reports() -> None:
    """Delete all scan reports."""
    for p in paths.REPORTS_DIR.glob("*.json"):
        try:
            p.unlink()
        except OSError as exc:
            log.warning("Could not remove %s: %s", p, exc)


def load_report(scan_id: str) -> dict | None:
    p = _report_path(scan_id)
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, json.JSONDecodeError) as exc:
        log.error("Could not load report %s: %s", p, exc)
        return None
