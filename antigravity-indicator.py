#!/usr/bin/env python3
import sys
import os
import re
import json
import urllib.request
import ssl
from datetime import datetime

try:
    from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QAction
    from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush
    from PyQt5.QtCore import QTimer, QRectF, Qt
    PYQT_VERSION = 5
except ImportError:
    try:
        from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
        from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush, QAction
        from PyQt6.QtCore import QTimer, QRectF, Qt
        PYQT_VERSION = 6
    except ImportError:
        print("Error: PyQt5 or PyQt6 is required to run the Antigravity Status Bar Monitor.")
        sys.exit(1)

def get_qcolor(fraction):
    if fraction > 0.5:
        return QColor(102, 255, 102)     # Green
    elif fraction > 0.2:
        return QColor(255, 215, 0)       # Yellow
    elif fraction > 0.0:
        return QColor(255, 140, 0)       # Orange
    else:
        return QColor(255, 68, 68)        # Red

def fmt_reset(reset_str):
    try:
        from datetime import timezone
        reset_time = datetime.strptime(reset_str.replace('Z', ''), '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = reset_time - now
        total_seconds = diff.total_seconds()
        if total_seconds <= 0:
            return "Ready"
        mins = int(total_seconds / 60)
        if mins < 60:
            return f"{mins}m"
        hours = mins // 60
        mins_rem = mins % 60
        return f"{hours}h {mins_rem}m"
    except Exception:
        return reset_str

class AntigravityQuotaApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        self.tray = QSystemTrayIcon()
        self.menu = QMenu()
        self.tray.setContextMenu(self.menu)

        self.timer = QTimer()
        self.timer.timeout.connect(self.poll_and_update)
        
        # Start immediately
        print("Initializing Antigravity Status Bar Monitor...")
        self.poll_and_update()
        self.timer.start(60000) # every 60 seconds
        
        self.tray.show()
        print("Tray icon display initialized.")

    def get_pid_listening_ports(self, pid):
        inodes = set()
        try:
            for fd in os.listdir(f"/proc/{pid}/fd"):
                try:
                    link = os.readlink(f"/proc/{pid}/fd/{fd}")
                    m = re.match(r'socket:\[(\d+)\]', link)
                    if m:
                        inodes.add(m.group(1))
                except Exception:
                    continue
        except Exception:
            pass

        ports = []
        for proto in ('tcp', 'tcp6'):
            try:
                with open(f"/proc/net/{proto}", "r") as f:
                    lines = f.readlines()
                for line in lines[1:]:
                    parts = line.strip().split()
                    if not parts:
                        continue
                    inode = parts[9]
                    state = parts[3]
                    if state == '0A' and inode in inodes:
                        local_addr = parts[1]
                        ip_hex, port_hex = local_addr.split(':')
                        port = int(port_hex, 16)
                        if port not in ports:
                            ports.append(port)
            except Exception:
                pass
        return ports

    def find_language_servers(self):
        matches = []
        for pid_str in os.listdir('/proc'):
            if not pid_str.isdigit():
                continue
            try:
                with open(f"/proc/{pid_str}/cmdline", "rb") as f:
                    content = f.read()
                args = [arg.decode('utf-8', errors='ignore') for arg in content.split(b'\x00') if arg]
                if not args:
                    continue
                cmd_name = args[0]
                if 'language_server' in cmd_name:
                    csrf_token = None
                    app_data_dir = None
                    for i, arg in enumerate(args):
                        if arg.startswith('--csrf_token='):
                            csrf_token = arg.split('=', 1)[1]
                        elif arg == '--csrf_token' and i + 1 < len(args):
                            csrf_token = args[i + 1]
                        elif arg.startswith('--app_data_dir='):
                            app_data_dir = arg.split('=', 1)[1]
                        elif arg == '--app_data_dir' and i + 1 < len(args):
                            app_data_dir = args[i + 1]
                    if csrf_token:
                        matches.append({
                            'pid': int(pid_str),
                            'csrf_token': csrf_token,
                            'app_data_dir': app_data_dir,
                            'cmd': cmd_name
                        })
            except Exception:
                continue
        return matches

    def query_user_status(self, port, token):
        url = f"https://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/GetUserStatus"
        body = { "metadata": { "ideName": "antigravity", "extensionName": "antigravity", "locale": "en" } }
        payload = json.dumps(body).encode('utf-8')
        
        headers = {
            'Content-Type': 'application/json',
            'Connect-Protocol-Version': '1',
            'X-Codeium-Csrf-Token': token
        }
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        req = urllib.request.Request(url, data=payload, headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=3) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception:
            return None

    def make_concentric_icon(self, fraction_flash, fraction_pro, fraction_claude):
        pixmap = QPixmap(22, 22)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        bg_pen = QPen(QColor(80, 80, 80, 70), 2)
        painter.setPen(bg_pen)
        painter.drawArc(QRectF(2, 2, 18, 18), 0, 360 * 16)
        painter.drawArc(QRectF(5, 5, 12, 12), 0, 360 * 16)
        
        color_flash = get_qcolor(fraction_flash)
        pen_flash = QPen(color_flash, 2)
        painter.setPen(pen_flash)
        painter.drawArc(QRectF(2, 2, 18, 18), 90 * 16, int(-fraction_flash * 360 * 16))
        
        color_pro = get_qcolor(fraction_pro)
        pen_pro = QPen(color_pro, 2)
        painter.setPen(pen_pro)
        painter.drawArc(QRectF(5, 5, 12, 12), 90 * 16, int(-fraction_pro * 360 * 16))
        
        color_claude = get_qcolor(fraction_claude)
        painter.setBrush(QBrush(color_claude))
        painter.setPen(Qt.NoPen if PYQT_VERSION == 5 else Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(9, 9, 4, 4))
        
        painter.end()
        return QIcon(pixmap)

    def poll_and_update(self):
        print("Polling Antigravity quota status...")
        servers = self.find_language_servers()
        if not servers:
            print("Error: No running language servers detected.")
            self.set_error_icon("No Server")
            return

        standalone_server = None
        for s in servers:
            if s['app_data_dir'] == 'antigravity':
                standalone_server = s
                break
        if not standalone_server:
            standalone_server = servers[0]

        pid = standalone_server['pid']
        token = standalone_server['csrf_token']
        print(f"Targeting server PID: {pid} (dir: {standalone_server['app_data_dir']})")
        
        ports = self.get_pid_listening_ports(pid)
        print(f"Server ports: {ports}")
        status = None
        for port in ports:
            print(f"Trying connection on port {port}...")
            status = self.query_user_status(port, token)
            if status:
                print(f"Successfully connected to port {port}!")
                break

        if not status:
            print("Error: Failed to fetch status from any port.")
            self.set_error_icon("Offline")
            return

        print("Parsing quota response...")
        user_status = status.get("userStatus", {})
        model_configs = user_status.get("cascadeModelConfigData", {}).get("clientModelConfigs", [])
        
        flash_fracs, pro_fracs, claude_fracs = [], [], []
        flash_models, pro_models, claude_models = [], [], []

        for c in model_configs:
            label = c.get("label", "")
            quota_info = c.get("quotaInfo")
            fraction = 1.0
            reset = "N/A"
            if quota_info:
                fraction = quota_info.get("remainingFraction", 1.0)
                reset = quota_info.get("resetTime", "")
            
            m_data = {"label": label, "fraction": fraction, "reset": reset}
            
            if re.search(r"flash", label, re.IGNORECASE):
                flash_fracs.append(fraction)
                flash_models.append(m_data)
            elif re.search(r"pro", label, re.IGNORECASE):
                pro_fracs.append(fraction)
                pro_models.append(m_data)
            elif re.search(r"claude|gpt", label, re.IGNORECASE):
                claude_fracs.append(fraction)
                claude_models.append(m_data)

        fraction_flash = min(flash_fracs) if flash_fracs else 1.0
        fraction_pro = min(pro_fracs) if pro_fracs else 1.0
        fraction_claude = min(claude_fracs) if claude_fracs else 1.0

        print(f"Quota parsed: Flash={fraction_flash*100:.1f}%, Pro={fraction_pro*100:.1f}%, Claude/GPT={fraction_claude*100:.1f}%")

        icon = self.make_concentric_icon(fraction_flash, fraction_pro, fraction_claude)
        self.tray.setIcon(icon)
        self.tray.setToolTip(
            f"Antigravity Quota\n"
            f"Flash: {fraction_flash*100:.1f}%\n"
            f"Pro: {fraction_pro*100:.1f}%\n"
            f"Claude/GPT: {fraction_claude*100:.1f}%"
        )

        self.rebuild_menu(flash_models, pro_models, claude_models)
        print("Tray icon and menu updated successfully.")

    def set_error_icon(self, msg):
        pixmap = QPixmap(22, 22)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(QColor(255, 68, 68)))
        painter.setPen(Qt.NoPen if PYQT_VERSION == 5 else Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(3, 3, 16, 16))
        painter.end()
        
        self.tray.setIcon(QIcon(pixmap))
        self.tray.setToolTip(f"Antigravity Quota: {msg}")
        
        self.menu.clear()
        err_action = QAction(f"Error: {msg}", self.menu)
        err_action.setEnabled(False)
        self.menu.addAction(err_action)
        self.menu.addSeparator()
        
        refresh_action = QAction("Refresh", self.menu)
        refresh_action.triggered.connect(self.poll_and_update)
        self.menu.addAction(refresh_action)
        
        exit_action = QAction("Exit", self.menu)
        exit_action.triggered.connect(self.app.quit)
        self.menu.addAction(exit_action)

    def rebuild_menu(self, flash, pro, claude):
        self.menu.clear()
        
        def add_category_header(title):
            header = QAction(title, self.menu)
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            header.setEnabled(False)
            self.menu.addAction(header)

        add_category_header("⚡ Gemini Flash Bucket")
        for m in flash:
            reset_lbl = f" (Resets in {fmt_reset(m['reset'])})" if m['reset'] != "N/A" and fmt_reset(m['reset']) != "Ready" else ""
            self.menu.addAction(f"  {m['label']}: {m['fraction']*100:.1f}%{reset_lbl}")
        self.menu.addSeparator()

        add_category_header("💎 Gemini Pro Bucket")
        for m in pro:
            reset_lbl = f" (Resets in {fmt_reset(m['reset'])})" if m['reset'] != "N/A" and fmt_reset(m['reset']) != "Ready" else ""
            self.menu.addAction(f"  {m['label']}: {m['fraction']*100:.1f}%{reset_lbl}")
        self.menu.addSeparator()

        add_category_header("🧠 Claude / GPT Bucket")
        for m in claude:
            reset_lbl = f" (Resets in {fmt_reset(m['reset'])})" if m['reset'] != "N/A" and fmt_reset(m['reset']) != "Ready" else ""
            self.menu.addAction(f"  {m['label']}: {m['fraction']*100:.1f}%{reset_lbl}")
        self.menu.addSeparator()

        refresh_action = QAction("Refresh Now", self.menu)
        refresh_action.triggered.connect(self.poll_and_update)
        self.menu.addAction(refresh_action)

        exit_action = QAction("Exit Monitor", self.menu)
        exit_action.triggered.connect(self.app.quit)
        self.menu.addAction(exit_action)

    def run(self):
        sys.exit(self.app.exec_() if PYQT_VERSION == 5 else self.app.exec())

if __name__ == '__main__':
    app = AntigravityQuotaApp()
    app.run()
