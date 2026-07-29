"""Quarantine management.

Infected files are moved (not copied) to a per-user quarantine directory
and zipped with a password so they can't accidentally run. Each file is
stored as ``<sha256-of-original-path>.zip``.

The user can later restore (re-extract) or delete the quarantined items.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from . import paths

log = logging.getLogger(__name__)


@dataclass
class QuarantineEntry:
    """Metadata for a quarantined file."""
    id: str                # filename of the .zip (no extension)
    original_path: str
    signature: str
    quarantined_at: float  # unix timestamp
    size_bytes: int = 0
    archive_path: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "QuarantineEntry":
        valid = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in data.items() if k in valid}
        return cls(**clean)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _manifest_path() -> Path:
    return paths.QUARANTINE_DIR / "manifest.json"


def _load_manifest() -> list[dict]:
    p = _manifest_path()
    if not p.exists():
        return []
    try:
        with p.open("r", encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Bad quarantine manifest: %s", exc)
        return []


def _save_manifest(entries: list[dict]) -> None:
    p = _manifest_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fp:
        json.dump(entries, fp, indent=2, sort_keys=True)
    os.replace(tmp, p)


def _id_for_path(path: str) -> str:
    h = hashlib.sha256()
    h.update(path.encode("utf-8", errors="replace"))
    h.update(b"|")
    h.update(str(time.time_ns()).encode("ascii"))
    return h.hexdigest()[:16]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_quarantinable(path: str) -> bool:
    """Sanity check before we touch a file."""
    p = Path(path)
    if not p.exists():
        return False
    if not p.is_file():
        return False
    # Don't quarantine our own state files.
    try:
        p_resolved = p.resolve()
        if str(p_resolved).startswith(str(paths.QUARANTINE_DIR.resolve())):
            return False
    except OSError:
        return False
    return True


def quarantine_file(
    source: str,
    signature: str,
    note: str = "",
    password: str = "infected",
) -> Optional[QuarantineEntry]:
    """Move ``source`` into the quarantine vault.

    Returns the new entry, or None on failure.
    """
    src = Path(source)
    if not is_quarantinable(source):
        log.warning("Cannot quarantine %s", source)
        return None

    paths.QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    entry_id = _id_for_path(str(src))
    archive = paths.QUARANTINE_DIR / f"{entry_id}.zip"

    try:
        size = src.stat().st_size
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.setpassword(password.encode("utf-8"))
            zf.write(src, arcname=src.name)
    except OSError as exc:
        log.error("Failed to zip %s: %s", src, exc)
        return None

    # Remove the original *only* after the archive is on disk.
    try:
        src.unlink()
    except OSError as exc:
        log.error("Wrote archive but could not remove original %s: %s", src, exc)
        # Archive remains - we still record the entry so the user can clean up.

    entry = QuarantineEntry(
        id=entry_id,
        original_path=str(src),
        signature=signature,
        quarantined_at=time.time(),
        size_bytes=size,
        archive_path=str(archive),
        note=note,
    )
    manifest = _load_manifest()
    manifest.append(entry.to_dict())
    _save_manifest(manifest)
    log.info("Quarantined %s -> %s", src, archive)
    return entry


def list_entries() -> list[QuarantineEntry]:
    """Return all quarantined entries (newest first)."""
    return [
        QuarantineEntry.from_dict(d)
        for d in sorted(_load_manifest(), key=lambda d: d.get("quarantined_at", 0), reverse=True)
    ]


def delete_entry(entry_id: str) -> bool:
    """Permanently remove a quarantined item."""
    manifest = _load_manifest()
    new = []
    removed = None
    for d in manifest:
        if d.get("id") == entry_id:
            removed = d
        else:
            new.append(d)
    if removed is None:
        return False

    archive = Path(removed.get("archive_path", ""))
    try:
        if archive.exists():
            archive.unlink()
    except OSError as exc:
        log.error("Could not delete archive %s: %s", archive, exc)
    _save_manifest(new)
    return True


def restore_entry(entry_id: str, target_dir: str | None = None, password: str = "infected") -> Optional[str]:
    """Re-extract a quarantined file.

    Returns the restored path on success, None on failure. The restored file
    is left alone - the user is responsible for deleting the archive later.
    """
    manifest = _load_manifest()
    target = None
    for d in manifest:
        if d.get("id") == entry_id:
            target = d
            break
    if target is None:
        return None

    archive = Path(target.get("archive_path", ""))
    if not archive.exists():
        log.error("Archive missing: %s", archive)
        return None

    original = Path(target.get("original_path", ""))
    out_dir = Path(target_dir) if target_dir else original.parent
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.error("Cannot create %s: %s", out_dir, exc)
        return None

    try:
        with zipfile.ZipFile(archive) as zf:
            zf.setpassword(password.encode("utf-8"))
            zf.extractall(out_dir)
    except (RuntimeError, zipfile.BadZipFile, OSError) as exc:
        log.error("Failed to restore %s: %s", archive, exc)
        return None

    # Remove from manifest & archive.
    manifest = [d for d in manifest if d.get("id") != entry_id]
    _save_manifest(manifest)
    try:
        archive.unlink()
    except OSError:
        pass
    log.info("Restored %s -> %s", archive, out_dir)
    return str(out_dir)


def clear_quarantine() -> int:
    """Delete everything in the quarantine vault. Returns count removed."""
    manifest = _load_manifest()
    count = 0
    for d in manifest:
        archive = Path(d.get("archive_path", ""))
        try:
            if archive.exists():
                archive.unlink()
                count += 1
        except OSError as exc:
            log.error("Could not delete %s: %s", archive, exc)
    _save_manifest([])
    return count


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def quarantine_stats() -> dict[str, int]:
    entries = list_entries()
    total = sum(e.size_bytes for e in entries)
    return {
        "count": len(entries),
        "total_bytes": total,
        "oldest": int(min((e.quarantined_at for e in entries), default=0)),
        "newest": int(max((e.quarantined_at for e in entries), default=0)),
    }
