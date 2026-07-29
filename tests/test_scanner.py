"""Tests for the ClamAV scanner parser.

We replace the actual `clamscan` binary with a shell script that emits a
realistic log, then verify the parser correctly extracts threats, counts,
and summary fields.
"""
from __future__ import annotations

import os
import sys
import stat
import tempfile
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plasma_guard.scanner import ClamAVScanner, ScanTarget, Threat


def _make_fake_clamscan(tmp: Path, output: str, exit_code: int) -> Path:
    p = tmp / "clamscan"
    p.write_text(
        f"#!/bin/sh\ncat <<'EOF'\n{output}\nEOF\nexit {exit_code}\n"
    )
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


def test_clean_scan() -> None:
    output = textwrap.dedent("""
        /tmp/file1.txt: OK
        /tmp/file2.txt: OK
        ----------- SCAN SUMMARY -----------
        Known viruses: 1
        Engine version: 1.4.0
        Scanned directories: 1
        Scanned files: 2
        Infected files: 0
        Data scanned: 0.01 MB
        Data read: 0.01 MB (ratio 1.00:1)
        Time: 0.012 sec (0 m 0 s)
    """).strip()
    with tempfile.TemporaryDirectory() as td:
        binary = _make_fake_clamscan(Path(td), output, exit_code=0)
        s = ClamAVScanner(binary=str(binary))
        result = s.scan(ScanTarget("/tmp", "tmp"))
        assert result.exit_code == 0
        assert result.scanned_files == 2
        assert result.infected_files == 0
        assert not result.threats
        print("OK test_clean_scan")


def test_infected_scan() -> None:
    output = textwrap.dedent("""
        /tmp/eicar.com: Win.Test.EICAR_HDB-1 FOUND
        /tmp/clean.txt: OK
        /tmp/phish.pdf: Heuristics.Phishing.Email.SpoofedDomain FOUND
        ----------- SCAN SUMMARY -----------
        Known viruses: 12345
        Engine version: 1.4.0
        Scanned directories: 1
        Scanned files: 3
        Infected files: 2
        Errors: 0
        Data scanned: 1.50 MB
        Data read: 0.50 MB (ratio 3.00:1)
        Time: 0.5 sec (0 m 0 s)
    """).strip()
    with tempfile.TemporaryDirectory() as td:
        binary = _make_fake_clamscan(Path(td), output, exit_code=1)
        s = ClamAVScanner(binary=str(binary))
        result = s.scan(ScanTarget("/tmp", "tmp"))
        assert result.exit_code == 1
        assert result.scanned_files == 3
        assert result.infected_files == 2
        assert len(result.threats) == 2
        assert result.threats[0].path == "/tmp/eicar.com"
        assert result.threats[0].signature == "Win.Test.EICAR_HDB-1"
        assert result.threats[1].signature == "Heuristics.Phishing.Email.SpoofedDomain"
        assert abs(result.data_scanned_mb - 1.5) < 0.001
        print("OK test_infected_scan")


def test_scan_with_errors() -> None:
    output = textwrap.dedent("""
        /tmp/locked.bin: Access denied
        /tmp/file.txt: OK
        ----------- SCAN SUMMARY -----------
        Scanned files: 2
        Infected files: 0
        Errors: 1
        Data scanned: 0.10 MB
        Time: 0.1 sec (0 m 0 s)
    """).strip()
    with tempfile.TemporaryDirectory() as td:
        binary = _make_fake_clamscan(Path(td), output, exit_code=2)
        s = ClamAVScanner(binary=str(binary))
        result = s.scan(ScanTarget("/tmp", "tmp"))
        assert result.exit_code == 2
        assert result.errors == 1
        print("OK test_scan_with_errors")


if __name__ == "__main__":
    test_clean_scan()
    test_infected_scan()
    test_scan_with_errors()
    print()
    print("All tests passed ✓")
