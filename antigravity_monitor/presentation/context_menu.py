"""
Antigravity Quota Monitor - GTK3 Context Menu
Right-click context menu showing status, target computer switcher, and actions.
"""

import socket
from typing import Callable, Optional, List, Dict
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ..domain.models import HostQuotaSnapshot
from ..domain.policy import format_reset_time


class TrayContextMenu:
    def __init__(
        self,
        on_show_popup: Callable[[], None],
        on_refresh: Callable[[], None],
        on_host_selected: Callable[[str], None],
        on_quit: Callable[[], None]
    ):
        self.on_show_popup = on_show_popup
        self.on_refresh = on_refresh
        self.on_host_selected = on_host_selected
        self.on_quit = on_quit

    def build_menu(
        self,
        snapshot: Optional[HostQuotaSnapshot],
        last_error: Optional[str],
        target_host: str,
        ssh_hosts: List[str],
        host_map: Dict[str, str]
    ) -> Gtk.Menu:
        menu = Gtk.Menu()

        if snapshot:
            st = snapshot
            surf = f" • {st.surfaces[0]}" if st.surfaces else ""
            hdr = Gtk.MenuItem(label=f"🖥 Host: {st.hostname}{surf}")
            hdr.set_sensitive(False)
            menu.append(hdr)

            act = st.active_model
            act_item = Gtk.MenuItem(
                label=f"★ Active: {act.label} (5h: {act.five_hour_fraction*100:.1f}% | Wk: {act.weekly_fraction*100:.1f}%)"
            )
            act_item.connect("activate", lambda _i: self.on_show_popup())
            menu.append(act_item)
            menu.append(Gtk.SeparatorMenuItem())

            for pool in (st.gemini_pool, st.claude_gpt_pool):
                ghdr = Gtk.MenuItem(label=f"{pool.icon} {pool.title} ({pool.subtitle})")
                ghdr.set_sensitive(False)
                menu.append(ghdr)

                fh_reset = format_reset_time(pool.five_hour.reset_time)
                fh_item = Gtk.MenuItem(
                    label=f"  ⏱ 5-Hour Limit: {pool.five_hour.fraction * 100:.1f}% (Resets in {fh_reset})"
                )
                fh_item.connect("activate", lambda _i: self.on_show_popup())
                menu.append(fh_item)

                wk_reset = format_reset_time(pool.weekly.reset_time)
                wk_item = Gtk.MenuItem(
                    label=f"  📅 Weekly Limit: {pool.weekly.fraction * 100:.1f}% (Resets in {wk_reset})"
                )
                wk_item.connect("activate", lambda _i: self.on_show_popup())
                menu.append(wk_item)

                menu.append(Gtk.SeparatorMenuItem())
        else:
            err_item = Gtk.MenuItem(label=f"⚠ Status: {last_error or 'Offline'}")
            err_item.set_sensitive(False)
            menu.append(err_item)
            menu.append(Gtk.SeparatorMenuItem())

        # Target Computer Selector Submenu
        host_menu_item = Gtk.MenuItem(label=f"🖧 Target Computer ({target_host})")
        host_submenu = Gtk.Menu()
        host_menu_item.set_submenu(host_submenu)

        targets = [
            ("auto", "Auto (Detect Active Host)"),
            ("localhost", f"Localhost ({socket.gethostname()})"),
        ]
        for h in ssh_hosts:
            if h not in ("localhost", socket.gethostname()):
                targets.append((h, f"{h} ({host_map.get(h, h)})"))

        group = []
        for key, label in targets:
            radio = Gtk.RadioMenuItem.new_with_label(group, label)
            group = radio.get_group()
            if target_host == key:
                radio.set_active(True)
            radio.connect("toggled", self._on_radio_toggled, key, target_host)
            host_submenu.append(radio)

        menu.append(host_menu_item)
        menu.append(Gtk.SeparatorMenuItem())

        open_dash = Gtk.MenuItem(label="📊 Open Visual Gauge")
        open_dash.connect("activate", lambda _i: self.on_show_popup())
        menu.append(open_dash)

        refresh_item = Gtk.MenuItem(label="↻ Refresh Now (Live)")
        refresh_item.connect("activate", lambda _i: self.on_refresh())
        menu.append(refresh_item)

        exit_item = Gtk.MenuItem(label="✕ Exit Monitor")
        exit_item.connect("activate", lambda _i: self.on_quit())
        menu.append(exit_item)

        menu.show_all()
        return menu

    def _on_radio_toggled(self, radio_item: Gtk.RadioMenuItem, host_key: str, current_target: str) -> None:
        if radio_item.get_active() and current_target != host_key:
            self.on_host_selected(host_key)
