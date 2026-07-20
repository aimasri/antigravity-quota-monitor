#!/usr/bin/env bash

# Exit on error
set -e

echo "===================================================="
echo "    Installing Antigravity Status Bar Monitor       "
echo "===================================================="

# Check requirements
if ! python3 -c "import PyQt5" 2>/dev/null && ! python3 -c "import PyQt6" 2>/dev/null; then
    echo "Warning: PyQt5 or PyQt6 is not installed."
    echo "Please run: pip3 install PyQt5  or  sudo apt install python3-pyqt5"
    echo "Press Enter to continue anyway, or Ctrl+C to cancel."
    read -r
fi

# Create target directories
mkdir -p "$HOME/.local/bin"
mkdir -p "$HOME/.config/autostart"

# Copy binary script
echo "Copying script to $HOME/.local/bin/antigravity-indicator..."
cp "$(dirname "$0")/antigravity-indicator.py" "$HOME/.local/bin/antigravity-indicator"
chmod +x "$HOME/.local/bin/antigravity-indicator"

# Create autostart entry
echo "Creating autostart entry..."
cat <<EOF > "$HOME/.config/autostart/antigravity-indicator.desktop"
[Desktop Entry]
Type=Application
Exec=$HOME/.local/bin/antigravity-indicator
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name=Antigravity Quota Monitor
Comment=Real-time Antigravity model quota monitor in the system tray
Icon=utilities-system-monitor
Categories=Utility;Development;
EOF

echo "----------------------------------------------------"
echo "Installation complete!"
echo "You can now run 'antigravity-indicator' from your terminal."
echo "It has also been added to your startup applications."
echo "===================================================="
