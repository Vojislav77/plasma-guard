"""PlasmaGuard diagnostics.

Runs a comprehensive set of checks to help the user (and us) understand
why scans or updates might not be working. Exposed via the ``--diagnose``
CLI flag and from the Settings page.
"""
from __future__ import annotations

import getpass
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import paths
from .scanner import ClamAVScanner
from .updater import FreshclamUpdater, database_info


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    fix_hint: str = ""

    def line(self) -> str:
        mark = "✓" if self.ok else "✗"
        s = f"  {mark} {self.name}: {self.detail}"
        if not self.ok and self.fix_hint:
            s += f"\n      → {self.fix_hint}"
        return s


def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def _has_group(user: str, group: str) -> bool:
    try:
        out = subprocess.check_output(["id", "-nG", user], text=True, timeout=5)
        return group in out.split()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def _readable(p: Path) -> bool:
    try:
        return os.access(p, os.R_OK)
    except OSError:
        return False


def _writable(p: Path) -> bool:
    try:
        return os.access(p, os.W_OK)
    except OSError:
        return False


def run_all() -> list[CheckResult]:
    """Run every diagnostic check and return the list."""
    results: list[CheckResult] = []
    user = getpass.getuser()

    # 1. ClamAV installed
    sc = ClamAVScanner()
    uc = FreshclamUpdater()
    if sc.is_installed():
        results.append(CheckResult("clamscan binary", True, sc.version()))
    else:
        results.append(CheckResult(
            "clamscan binary", False, "clamscan not found on PATH",
            "Install: sudo dnf install clamav"))

    if uc.is_installed():
        results.append(CheckResult("freshclam binary", True,
                                   f"{uc.binary} ({shutil.which(uc.binary)})"))
    else:
        results.append(CheckResult(
            "freshclam binary", False, "freshclam not found on PATH",
            "Install: sudo dnf install clamav-update"))

    # freshclam.conf exists and is usable
    fc_conf = Path("/etc/freshclam.conf")
    if fc_conf.exists():
        if _readable(fc_conf):
            content = fc_conf.read_text(encoding="utf-8", errors="ignore")
            if any(line.strip().startswith("Example") for line in content.splitlines()):
                results.append(CheckResult(
                    "freshclam.conf", False,
                    "/etc/freshclam.conf still has the 'Example' directive active",
                    "Edit the file and comment out the 'Example' line:\n"
                    "  sudo sed -i '/^Example/s/^/#/' /etc/freshclam.conf"))
            else:
                results.append(CheckResult(
                    "freshclam.conf", True, "/etc/freshclam.conf is readable"))
        else:
            results.append(CheckResult(
                "freshclam.conf", False, "/etc/freshclam.conf is not readable",
                "Run: sudo chmod 644 /etc/freshclam.conf"))
    else:
        results.append(CheckResult(
            "freshclam.conf", False, "/etc/freshclam.conf does not exist",
            "Install: sudo dnf install clamav-update"))

    # 2. ClamAV group membership
    if _has_group(user, "clamav"):
        results.append(CheckResult("'clamav' group membership", True,
                                   f"user '{user}' is in the clamav group"))
    else:
        results.append(CheckResult(
            "'clamav' group membership", False,
            f"user '{user}' is NOT in the clamav group",
            "Run: sudo usermod -aG clamav $USER   (then LOG OUT and back in)"))

    # 3. Database dir readable
    db_path = Path("/var/lib/clamav")
    if db_path.exists():
        if _readable(db_path):
            results.append(CheckResult("Database dir readable", True, str(db_path)))
        else:
            results.append(CheckResult(
                "Database dir readable", False,
                f"{db_path} is not readable by {user}",
                "Add yourself to the clamav group (see above) or chmod a+rx the dir"))

        if _writable(db_path):
            results.append(CheckResult("Database dir writable", True, str(db_path)))
        else:
            results.append(CheckResult(
                "Database dir writable", False,
                f"{db_path} is not writable by {user}",
                "Add yourself to the clamav group (see above)"))
    else:
        results.append(CheckResult(
            "Database directory exists", False, f"{db_path} does not exist",
            "Run: sudo mkdir -p /var/lib/clamav && sudo chown clamav:clamav /var/lib/clamav"))

    # 4. Database has content
    info = database_info(str(db_path))
    if info.get("exists") == "yes":
        cvd_files = list(db_path.glob("*.cvd")) + list(db_path.glob("*.cld"))
        if cvd_files:
            age = float(info.get("age_hours", 0))
            results.append(CheckResult(
                "Database has signatures", True,
                f"{len(cvd_files)} signature files, newest is {info.get('newest_file')} "
                f"({age:.1f} hours old)"))
        else:
            results.append(CheckResult(
                "Database has signatures", False,
                "No .cvd / .cld files in /var/lib/clamav/",
                "Click 'Update database' in the app, or run: sudo freshclam"))
    else:
        results.append(CheckResult(
            "Database has signatures", False,
            "Database directory is empty / doesn't exist",
            "Click 'Update database' in the app, or run: sudo freshclam"))

    # 5. System freshclam service
    rc, out = _run(["systemctl", "is-active", "clamav-freshclam.service"])
    if rc == 0:
        results.append(CheckResult(
            "System freshclam service", False,
            "clamav-freshclam.service is ACTIVE - this conflicts with the app's update",
            "Run: sudo systemctl disable --now clamav-freshclam.service"))
    else:
        results.append(CheckResult(
            "System freshclam service", True, "not active (good)"))

    # 6. PlasmaGuard user timer
    rc, out = _run(["systemctl", "--user", "is-active", "plasma-guard-scan.timer"])
    if rc == 0:
        results.append(CheckResult(
            "PlasmaGuard scheduled scan timer", True, "active"))
    else:
        results.append(CheckResult(
            "PlasmaGuard scheduled scan timer", False, "not active",
            "Open Settings and click 'Apply / refresh systemd timer'"))

    # 7. PlasmaGuard app dirs
    for d in (paths.APP_DATA_DIR, paths.APP_CONFIG_DIR, paths.QUARANTINE_DIR,
              paths.REPORTS_DIR, paths.APP_LOG_DIR):
        if d.exists():
            results.append(CheckResult(f"Dir: {d.parent.name}/{d.name}",
                                       True, str(d)))
        else:
            results.append(CheckResult(
                f"Dir: {d.parent.name}/{d.name}", False, "missing",
                "It will be created on first launch"))

    # 8. SELinux (informational)
    if Path("/sys/fs/selinux").exists():
        rc, out = _run(["getenforce"])
        results.append(CheckResult(
            "SELinux mode", True, f"{out} (informational only)"))

    # 9. Network reachability for ClamAV mirrors
    try:
        from . import updater
        net = updater.test_network()
        for host, status in net.items():
            ok = "fail" not in status.lower()
            results.append(CheckResult(
                f"Network: {host}", ok, status,
                "Check your internet connection / proxy / firewall" if not ok else ""))
    except Exception as exc:
        results.append(CheckResult(
            "Network test", False, str(exc)))

    return results


def format_report(results: Optional[list[CheckResult]] = None) -> str:
    if results is None:
        results = run_all()
    lines = ["PlasmaGuard diagnostic report", "=" * 60]
    n_ok = sum(1 for r in results if r.ok)
    n_bad = len(results) - n_ok
    for r in results:
        lines.append(r.line())
    lines.append("=" * 60)
    lines.append(f"{n_ok}/{len(results)} checks passed")
    if n_bad:
        lines.append("")
        lines.append("Some checks failed. See fix hints above ↑")
    return "\n".join(lines)


def main() -> int:
    print(format_report())
    n_bad = sum(1 for r in run_all() if not r.ok)
    return 0 if n_bad == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
