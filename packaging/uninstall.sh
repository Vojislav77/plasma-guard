#!/usr/bin/env bash
# PlasmaGuard uninstaller - removes everything we installed
set -euo pipefail

log()  { printf '\033[1;34m[uninstall]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }

# --- 1. Remove systemd user timer -----------------------------------------
for f in "$HOME/.config/systemd/user/plasma-guard-scan.service" \
         "$HOME/.config/systemd/user/plasma-guard-scan.timer"; do
    if [[ -f "$f" ]]; then
        log "removing $f"
        rm -f "$f"
    fi
done
# Remove the timer symlink if it exists
rm -f "$HOME/.config/systemd/user/timers.target.wants/plasma-guard-scan.timer" 2>/dev/null || true

if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload 2>/dev/null || true
fi

# --- 2. Remove .desktop file ----------------------------------------------
for f in "$HOME/.local/share/applications/plasma-guard.desktop"; do
    if [[ -f "$f" ]]; then
        log "removing $f"
        rm -f "$f"
    fi
done
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi

# --- 3. Remove icons -------------------------------------------------------
for size in 16 22 32 48 64 128 256 512; do
    rm -f "$HOME/.local/share/icons/hicolor/${size}x${size}/apps/plasma-guard.png"
done
rm -f "$HOME/.local/share/icons/hicolor/scalable/apps/plasma-guard.svg"
rm -f "$HOME/.local/share/pixmaps/plasma-guard.png"

# Unregister from xdg-icon-resource
if command -v xdg-icon-resource >/dev/null 2>&1; then
    for size in 16 22 32 48 64 128 256 512; do
        xdg-icon-resource uninstall --context apps --size "$size" "plasma-guard" 2>/dev/null || true
    done
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
fi

# --- 4. Remove the Python package -----------------------------------------
log "Uninstalling Python package..."
python3 -m pip uninstall -y plasma-guard 2>/dev/null || warn "package not in pip"

# --- 5. Optionally purge user data ----------------------------------------
if [[ "${1:-}" == "--purge" ]]; then
    log "Purging user data..."
    rm -rf "$HOME/.local/share/plasma-guard" \
           "$HOME/.config/plasma-guard" \
           "$HOME/.cache/plasma-guard" \
           "$HOME/.local/state/plasma-guard"
fi

cat <<EOF

\033[1;32m
  PlasmaGuard uninstalled.
\033[0m

  Note: the 'clamav' system group/user (if you ran setup-clamav.sh)
  was NOT removed. If you want to remove them too:

      sudo userdel clamav
      sudo groupdel clamav

EOF
