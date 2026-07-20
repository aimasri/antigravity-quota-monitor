# Antigravity Status Bar Monitor

A lightweight, native system tray / status bar application for Linux (and compatible desktop environments) that monitors and displays your Google Antigravity AI model quotas in real-time.

Designed for developers migrating from the Antigravity IDE to the standalone CLI/agent workflow, providing the same real-time visibility directly in the OS panel.

## Features

- **Concentric Ring & Bar Visualization:**
  - **Left Concentric Rings:**
    - **Outer Ring:** Shows remaining quota percentage for **Gemini Flash**.
    - **Inner Ring:** Shows remaining quota percentage for **Gemini Pro**.
    - **Center Dot:** Shows remaining quota status for **Claude / GPT**.
  - **Right Vertical Bar:** Shows remaining weekly **Prompt Credits** quota.
- **Interactive Menu:** Click the icon to view detailed model breakdowns, weekly prompt/flow credits, and exact reset countdowns (e.g., "Resets in 3h 54m").
- **Hover Tooltip:** Quick readout of percentages and weekly credits when hovering.
- **Zero Config:** Automatically detects the running `language_server` process and queries it locally. No Google login credentials or API keys required.
- **Auto-polling:** Automatically refreshes the data every 60 seconds (or manually via "Refresh Now" in the menu).

## Requirements

- Python 3.x
- `PyQt5` or `PyQt6` (automatically detected)

Install requirements on Debian/Ubuntu:
```bash
sudo apt install python3-pyqt5
# OR
pip3 install PyQt5
```

## Installation & Autostart

1. Make the script executable:
   ```bash
   chmod +x antigravity-indicator.py
   ```

2. Run the application:
   ```bash
   python3 antigravity-indicator.py
   ```

3. **Configure Autostart (GNOME/KDE/XFCE):**
   To have the monitor start automatically when you log in, copy or symlink the application to your XDG Autostart directory:
   ```bash
   mkdir -p ~/.config/autostart
   cat <<EOF > ~/.config/autostart/antigravity-indicator.desktop
   [Desktop Entry]
   Type=Application
   Exec=python3 $(pwd)/antigravity-indicator.py
   Hidden=false
   NoDisplay=false
   X-GNOME-Autostart-enabled=true
   Name=Antigravity Quota Monitor
   Comment=Real-time Antigravity model quota monitor in the system tray
   Icon=utilities-system-monitor
   Categories=Utility;Development;
   EOF
   ```

## License

This project is licensed under the [MIT License](LICENSE).
