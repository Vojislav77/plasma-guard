"""freshclam wrapper for virus database updates.

Runs the `freshclam` binary and streams its output to the UI. Includes a
hard timeout so the UI can never hang forever.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)

# Hard cap on how long a single freshclam can run. Default 5 minutes;
# most updates complete in <60s, but the first run after a fresh install
# downloads ~150MB and can take longer.
DEFAULT_TIMEOUT_S = 300


@dataclass
class UpdateResult:
    started_at: float
    finished_at: float = 0.0
    success: bool = False
    message: str = ""
    log_lines: list[str] = field(default_factory=list)
    exit_code: int = -1
    timed_out: bool = False

    @property
    def duration_s(self) -> float:
        if self.finished_at and self.started_at:
            return self.finished_at - self.started_at
        return 0.0


_VERSION_RE = re.compile(r"ClamAV (?P<ver>[\d\.]+)/(\d+)")


class FreshclamUpdater:
    """Wrapper around freshclam with timeout and cancellation."""

    def __init__(self, binary: str = "freshclam",
                 config_file: Optional[str] = None,
                 timeout_s: int = DEFAULT_TIMEOUT_S) -> None:
        self.binary = binary
        self.config_file = config_file
        self.timeout_s = timeout_s

    def is_installed(self) -> bool:
        return shutil.which(self.binary) is not None

    def database_dir(self) -> Optional[str]:
        """Return the configured database directory by parsing freshclam.conf
        and clamd.conf if present. Falls back to the standard Fedora path.
        """
        candidates = [
            Path("/etc/clamd.d/scan.conf"),
            Path("/etc/clamd.conf"),
            Path("/etc/freshclam.conf"),
        ]
        for conf in candidates:
            if not conf.exists():
                continue
            try:
                for line in conf.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if line.startswith("DatabaseDirectory"):
                        _, _, val = line.partition(" ")
                        val = val.strip()
                        if val:
                            return val
            except OSError:
                continue
        return "/var/lib/clamav"

    def update(
        self,
        on_log: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
        cancel: Optional[Callable[[], bool]] = None,
    ) -> UpdateResult:
        if not self.is_installed():
            msg = f"{self.binary} not found. Install the 'clamav' package."
            log.error(msg)
            return UpdateResult(
                started_at=time.time(), finished_at=time.time(),
                success=False, message=msg, exit_code=127,
            )

        cmd = [self.binary, "--verbose"]
        if self.config_file:
            cmd += ["--config-file", self.config_file]

        # On Fedora with SELinux, the database dir is labelled
        # antivirus_db_t and only writable by the clamav user.
        # If the current user can't write to it, try sudo -u clamav.
        db_dir = self.database_dir() or "/var/lib/clamav"
        if os.geteuid() != 0 and not os.access(db_dir, os.W_OK):
            sudo_bin = shutil.which("sudo")
            if sudo_bin:
                import pwd
                try:
                    pwd.getpwnam("clamav")
                    cmd = [sudo_bin, "-u", "clamav"] + cmd
                except (KeyError, OSError):
                    pass

        emitter = on_log or (lambda m: None)
        emitter(f"$ {' '.join(cmd)}")
        log.info("Running: %s", " ".join(cmd))

        result = UpdateResult(started_at=time.time())
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
        except FileNotFoundError as exc:
            result.message = str(exc)
            result.finished_at = time.time()
            result.exit_code = 127
            return result

        # We watch the process in a small loop so we can apply a hard
        # timeout AND let the user cancel.
        deadline = time.time() + self.timeout_s
        last_output = time.time()
        try:
            assert proc.stdout is not None
            import select
            while True:
                # Cooperative cancellation
                if cancel and cancel():
                    emitter("[updater] cancellation requested")
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    result.message = "Cancelled by user."
                    break

                # Timeout check
                if time.time() > deadline:
                    emitter(f"[updater] HARD TIMEOUT after {self.timeout_s}s — killing freshclam")
                    log.warning("freshclam timed out after %ss", self.timeout_s)
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    result.timed_out = True
                    result.message = (
                        f"freshclam timed out after {self.timeout_s} seconds.\n\n"
                        f"This usually means the ClamAV database mirrors are\n"
                        f"unreachable from your network. Check:\n"
                        f"  - Internet connection (try:  ping -c 3 database.clamav.net)\n"
                        f"  - Proxy settings (http_proxy / https_proxy)\n"
                        f"  - Firewall rules\n"
                        f"  - DNS resolution (try:  nslookup database.clamav.net)"
                    )
                    break

                # No-output watchdog: if freshclam hasn't produced ANY
                # output for 60s, assume it's stuck.
                if time.time() - last_output > 60:
                    emitter("[updater] no output for 60s — likely stuck on network/DNS")
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    result.timed_out = True
                    result.message = (
                        f"freshclam produced no output for 60s.\n\n"
                        f"Likely cause: cannot reach the ClamAV database mirrors.\n"
                        f"Try from a terminal:\n"
                        f"  ping -c 3 database.clamav.net\n"
                        f"  curl -I https://database.clamav.net"
                    )
                    break

                # Read whatever lines are available without blocking
                line = proc.stdout.readline()
                if line:
                    last_output = time.time()
                    line = line.rstrip("\n")
                    result.log_lines.append(line)
                    emitter(line)
                    if on_progress:
                        on_progress(line)
                else:
                    # No line; check if process exited
                    if proc.poll() is not None:
                        break
                    # Brief sleep to avoid busy-loop
                    time.sleep(0.1)

            if not result.timed_out and result.message != "Cancelled by user.":
                result.exit_code = proc.returncode
                result.success = proc.returncode in (0, 1)
                if proc.returncode == 0:
                    result.message = "Database updated successfully."
                elif proc.returncode == 1:
                    result.message = "Database is already up to date."
                else:
                    output = "\n".join(result.log_lines).lower()
                    if "permission denied" in output or "can't open" in output:
                        result.message = (
                            "freshclam cannot write to the database directory.\n\n"
                            "Make sure you are in the 'clamav' group:\n"
                            "  bash packaging/setup-clamav.sh\n\n"
                            "Then log out and back in for group changes to take effect."
                        )
                    elif "connection" in output and (
                        "refused" in output or "timeout" in output or "reset" in output
                    ):
                        result.message = (
                            "freshclam cannot reach the ClamAV mirrors.\n\n"
                            "Check your internet connection, firewall, or proxy settings."
                        )
                    elif "already locked" in output or "could not lock" in output:
                        result.message = (
                            "The database is locked by another process.\n\n"
                            "Run: sudo systemctl disable --now clamav-freshclam.service"
                        )
                    else:
                        result.message = (
                            f"freshclam exited with code {proc.returncode}.\n\n"
                            f"Run from a terminal to see details:\n"
                            f"  freshclam --verbose"
                        )
        finally:
            if proc.poll() is None:
                proc.kill()
        result.finished_at = time.time()
        return result


def database_info(db_dir: str | None = None) -> dict[str, str]:
    """Return simple info about the local database files (version, age)."""
    db_dir = Path(db_dir or "/var/lib/clamav")
    info: dict[str, str] = {"dir": str(db_dir), "exists": "no"}
    if not db_dir.exists():
        return info
    info["exists"] = "yes"

    # Look for the main.cvd / daily.cvd / bytecode.cvd
    files = sorted(db_dir.glob("*.cvd")) + sorted(db_dir.glob("*.cld"))
    if files:
        newest = max(files, key=lambda p: p.stat().st_mtime)
        mtime = newest.stat().st_mtime
        info["newest_file"] = newest.name
        age_h = (time.time() - mtime) / 3600
        info["age_hours"] = f"{age_h:.1f}"
    total = sum(p.stat().st_size for p in db_dir.glob("*") if p.is_file())
    info["total_size_mb"] = f"{total / (1024 * 1024):.1f}"
    return info


def test_network() -> dict[str, str]:
    """Test DNS resolution for ClamAV database mirrors.

    We only check DNS here. The ClamAV CDN blocks plain HTTP/HTTPS
    requests that don't use the freshclam protocol, so an HTTP check
    would always produce a false "fail". DNS resolution is the reliable
    indicator for network-level connectivity.

    Returns a dict of {name: status}.
    """
    import socket

    results: dict[str, str] = {}
    for host in ("database.clamav.net", "db.local.clamav.net"):
        try:
            socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            results[host] = "DNS ok"
        except (socket.gaierror, OSError) as exc:
            results[host] = f"DNS fail: {exc}"
    return results
