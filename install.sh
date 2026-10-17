#!/usr/bin/env bash
# ==============================================================================
# Title:           install.sh
# Purpose:         Installs & Provisions Antigravity Quota Monitor v3.0 (Enterprise)
# Why This Design: Deploys modular Python package, registers executable launcher,
#                  provisions systemd user service (WantedBy=default.target) and
#                  wires Openbox autostart for resilient desktop session launch.
# Privilege:       Dual-Mode (Installs to ~/.local/ without root/sudo; supports /usr/local/ when run as root)
# Subsystems:      systemd (user session), X11, Openbox, Tint2, PyGObject/Cairo
# Idempotency:     Completely idempotent. Running repeatedly updates files in-place,
#                  reloads systemd user daemon, and restarts the service cleanly.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TARGET_USER="${SUDO_USER:-$USER}"
TARGET_HOME=$(getent passwd "$TARGET_USER" | cut -d: -f6 2>/dev/null || echo "$HOME")
[ -z "$TARGET_HOME" ] && TARGET_HOME="$HOME"

run_as_target() {
    if [ "$EUID" -eq 0 ] && [ -n "${SUDO_USER:-}" ] && [ "$TARGET_USER" != "root" ]; then
        sudo -u "$TARGET_USER" -H "$@"
    else
        "$@"
    fi
}

echo "=== [Antigravity Quota Monitor v3.0] Provisioning for user: $TARGET_USER ==="

# 1. Dependency Validation (GTK3 + Cairo via PyGObject)
if ! python3 -c "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk; import cairo" 2>/dev/null; then
    echo "Warning: PyGObject / GTK3 / Cairo bindings not detected."
    if [ "$EUID" -eq 0 ]; then
        echo "Installing required Debian packages..."
        apt-get update -qq
        apt-get install -y python3-gi python3-gi-cairo gir1.2-gtk-3.0
    else
        echo "Please ensure packages are installed: sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0"
        exit 1
    fi
fi

# 2. Determine target directories based on execution mode
if [ "$EUID" -eq 0 ] && [ -z "${SUDO_USER:-}" ]; then
    INSTALL_LIB_DIR="/usr/local/lib/antigravity-quota-monitor"
    INSTALL_BIN_DIR="/usr/local/bin"
else
    INSTALL_LIB_DIR="$TARGET_HOME/.local/lib/antigravity-quota-monitor"
    INSTALL_BIN_DIR="$TARGET_HOME/.local/bin"
fi

run_as_target mkdir -p "$INSTALL_LIB_DIR" "$INSTALL_BIN_DIR"

# Copy package files
run_as_target rm -rf "$INSTALL_LIB_DIR/antigravity_monitor"
run_as_target cp -r "$SCRIPT_DIR/antigravity_monitor" "$INSTALL_LIB_DIR/"
run_as_target install -m 755 "$SCRIPT_DIR/bin/antigravity-indicator" "$INSTALL_BIN_DIR/antigravity-indicator"

echo "✓ Deployed package to $INSTALL_LIB_DIR"
echo "✓ Installed executable to $INSTALL_BIN_DIR/antigravity-indicator"

# 3. Clean up legacy XDG autostart entry
run_as_target rm -f "$TARGET_HOME/.config/autostart/antigravity-indicator.desktop"

# 4. Provision systemd user service (default.target)
SYSTEMD_USER_DIR="$TARGET_HOME/.config/systemd/user"
run_as_target mkdir -p "$SYSTEMD_USER_DIR"
run_as_target cp "$SCRIPT_DIR/systemd/antigravity-quota-monitor.service" "$SYSTEMD_USER_DIR/antigravity-quota-monitor.service"

echo "✓ Installed systemd user service unit (default.target)"

# 5. Wire Openbox autostart integration for explicit session boot launch
OPENBOX_AUTOSTART="$TARGET_HOME/.config/openbox/autostart"
if [ -f "$OPENBOX_AUTOSTART" ]; then
    if ! grep -q "antigravity-quota-monitor.service" "$OPENBOX_AUTOSTART"; then
        echo "Wiring Openbox session startup into $OPENBOX_AUTOSTART..."
        run_as_target bash -c "cat << 'EOF' >> '$OPENBOX_AUTOSTART'

## Antigravity Quota Monitor System Tray Daemon
[ -f ~/.config/systemd/user/antigravity-quota-monitor.service ] && (sleep 3s && systemctl --user start antigravity-quota-monitor.service) &
EOF"
        echo "✓ Registered in Openbox autostart"
    else
        echo "✓ Openbox autostart already wired"
    fi
fi

# 6. Reload systemd user daemon and enable service
run_as_target systemctl --user daemon-reload 2>/dev/null || true
run_as_target systemctl --user disable antigravity-quota-monitor.service 2>/dev/null || true
run_as_target systemctl --user enable antigravity-quota-monitor.service 2>/dev/null || true

# Terminate any legacy or orphan instances
pkill -f "antigravity-indicator\.py" 2>/dev/null || true
pkill -f "python3.*antigravity-indicator" 2>/dev/null || true

if [ -n "${DISPLAY:-}" ]; then
    echo "Restarting antigravity-quota-monitor.service in graphical session..."
    run_as_target systemctl --user restart antigravity-quota-monitor.service 2>/dev/null || true
fi

echo "===================================================="
echo " Antigravity Quota Monitor v3.0 Provisioned Successfully! "
echo " Executable: $INSTALL_BIN_DIR/antigravity-indicator "
echo " Service:    systemctl --user status antigravity-quota-monitor.service "
echo "===================================================="
