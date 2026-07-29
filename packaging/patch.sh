#!/usr/bin/env bash
# PlasmaGuard in-place patcher
#
# Re-runs the installer against the existing source tree. Use this if you
# already extracted plasma-guard to a folder and just want to update the
# installed code without re-downloading the zip.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"

bash "$REPO_ROOT/packaging/install.sh"
