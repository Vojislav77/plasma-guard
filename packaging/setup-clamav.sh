#!/usr/bin/env bash
# PlasmaGuard ClamAV system setup
#
# One-time setup. Creates the 'clamav' system user + group (these are NOT
# created automatically by the clamav package on Fedora 44), makes the
# database directory writable by the group, adds YOU to that group, and
# runs freshclam once to download the initial signature database.
#
# Re-runnable: safe to run multiple times.
set -euo pipefail

log()  { printf '\033[1;34m[setup]\033[0m %s\n' "$*"; }
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

pm_clamav_pkg() {
    case "$(detect_pm)" in
        dnf)    echo "clamav clamav-freshclam" ;;
        apt)    echo "clamav clamav-daemon freshclam" ;;
        pacman) echo "clamav" ;;
        zypper) echo "clamav" ;;
        *)      echo "clamav" ;;
    esac
}

[[ "$(uname -s)" == "Linux" ]] || fail "Linux only."

if ! have sudo; then
    fail "sudo is required for this script."
fi

# 1. Make sure ClamAV is installed
if ! have clamscan || ! have freshclam; then
    log "Installing ClamAV (needs sudo)..."
    pm_install $(pm_clamav_pkg) || fail "Could not install ClamAV"
fi

# 2. Create the clamav system group (idempotent)
if getent group clamav >/dev/null 2>&1; then
    log "Group 'clamav' already exists."
else
    log "Creating group 'clamav'..."
    sudo groupadd --system clamav
fi

# 3. Create the clamav system user (idempotent)
if id -u clamav >/dev/null 2>&1; then
    log "User 'clamav' already exists."
else
    log "Creating system user 'clamav'..."
    sudo useradd --system \
        --gid clamav \
        --home-dir /var/lib/clamav \
        --no-create-home \
        --shell /usr/sbin/nologin \
        --comment "ClamAV antivirus" \
        clamav
fi

# 4. Create the database directory and hand it to clamav:clamav
DB_DIR="/var/lib/clamav"
if [[ -d "$DB_DIR" ]]; then
    log "Database directory $DB_DIR exists."
else
    log "Creating $DB_DIR..."
    sudo mkdir -p "$DB_DIR"
fi
sudo chown -R clamav:clamav "$DB_DIR"
sudo chmod 2775 "$DB_DIR"   # group-writable, sticky group bit

# 5. Stop & disable the system freshclam service (if it exists and is on)
if have systemctl; then
    if systemctl is-enabled --quiet clamav-freshclam.service 2>/dev/null; then
        log "Disabling system 'clamav-freshclam.service' (PlasmaGuard will update)..."
        sudo systemctl disable --now clamav-freshclam.service || \
            warn "Could not disable clamav-freshclam.service"
    fi
    if systemctl is-active --quiet clamav-freshclam.service 2>/dev/null; then
        sudo systemctl stop clamav-freshclam.service || true
    fi
fi

# 6. Add YOU to the clamav group
USER_NAME="${SUDO_USER:-$USER}"
if id -nG "$USER_NAME" 2>/dev/null | tr ' ' '\n' | grep -qx clamav; then
    log "User '$USER_NAME' is already in the 'clamav' group."
else
    log "Adding user '$USER_NAME' to the 'clamav' group..."
    sudo usermod -aG clamav "$USER_NAME"
    warn "Group change won't take effect until you LOG OUT and back in."
fi

# 7. Download the initial virus database
log "Running freshclam to download the initial virus database..."
if sudo -u clamav freshclam 2>&1 | tail -20; then
    log "Initial database downloaded."
else
    warn "freshclam returned non-zero - the database may already be present or"
    warn "the mirrors may be temporarily unreachable. Try again with:"
    warn "    sudo -u clamav freshclam"
fi

# 8. SELinux context fix (Fedora only)
if have restorecon; then
    log "Restoring SELinux contexts on $DB_DIR..."
    sudo restorecon -R "$DB_DIR" 2>/dev/null || true
fi

# 9. Passwordless sudo for freshclam as clamav (for PlasmaGuard updater)
SUDOERS_FILE="/etc/sudoers.d/plasma-guard-freshclam"
if [[ ! -f "$SUDOERS_FILE" ]] || ! grep -q "^${USER_NAME} ALL=(clamav) NOPASSWD:" "$SUDOERS_FILE" 2>/dev/null; then
    log "Setting up passwordless sudo for freshclam as clamav..."
    echo "${USER_NAME} ALL=(clamav) NOPASSWD: /usr/bin/freshclam" | \
        sudo tee "$SUDOERS_FILE" >/dev/null
    sudo chmod 440 "$SUDOERS_FILE"
    log "Sudoers rule added."
fi

# 10. Verify
log "Verifying setup..."
DB_FILES=$(find "$DB_DIR" -maxdepth 1 \( -name '*.cvd' -o -name '*.cld' \) 2>/dev/null | wc -l)
if (( DB_FILES > 0 )); then
    log "Setup complete. $DB_FILES signature file(s) in $DB_DIR."
else
    warn "No signature files found in $DB_DIR. Run manually:"
    warn "    sudo -u clamav freshclam"
fi

cat <<EOF

\033[1;32m
  ╔════════════════════════════════════════════════════════╗
  ║   ClamAV setup complete.                                ║
  ╚════════════════════════════════════════════════════════╝
\033[0m

  Next: LOG OUT and log back in. Then:

      plasma-guard --diagnose    # should show all green
      plasma-guard               # launch the app
EOF
