#!/usr/bin/env bash
# Plasma Guard installer
#
# ULTRA-MINIMAL: only installs the Python package, the .desktop file,
# and the icon. It does NOT:
#   - touch the systemd timer (you can enable it from the app's Settings)
#   - touch any system files
#   - rebuild the running Plasma service cache
#   - enable or disable any system services
#
# Re-runnable. Safe to run multiple times.
set -euo pipefail

APP_ID="plasma-guard"
APP_DISPLAY="Plasma Guard"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"

# --- helpers ---------------------------------------------------------------

log()  { printf '\033[1;34m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

# --- package manager detection ---------------------------------------------

detect_pm() {
    if have dnf;   then echo "dnf"
    elif have apt; then echo "apt"
    elif have pacman; then echo "pacman"
    elif have zypper; then echo "zypper"
    else echo "unknown"
    fi
}

pm_install() {
    case "$(detect_pm)" in
        dnf)    sudo dnf install -y "$@" ;;
        apt)    sudo apt install -y "$@"  ;;
        pacman) sudo pacman -S --noconfirm "$@" ;;
        zypper) sudo zypper install -y "$@" ;;
        *)      fail "No supported package manager found. Install manually: $*" ;;
    esac
}

pm_python_pkg() {
    case "$(detect_pm)" in
        dnf)    echo "python3" ;;
        apt)    echo "python3 python3-pip" ;;
        pacman) echo "python python-pip" ;;
        zypper) echo "python3 python3-pip" ;;
        *)      echo "python3" ;;
    esac
}

pm_clamav_pkg() {
    case "$(detect_pm)" in
        dnf)    echo "clamav clamav-update" ;;
        apt)    echo "clamav clamav-daemon freshclam" ;;
        pacman) echo "clamav" ;;
        zypper) echo "clamav" ;;
        *)      echo "clamav" ;;
    esac
}

# --- preflight -------------------------------------------------------------

[[ "$(uname -s)" == "Linux" ]] || fail "This installer targets Linux."

if ! have python3; then
    fail "python3 is not installed. Install it with: sudo $(detect_pm) install $(pm_python_pkg)"
fi

PY_MIN=$(python3 -c 'import sys; print("%d%d" % (sys.version_info.major, sys.version_info.minor))')
if (( PY_MIN < 310 )); then
    fail "Plasma Guard needs Python 3.10+ (you have $(python3 -V))."
fi

if ! have clamscan; then
    warn "clamscan not found. You need ClamAV to scan."
    warn "Install with:  sudo $(detect_pm) install $(pm_clamav_pkg)"
fi

# --- Python deps + package -------------------------------------------------

log "Installing PySide6 (Python deps)..."
python3 -m pip install --user --upgrade pip >/dev/null
python3 -m pip install --user --upgrade "PySide6>=6.6,<7"

log "Installing $APP_DISPLAY package (aggressive cache-bust)..."
# Purge any old version so we definitely get the new one
python3 -m pip uninstall -y plasma-guard 2>/dev/null || true
rm -rf "$REPO_ROOT/build" "$REPO_ROOT/dist" 2>/dev/null || true
rm -rf "$REPO_ROOT"/*.egg-info 2>/dev/null || true
rm -rf "$HOME/.cache/pip/wheels"/*plasma-guard* 2>/dev/null || true
# Reinstall with --no-cache-dir to bypass any pip wheel cache
python3 -m pip install --user --upgrade --force-reinstall --no-cache-dir "$REPO_ROOT"

# Verify the version that actually got installed
INSTALLED_VER=$(python3 -c "import plasma_guard; print(plasma_guard.__version__)" 2>/dev/null || echo "UNKNOWN")
log "Installed version: $INSTALLED_VER"

# --- Icons -----------------------------------------------------------------

ICON_BASE="$HOME/.local/share/icons/hicolor"
PIXMAPS="$HOME/.local/share/pixmaps"
APPS_DIR="$HOME/.local/share/applications"

mkdir -p "$ICON_BASE/scalable/apps" "$PIXMAPS" "$APPS_DIR"

# Copy SVG to the hicolor theme (the standard XDG location)
cp -f "$REPO_ROOT/assets/icon.svg" "$ICON_BASE/scalable/apps/${APP_ID}.svg"
# Copy a PNG to pixmaps as an absolute fallback
cp -f "$REPO_ROOT/assets/icon-256.png" "$PIXMAPS/${APP_ID}.png"
# Copy all PNG sizes into hicolor
for size in 16 22 32 48 64 128 256 512; do
    src="$REPO_ROOT/assets/icon-${size}.png"
    dst_dir="$ICON_BASE/${size}x${size}/apps"
    mkdir -p "$dst_dir"
    [[ -f "$src" ]] && cp -f "$src" "$dst_dir/${APP_ID}.png"
done

# Pick the icon path we want in the .desktop file (absolute - always works)
ICON_PATH="$PIXMAPS/${APP_ID}.png"

# Register with xdg-icon-resource (helps some DEs)
if have xdg-icon-resource; then
    for size in 16 22 32 48 64 128 256 512; do
        src="$REPO_ROOT/assets/icon-${size}.png"
        [[ -f "$src" ]] && \
            xdg-icon-resource install --context apps --size "$size" "$src" "$APP_ID" 2>/dev/null || true
    done
fi

# SELinux context fix (Fedora)
if have restorecon; then
    restorecon -R "$ICON_BASE" 2>/dev/null || true
    restorecon -R "$PIXMAPS" 2>/dev/null || true
fi

# --- .desktop file (with absolute Icon= path) ------------------------------

cp -f "$REPO_ROOT/packaging/plasma-guard.desktop" "$APPS_DIR/${APP_ID}.desktop"
# Inject the absolute icon path
sed -i "s|@ICON_PATH@|${ICON_PATH}|g" "$APPS_DIR/${APP_ID}.desktop"
chmod 0644 "$APPS_DIR/${APP_ID}.desktop"

if have restorecon; then
    restorecon "$APPS_DIR/${APP_ID}.desktop" 2>/dev/null || true
fi

# Refresh the SAFE caches (these don't touch the running session)
if have update-desktop-database; then
    update-desktop-database "$APPS_DIR" 2>/dev/null || true
fi
if have gtk-update-icon-cache; then
    gtk-update-icon-cache -f -t "$ICON_BASE" 2>/dev/null || true
fi

# We deliberately do NOT install/enable the systemd timer here.
# The user can enable it from Settings -> Scheduled scans.

# --- final -----------------------------------------------------------------

cat <<EOF

\033[1;32m
  ╔════════════════════════════════════════════════════════╗
  ║   $APP_DISPLAY installed.                               ║
  ╚════════════════════════════════════════════════════════╝
\033[0m

  NEXT STEPS (in order):

  1) Set up ClamAV (one-time, needs sudo):
         bash $REPO_ROOT/packaging/setup-clamav.sh

  2) LOG OUT and back in (clamav group + Plasma icon cache).

  3) Launch:
         plasma-guard

  Other commands:
      plasma-guard --diagnose
      plasma-guard --update
      plasma-guard --scan /path/to/dir

  To uninstall:
      bash $REPO_ROOT/packaging/uninstall.sh

EOF
