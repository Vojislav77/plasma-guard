"""Tests for the quarantine module."""
from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plasma_guard import paths, quarantine


def test_quarantine_and_restore() -> None:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        # Override paths
        paths.QUARANTINE_DIR = td_path / "q"
        paths.QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
        # Source file
        src = td_path / "evil.txt"
        src.write_text("infected content")
        # Quarantine
        e = quarantine.quarantine_file(str(src), "Test.Sig", password="pwd")
        assert e is not None
        assert not src.exists(), "original should be moved"
        archive = paths.QUARANTINE_DIR / f"{e.id}.zip"
        assert archive.exists()
        # Manifest
        entries = quarantine.list_entries()
        assert len(entries) == 1
        assert entries[0].id == e.id
        # Restore
        out = quarantine.restore_entry(e.id, target_dir=str(td_path / "out"),
                                       password="pwd")
        assert out is not None
        restored = Path(out) / "evil.txt"
        assert restored.exists()
        assert restored.read_text() == "infected content"
        # Manifest should be empty now
        assert quarantine.list_entries() == []
        # Stats
        stats = quarantine.quarantine_stats()
        assert stats["count"] == 0
        print("OK test_quarantine_and_restore")


def test_quarantine_delete() -> None:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        paths.QUARANTINE_DIR = td_path / "q"
        paths.QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
        src = td_path / "bad.txt"
        src.write_text("bad")
        e = quarantine.quarantine_file(str(src), "Sig")
        assert e is not None
        assert quarantine.delete_entry(e.id) is True
        assert quarantine.list_entries() == []
        print("OK test_quarantine_delete")


def test_clear_quarantine() -> None:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        paths.QUARANTINE_DIR = td_path / "q"
        paths.QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
        for i in range(3):
            src = td_path / f"bad{i}.txt"
            src.write_text(f"bad {i}")
            quarantine.quarantine_file(str(src), f"Sig{i}")
        assert len(quarantine.list_entries()) == 3
        n = quarantine.clear_quarantine()
        assert n == 3
        assert quarantine.list_entries() == []
        print("OK test_clear_quarantine")


def test_is_quarantinable() -> None:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        # Existing file
        f = td_path / "x.txt"
        f.write_text("x")
        assert quarantine.is_quarantinable(str(f))
        # Non-existing
        assert not quarantine.is_quarantinable(str(td_path / "missing.txt"))
        # Directory
        assert not quarantine.is_quarantinable(str(td_path))
        print("OK test_is_quarantinable")


if __name__ == "__main__":
    test_quarantine_and_restore()
    test_quarantine_delete()
    test_clear_quarantine()
    test_is_quarantinable()
    print()
    print("All tests passed ✓")
