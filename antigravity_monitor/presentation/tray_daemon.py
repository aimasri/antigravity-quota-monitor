"""
Antigravity Quota Monitor - Root Tray Daemon Orchestrator
Coordinates:
- Gtk.StatusIcon and Cairo 2-ring supersampled tray pixbuf
- Tint2 system tray embedding watchdog
- Asynchronous probe dispatch and periodic GLib timers
- UNIX domain socket Single-Instance IPC listener
- Popup Dashboard Window and Context Menu
"""

import logging
import threading
from typing import Optional, Dict, Any
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf
import cairo

from ..domain.models import HostQuotaSnapshot
from ..domain.policy import build_host_snapshot, format_reset_time
from ..infrastructure.probe_service import QuotaProbeService
from ..infrastructure.ssh_discovery import discover_ssh_hosts
from ..infrastructure.settings_repository import SettingsRepository
from ..infrastructure.ipc_server import SingleInstanceIpcService
from .cairo_gauge import draw_concentric_rings_cairo
from .popup_window import PopupDashboardWindow
from .context_menu import TrayContextMenu

logger = logging.getLogger("antigravity_monitor.daemon")


class QuotaTrayDaemon:
    def __init__(self, probe_service: Optional[QuotaProbeService] = None, settings_repo: Optional[SettingsRepository] = None):
        self.ssh_hosts, self.host_map = discover_ssh_hosts()
        self.settings_repo = settings_repo or SettingsRepository()
        self.probe_service = probe_service or QuotaProbeService()
        self.target_host = self.settings_repo.load_target_host(self.ssh_hosts)

        self.last_snapshot: Optional[HostQuotaSnapshot] = None
        self.last_error: Optional[str] = "Initializing..."
        self.is_polling: bool = False

        # 1. System Tray Icon Setup
        self.status_icon = Gtk.StatusIcon()
        self.status_icon.set_title("Antigravity Quota Monitor")
        self.status_icon.set_tooltip_text("Antigravity Quota: Initializing...")
        self.status_icon.connect("activate", self._on_tray_activated)
        self.status_icon.connect("popup-menu", self._on_tray_popup_menu)

        self._update_tray_icon_error("...")
        self.status_icon.set_visible(True)

        # 2. Presentation Components
        self.popup = PopupDashboardWindow(
            status_icon=self.status_icon,
            on_refresh_requested=lambda: self.trigger_poll(force_refresh=True),
            on_host_selected=self.switch_target_host
        )

        self.context_menu_builder = TrayContextMenu(
            on_show_popup=self.popup.show,
            on_refresh=lambda: self.trigger_poll(force_refresh=True),
            on_host_selected=self.switch_target_host,
            on_quit=self.quit
        )

        # 3. Setup Single-Instance IPC Listener
        self.ipc_service = SingleInstanceIpcService(command_handler=self._handle_ipc_command)
        if not self.ipc_service.start_listener():
            logger.warning("Another instance appears to be running, but continuing daemon startup.")
        else:
            if self.ipc_service.server_sock:
                GLib.io_add_watch(
                    self.ipc_service.server_sock.fileno(),
                    GLib.IO_IN,
                    self._on_ipc_socket_ready
                )

        # 4. Periodic Quota Refresh Timer (60 seconds)
        GLib.timeout_add_seconds(60, self._on_periodic_timer)

        # 5. X11 System Tray Embedding Watchdog (handles Tint2 panel delayed startup)
        self._embed_retry_count = 0
        GLib.timeout_add(1000, self._check_tray_embedded)

        # Start initial probe immediately
        self.trigger_poll(force_refresh=True)

    def _check_tray_embedded(self) -> bool:
        """Polls every 1s until the StatusIcon is embedded into an X11 tray panel."""
        if hasattr(self.status_icon, "is_embedded") and self.status_icon.is_embedded():
            logger.info("StatusIcon successfully embedded in desktop system tray.")
            return False  # Stop watchdog timer

        self._embed_retry_count += 1
        if self._embed_retry_count % 10 == 0:
            logger.debug(f"Waiting for X11 system tray panel to become available ({self._embed_retry_count}s)...")
        return True  # Keep checking

    def _on_ipc_socket_ready(self, _source, _condition) -> bool:
        self.ipc_service.handle_client_connection()
        return True

    def _handle_ipc_command(self, cmd_obj: Dict[str, Any]) -> Dict[str, Any]:
        cmd = cmd_obj.get("cmd", "")
        if cmd == "ping":
            return {"ok": True, "status": "running"}
        elif cmd in ("toggle_popup", "show"):
            GLib.idle_add(self.popup.toggle)
            return {"ok": True, "action": "toggled"}
        elif cmd == "refresh":
            GLib.idle_add(self.trigger_poll, True)
            return {"ok": True, "action": "refreshed"}
        elif cmd == "set_host":
            host = cmd_obj.get("host")
            if host:
                GLib.idle_add(self.switch_target_host, host)
                return {"ok": True, "host": host}
        elif cmd == "dump_json":
            return {
                "ok": True,
                "snapshot": self.last_snapshot.__dict__ if self.last_snapshot else None,
                "error": self.last_error,
                "target_host": self.target_host
            }
        return {"ok": False, "error": f"Unknown command {cmd}"}

    def _on_periodic_timer(self) -> bool:
        self.trigger_poll(force_refresh=True)
        return True

    def _on_tray_activated(self, _icon: Gtk.StatusIcon) -> None:
        self.popup.toggle()

    def _on_tray_popup_menu(self, icon: Gtk.StatusIcon, button: int, activate_time: int) -> None:
        if self.popup.is_visible():
            self.popup.hide()

        menu = self.context_menu_builder.build_menu(
            snapshot=self.last_snapshot,
            last_error=self.last_error,
            target_host=self.target_host,
            ssh_hosts=self.ssh_hosts,
            host_map=self.host_map
        )
        menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, activate_time)

    def switch_target_host(self, new_host: str) -> None:
        if self.target_host != new_host:
            self.target_host = new_host
            self.settings_repo.save_target_host(new_host)
            self.trigger_poll(force_refresh=True)

    def trigger_poll(self, force_refresh: bool = True) -> None:
        if self.is_polling:
            return
        self.is_polling = True
        self.popup.update_data(
            snapshot=self.last_snapshot,
            last_error=self.last_error,
            is_polling=True,
            target_host=self.target_host,
            ssh_hosts=self.ssh_hosts
        )

        t = threading.Thread(
            target=self._poll_worker,
            args=(self.target_host, force_refresh),
            daemon=True
        )
        t.start()

    def _poll_worker(self, target: str, force_refresh: bool) -> None:
        raw = self.probe_service.probe_target(
            target=target,
            host_map=self.host_map,
            ssh_hosts=self.ssh_hosts,
            force_refresh=force_refresh
        )
        snapshot = build_host_snapshot(raw)
        GLib.idle_add(self._on_poll_complete, raw, snapshot)

    def _on_poll_complete(self, raw: Dict[str, Any], snapshot: Optional[HostQuotaSnapshot]) -> bool:
        self.is_polling = False
        if snapshot is None:
            err = raw.get("error", "Offline") if raw else "Offline"
            detail = raw.get("detail", "") if raw else ""
            self.last_snapshot = None
            self.last_error = f"{err}\n{detail}".strip()
            self._update_tray_icon_error(err)
        else:
            self.last_snapshot = snapshot
            self.last_error = None
            self._update_tray_icon_from_snapshot(snapshot)

        self.popup.update_data(
            snapshot=self.last_snapshot,
            last_error=self.last_error,
            is_polling=False,
            target_host=self.target_host,
            ssh_hosts=self.ssh_hosts
        )
        return False

    def _make_tray_pixbuf(self, rings=None, error=False) -> GdkPixbuf.Pixbuf:
        size = 48
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
        cr = cairo.Context(surface)
        draw_concentric_rings_cairo(cr, size, size, rings or [], center_text=None, error_state=error)
        surface.flush()
        return Gdk.pixbuf_get_from_surface(surface, 0, 0, size, size)

    def _update_tray_icon_error(self, msg: str) -> None:
        pixbuf = self._make_tray_pixbuf(error=True)
        self.status_icon.set_from_pixbuf(pixbuf)
        target_lbl = "Auto" if self.target_host == "auto" else self.target_host
        self.status_icon.set_tooltip_text(
            f"Antigravity Quota [{target_lbl}]\nStatus: {msg}\nLeft-click: Open gauge | Right-click: Menu"
        )

    def _update_tray_icon_from_snapshot(self, st: HostQuotaSnapshot) -> None:
        pixbuf = self._make_tray_pixbuf(rings=st.rings, error=False)
        self.status_icon.set_from_pixbuf(pixbuf)

        act = st.active_model
        r0, r1 = st.rings[0], st.rings[1]
        r0_rst = format_reset_time(r0.reset_time)
        r1_rst = format_reset_time(r1.reset_time)

        tooltip_lines = [
            f"Antigravity Quota • {st.hostname}",
            f"★ Active: {act.label}",
            f"────────────────────────",
            f"◎ Outer ({r0.short}): {r0.fraction * 100:.1f}% (Resets {r0_rst})",
            f"◎ Inner ({r1.short}): {r1.fraction * 100:.1f}% (Resets {r1_rst})",
            f"Updated: {st.updated_at} (Click for details)",
        ]
        self.status_icon.set_tooltip_text("\n".join(tooltip_lines))

    def quit(self) -> None:
        self.ipc_service.cleanup()
        Gtk.main_quit()

    def run(self) -> None:
        Gtk.main()
