#!/usr/bin/env bash
# PlasmaGuard icon fix
#
# Use this if the PlasmaGuard icon doesn't appear in the application menu
# or on the panel after installation. Safe to re-run.
#
# It does NOT rebuild the running Plasma service cache (that crashes
# other apps). Instead it refreshes the safe caches and touches the
# relevant directories so the next time you log in (or restart plasmashell)
# the new icon is picked up.
set -euo pipefail

log()  { printf '\033[1;34m[icons]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ICON_BASE="$HOME/.local/share/icons/hicolor"
PIXMAPS="$HOME/.local/share/pixmaps"
APPS_DIR="$HOME/.local/share/applications"

# 1. Make sure the icon files are present
log "Re-copying icons to user hicolor theme..."
for size in 16 22 32 48 64 128 256 512; do
    src="$REPO_ROOT/assets/icon-${size}.png"
    dst="$ICON_BASE/${size}x${size}/apps/plasma-guard.png"
    if [[ -f "$src" ]]; then
        mkdir -p "$(dirname "$dst")"
        cp -f "$src" "$dst"
    fi
done
if [[ -f "$REPO_ROOT/assets/icon.svg" ]]; then
    mkdir -p "$ICON_BASE/scalable/apps"
    cp -f "$REPO_ROOT/assets/icon.svg" "$ICON_BASE/scalable/apps/plasma-guard.svg"
fi
mkdir -p "$PIXMAPS"
[[ -f "$REPO_ROOT/assets/icon-256.png" ]] && \
    cp -f "$REPO_ROOT/assets/icon-256.png" "$PIXMAPS/plasma-guard.png"

# 2. Re-register with xdg-icon-resource (if available)
if have xdg-icon-resource; then
    for size in 16 22 32 48 64 128 256 512; do
        src="$REPO_ROOT/assets/icon-${size}.png"
        [[ -f "$src" ]] && \
            xdg-icon-resource install --context apps --size "$size" \
                "$src" plasma-guard 2>/dev/null || true
    done
fi

# 3. Refresh the safe caches (these don't touch the running session)
if have update-desktop-database; then
    log "Refreshing desktop database..."
    update-desktop-database "$APPS_DIR" 2>/dev/null || true
fi
if have gtk-update-icon-cache; then
    log "Refreshing GTK icon cache..."
    gtk-update-icon-cache -f -t "$ICON_BASE" 2>/dev/null || true
fi

# 4. Bump mtime on the watched dirs so Plasma notices them
touch "$ICON_BASE" "$APPS_DIR" 2>/dev/null || true

# 5. SELinux (Fedora)
if have restorecon; then
    restorecon -R "$ICON_BASE" 2>/dev/null || true
    restorecon -R "$PIXMAPS" 2>/dev/null || true
    [[ -f "$APPS_DIR/plasma-guard.desktop" ]] && \
        restorecon "$APPS_DIR/plasma-guard.desktop" 2>/dev/null || true
fi

# 6. Delete the stale Plasma service cache so the next login rebuilds it
# (this is the bit we removed from the installer - only do it on demand)
if [[ -d "$HOME/.cache" ]]; then
    log "Clearing stale Plasma service cache (will rebuild on next login)..."
    # Don't blow away the whole cache - only the ksycoca files
    rm -f "$HOME/.cache"/ksycoca* 2>/dev/null || true
fi

cat <<EOF

\033[1;32m
  Icons refreshed. Now do one of:
\033[0m

  a) Log out and back in (cleanest)
  b) Restart plasmashell in-place:
         systemctl --user restart plasma-plasmashell.service

EOF
