"""ClamAV scanner integration.

We shell out to the `clamscan` binary (shipped with the `clamav` package on
Fedora). Output is parsed line by line so we can stream progress to the UI.

clamscan exit codes (from clamdoc):
    0  - no virus found
    1  - virus(es) found
    2  - some error(s) occurred
"""
from __future__ import annotations

import dataclasses
import logging
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ScanTarget:
    """A file or directory to scan."""
    path: str
    label: str = ""           # UI label (e.g. "Home", "USB: KINGSTON")
    recursive: bool = True


@dataclass
class Threat:
    """An infected file reported by clamscan."""
    path: str
    signature: str

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.path}: {self.signature}"


@dataclass
class ScanResult:
    """Aggregated outcome of a scan run."""
    target: str
    started_at: float
    finished_at: float = 0.0
    scanned_files: int = 0
    infected_files: int = 0
    errors: int = 0
    data_scanned_mb: float = 0.0
    threats: list[Threat] = field(default_factory=list)
    error_lines: list[str] = field(default_factory=list)
    summary_lines: list[str] = field(default_factory=list)
    exit_code: int = -1

    @property
    def duration_s(self) -> float:
        if self.finished_at and self.started_at:
            return self.finished_at - self.started_at
        return 0.0

    @property
    def is_clean(self) -> bool:
        return self.exit_code == 0 and not self.threats


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


# Lines printed by clamscan look like:
#   /foo/bar/baz.exe: Win.Trojan.Something FOUND
#   /foo/bar/baz.txt: OK
#   /foo/bar/big.bin: OK
#   /foo/bar/bad.pdf: Heuristics.Phishing.Email.SpoofedDomain FOUND
#   ----------- SCAN SUMMARY -----------
#   Known viruses: 12345678
#   Engine version: 1.4.x
#   Scanned directories: 42
#   Scanned files: 1234
#   Infected files: 2
#   Data scanned: 56.78 MB
#   Data read: 45.67 MB (ratio 1.24:1)
#   Time: 12.345 sec (0 m 12 s)
_FOUND_RE = re.compile(r"^(?P<path>.+):\s+(?P<sig>.+?)\s+FOUND\s*$")
_OK_RE = re.compile(r"^(?P<path>.+):\s+(?P<sig>OK)\s*$")
_SUMMARY_HEAD = "----------- SCAN SUMMARY -----------"


class ClamAVScanner:
    """Thin wrapper around the clamscan CLI.

    Designed to be driven from a QThread via a callback. The callback is
    invoked from the worker thread - the UI is responsible for marshalling
    the events back to the main thread (Qt signals).
    """

    def __init__(
        self,
        binary: str = "clamscan",
        database_dir: Optional[str] = None,
    ) -> None:
        self.binary = binary
        self.database_dir = database_dir

    # ---- public API ------------------------------------------------------

    def is_installed(self) -> bool:
        return shutil.which(self.binary) is not None

    def version(self) -> str:
        if not self.is_installed():
            return "not installed"
        try:
            out = subprocess.run(
                [self.binary, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            return (out.stdout or out.stderr or "").strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"error: {exc}"

    def scan(
        self,
        target: ScanTarget,
        options: dict | None = None,
        on_progress: Optional[Callable[[str], None]] = None,
        on_threat: Optional[Callable[[Threat], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        cancel: Optional[Callable[[], bool]] = None,
    ) -> ScanResult:
        """Run a single scan.

        ``cancel`` is a callable returning True if the scan should abort.
        The process is sent SIGTERM then SIGKILL.
        """
        opts = options or {}
        cmd = self._build_command(target, opts)
        log.info("Running: %s", " ".join(cmd))

        result = ScanResult(target=target.path, started_at=time.time())
        emitter = on_log or (lambda m: None)
        emitter(f"$ {' '.join(cmd)}")

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            msg = f"clamscan binary not found: {self.binary}"
            log.error(msg)
            result.error_lines.append(msg)
            if on_error:
                on_error(msg)
            result.finished_at = time.time()
            result.exit_code = 127
            return result

        assert proc.stdout is not None
        # Tell the user up-front if the database is empty (super common on
        # fresh Fedora installs before freshclam has run).
        from pathlib import Path
        db_dir = Path(self.database_dir or "/var/lib/clamav")
        if db_dir.exists() and not any(db_dir.glob("*.cvd")) and not any(db_dir.glob("*.cld")):
            warn_msg = (f"WARNING: virus database at {db_dir} is empty. "
                        f"Click 'Update database' first, or run: sudo freshclam")
            emitter(warn_msg)
            if on_error:
                on_error(warn_msg)
        try:
            import select
            while True:
                # Cooperative cancellation — checked even when no output
                if cancel and cancel():
                    emitter("[scan] cancellation requested - terminating")
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    break

                readable, _, _ = select.select([proc.stdout], [], [], 0.5)
                if readable:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    self._consume_line(
                        line.rstrip("\n"),
                        result=result,
                        on_progress=on_progress,
                        on_threat=on_threat,
                        on_log=emitter,
                        on_error=on_error,
                    )
                elif proc.poll() is not None:
                    break
            proc.wait()
            result.exit_code = proc.returncode
        finally:
            if proc.poll() is None:
                proc.kill()

        result.finished_at = time.time()
        return result

    # ---- internals -------------------------------------------------------

    def _build_command(self, target: ScanTarget, opts: dict) -> list[str]:
        cmd: list[str] = [self.binary]

        if not target.recursive:
            cmd.append("--no-recursion")

        if opts.get("scan_archives", True):
            cmd.append("--scan-archive")
        else:
            cmd.append("--no-archive")

        if not opts.get("scan_mail", True):
            cmd.append("--no-mail")

        if opts.get("heuristic_alerts", True):
            cmd.append("--heuristic-alerts=yes")
        else:
            cmd.append("--heuristic-alerts=no")

        max_size = int(opts.get("max_file_size_mb", 0) or 0)
        if max_size > 0:
            cmd += ["--max-filesize", str(max_size)]
            cmd += ["--max-scansize", str(max_size)]

        max_time = int(opts.get("max_scan_time_s", 0) or 0)
        if max_time > 0:
            cmd += ["--timeout", str(max_time)]

        if opts.get("enable_logging", True):
            cmd.append("--log")
        else:
            cmd.append("--no-log")

        if self.database_dir:
            cmd += ["--database", self.database_dir]

        # Quiet mode - we'll parse the output ourselves.
        cmd.append("--infected")   # only print infected + OK lines
        cmd.append("-r") if target.recursive else cmd.append("--no-recursion")

        cmd.append(target.path)
        return cmd

    def _consume_line(
        self,
        line: str,
        result: ScanResult,
        on_progress: Optional[Callable[[str], None]],
        on_threat: Optional[Callable[[Threat], None]],
        on_log: Callable[[str], None],
        on_error: Optional[Callable[[str], None]],
    ) -> None:
        if not line:
            return

        # Threat line
        m = _FOUND_RE.match(line)
        if m:
            t = Threat(path=m.group("path"), signature=m.group("sig"))
            result.threats.append(t)
            if on_threat:
                on_threat(t)
            on_log(line)
            return

        # OK line - track as a progress event (sparse to avoid flooding)
        m = _OK_RE.match(line)
        if m:
            result.scanned_files += 1
            if on_progress and result.scanned_files % 50 == 0:
                on_progress(m.group("path"))
            return

        # Summary line
        if line.startswith(_SUMMARY_HEAD) or "SCAN SUMMARY" in line:
            result.summary_lines.append(line)
            on_log(line)
            return

        # Parsed summary fields
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if key == "Infected files":
                try:
                    result.infected_files = int(val.split()[0])
                except (ValueError, IndexError):
                    pass
            elif key == "Scanned files":
                try:
                    result.scanned_files = int(val.split()[0])
                except (ValueError, IndexError):
                    pass
            elif key == "Data scanned":
                # e.g. "56.78 MB"
                try:
                    num, unit = val.split()[:2]
                    mb = float(num)
                    if unit.upper() == "GB":
                        mb *= 1024
                    elif unit.upper() == "KB":
                        mb /= 1024
                    result.data_scanned_mb = mb
                except (ValueError, IndexError):
                    pass
            elif key == "Errors":
                try:
                    result.errors = int(val.split()[0])
                except (ValueError, IndexError):
                    pass

        # Error lines
        if line.lower().startswith("error") or "can't" in line.lower():
            result.error_lines.append(line)
            if on_error:
                on_error(line)
            on_log(line)
            return

        # Default: forward to log
        on_log(line)


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def default_targets(home: Path | None = None) -> list[ScanTarget]:
    """Return a list of common quick-scan targets."""
    home = home or Path.home()
    targets: list[ScanTarget] = []

    home_dir = home
    if home_dir.exists():
        targets.append(ScanTarget(str(home_dir), "Home"))

    downloads = home_dir / "Downloads"
    if downloads.exists():
        targets.append(ScanTarget(str(downloads), "Downloads"))

    documents = home_dir / "Documents"
    if documents.exists():
        targets.append(ScanTarget(str(documents), "Documents"))

    return targets


def detect_usb_mounts() -> list[ScanTarget]:
    """Return a list of currently mounted removable drives (Linux).

    Uses /proc/mounts to find filesystems mounted under /media or /run/media
    with a non-zero size, and excludes obvious system mounts.
    """
    out: list[ScanTarget] = []
    mounts = Path("/proc/mounts")
    if not mounts.exists():
        return out

    seen: set[str] = set()
    try:
        for raw in mounts.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = raw.split()
            if len(parts) < 3:
                continue
            mp = parts[1]
            fstype = parts[2]
            if fstype not in ("vfat", "exfat", "ntfs", "ntfs3", "ext4", "btrfs", "f2fs", "xfs"):
                continue
            if not (mp.startswith("/media/") or mp.startswith("/run/media/") or mp.startswith("/mnt/")):
                continue
            if mp in seen:
                continue
            seen.add(mp)
            label = Path(mp).name or mp
            out.append(ScanTarget(mp, f"USB: {label}"))
    except OSError as exc:
        log.warning("Could not read /proc/mounts: %s", exc)
    return out
