"""
Antigravity Quota Monitor - GTK3 Popup Dashboard Window
Anchored deterministically 6px above the Tint2 taskbar panel in the
gutterDesk Midnight Forest aesthetic (#060d08 background, #2c5438 border, 0px corners).
"""

import socket
import time
from typing import Callable, Optional, List, Tuple
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib
import cairo

from ..domain.models import HostQuotaSnapshot
from ..domain.policy import format_reset_time, get_hex_color
from .cairo_gauge import draw_concentric_rings_cairo, draw_linear_progress_bar_cairo


POPUP_CSS = b"""
#agy_popup_window {
    background-color: #060d08;
    color: #d8e2dc;
    border: 1px solid #2c5438;
    border-radius: 0px;
}
.agy-header {
    background-color: #0b140e;
    border-bottom: 1px solid #183321;
    padding: 7px 10px;
}
.agy-title {
    color: #629e79;
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 0.8px;
}
.agy-host-badge {
    color: #7c9082;
    font-size: 11px;
}
.agy-hero-card {
    background-color: #0b140e;
    border: 1px solid #183321;
    padding: 10px;
    border-radius: 0px;
}
.agy-bucket-card {
    background-color: #09120c;
    border: 1px solid #15291c;
    padding: 8px 10px;
    border-radius: 0px;
}
.agy-active-tag {
    color: #62c98b;
    font-size: 10px;
    font-weight: 700;
}
.agy-active-name {
    color: #ffffff;
    font-size: 13px;
    font-weight: 700;
}
.agy-active-sub {
    color: #94a89b;
    font-size: 11px;
}
.agy-btn {
    background-image: none;
    background-color: #0f1d14;
    color: #d8e2dc;
    border: 1px solid #24422e;
    border-radius: 0px;
    padding: 3px 8px;
    font-size: 11px;
}
.agy-btn:hover {
    background-color: #183321;
    border-color: #629e79;
}
"""


class PopupDashboardWindow:
    def __init__(
        self,
        status_icon: Gtk.StatusIcon,
        on_refresh_requested: Callable[[], None],
        on_host_selected: Callable[[str], None],
    ):
        self.status_icon = status_icon
        self.on_refresh_requested = on_refresh_requested
        self.on_host_selected = on_host_selected

        self.last_state: Optional[HostQuotaSnapshot] = None
        self.last_error: Optional[str] = "Initializing..."
        self.is_polling: bool = False
        self.target_host: str = "auto"
        self.ssh_hosts: List[str] = []
        self.last_focus_out_time: float = 0.0

        self._apply_css()
        self.win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.win.set_name("agy_popup_window")
        self.win.set_decorated(False)
        self.win.set_skip_taskbar_hint(True)
        self.win.set_skip_pager_hint(True)
        self.win.set_keep_above(True)
        self.win.set_resizable(False)
        self.win.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)

        self.win.connect("focus-out-event", self._on_focus_out)
        self.win.connect("key-press-event", self._on_key_press)

        self.root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.win.add(self.root_box)

    def _apply_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(POPUP_CSS)
        screen = Gdk.Screen.get_default()
        if screen:
            Gtk.StyleContext.add_provider_for_screen(
                screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def is_visible(self) -> bool:
        return self.win.get_visible()

    def hide(self) -> None:
        self.win.hide()

    def toggle(self) -> None:
        if self.is_visible():
            self.hide()
            return
        if time.monotonic() - self.last_focus_out_time < 0.25:
            return
        self.show()

    def show(self) -> None:
        self.rebuild_content()
        self._position_near_tray()
        self.win.show_all()
        self.win.present()
        self.win.grab_focus()

    def _on_focus_out(self, win, _event) -> bool:
        self.last_focus_out_time = time.monotonic()
        win.hide()
        return False

    def _on_key_press(self, win, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            win.hide()
            return True
        return False

    def _position_near_tray(self) -> None:
        """Determines natural dimensions and anchors 6px above Tint2 tray."""
        self.root_box.show_all()
        self.win.realize()

        _, nat = self.root_box.get_preferred_size()
        win_w = max(nat.width + 2, 350)
        win_h = max(nat.height + 2, 120)
        self.win.resize(win_w, win_h)

        display = Gdk.Display.get_default()
        screen = Gdk.Screen.get_default()

        ok, screen_g, area_rect, _orientation = self.status_icon.get_geometry()
        if ok and screen_g is not None:
            screen = screen_g

        mon_x, mon_y, mon_w, mon_h = 0, 0, 1920, 1080
        mon = None
        if display:
            if ok and area_rect.width > 0 and hasattr(display, "get_monitor_at_point"):
                mon = display.get_monitor_at_point(
                    area_rect.x + area_rect.width // 2,
                    area_rect.y + area_rect.height // 2,
                )
            if mon is None and hasattr(display, "get_primary_monitor"):
                mon = display.get_primary_monitor()
            if mon is None and hasattr(display, "get_n_monitors") and display.get_n_monitors() > 0:
                mon = display.get_monitor(0)

        if mon is not None:
            geom = mon.get_geometry()
            mon_x, mon_y, mon_w, mon_h = geom.x, geom.y, geom.width, geom.height
        elif screen:
            mon_w, mon_h = screen.get_width(), screen.get_height()

        if ok and area_rect.width > 0:
            tray_cx = area_rect.x + area_rect.width // 2
            x = tray_cx - (win_w // 2)
            x = max(mon_x + 8, min(x, mon_x + mon_w - win_w - 8))

            if area_rect.y > (mon_y + mon_h // 2):
                panel_top = mon_y + mon_h - 30
                if area_rect.y < panel_top + 12:
                    panel_top = area_rect.y - 3
                y = panel_top - win_h - 6
            else:
                panel_bottom = area_rect.y + area_rect.height + 3
                y = panel_bottom + 6
        else:
            x = mon_x + mon_w - win_w - 12
            y = mon_y + mon_h - 30 - win_h - 6

        y = max(mon_y + 8, min(y, mon_y + mon_h - win_h - 8))
        self.win.move(int(x), int(y))

    def update_data(
        self,
        snapshot: Optional[HostQuotaSnapshot],
        last_error: Optional[str],
        is_polling: bool,
        target_host: str,
        ssh_hosts: List[str]
    ) -> None:
        self.last_state = snapshot
        self.last_error = last_error
        self.is_polling = is_polling
        self.target_host = target_host
        self.ssh_hosts = ssh_hosts

        if self.is_visible():
            self.rebuild_content()
            self._position_near_tray()

    def rebuild_content(self) -> None:
        for child in self.root_box.get_children():
            self.root_box.remove(child)

        self.root_box.set_size_request(350, -1)

        # 1. Header Bar
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header_box.get_style_context().add_class("agy-header")

        title_lbl = Gtk.Label(label="ANTIGRAVITY QUOTA")
        title_lbl.get_style_context().add_class("agy-title")
        title_lbl.set_xalign(0)
        header_box.pack_start(title_lbl, False, False, 0)

        host_str = self.last_state.hostname if self.last_state else self.target_host
        surf_str = (
            f"• {self.last_state.surfaces[0].split(' (')[0]}"
            if (self.last_state and self.last_state.surfaces)
            else ""
        )
        host_badge = Gtk.Label(label=f"[{host_str} {surf_str}]".replace(" ]", "]"))
        host_badge.get_style_context().add_class("agy-host-badge")
        header_box.pack_start(host_badge, False, False, 2)

        refresh_btn = Gtk.Button(label="↻ Refresh" if not self.is_polling else "…")
        refresh_btn.get_style_context().add_class("agy-btn")
        refresh_btn.connect("clicked", lambda _b: self.on_refresh_requested())
        header_box.pack_end(refresh_btn, False, False, 0)

        self.root_box.pack_start(header_box, False, False, 0)

        # Body container
        body_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        body_box.set_margin_top(8)
        body_box.set_margin_bottom(8)
        body_box.set_margin_start(8)
        body_box.set_margin_end(8)

        # Target Host Selector Row
        target_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        target_lbl = Gtk.Label(label="Host:")
        target_lbl.get_style_context().add_class("agy-active-sub")
        target_lbl.set_xalign(0)
        target_row.pack_start(target_lbl, False, False, 0)

        options = [("auto", "Auto"), ("localhost", f"Local ({socket.gethostname()})")]
        for h in self.ssh_hosts:
            if h not in ("localhost", socket.gethostname()):
                options.append((h, h))

        for key, text in options[:4]:
            btn = Gtk.Button(label=f"● {text}" if self.target_host == key else text)
            btn.get_style_context().add_class("agy-btn")
            btn.connect("clicked", lambda _b, k=key: self.on_host_selected(k))
            target_row.pack_start(btn, False, False, 0)

        body_box.pack_start(target_row, False, False, 0)

        if self.last_state is None:
            err_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            err_card.get_style_context().add_class("agy-hero-card")
            err_lbl = Gtk.Label(label=self.last_error or "Offline")
            err_lbl.set_line_wrap(True)
            err_lbl.set_xalign(0)
            err_card.pack_start(err_lbl, False, False, 0)
            body_box.pack_start(err_card, False, False, 0)
            self.root_box.pack_start(body_box, False, False, 0)
            return

        st = self.last_state
        act = st.active_model
        rings = st.rings

        # 2. Hero Card: 86x86 2-Ring Concentric Gauge + Model Readout
        hero_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        hero_card.get_style_context().add_class("agy-hero-card")

        ring_area = Gtk.DrawingArea()
        ring_area.set_size_request(86, 86)
        fh_pct = act.five_hour_fraction
        center_pct = f"{int(round(fh_pct * 100))}%"
        ring_area.connect(
            "draw",
            lambda _w, cr: draw_concentric_rings_cairo(
                cr, 86, 86, rings, center_text=center_pct, error_state=False
            )
        )
        hero_card.pack_start(ring_area, False, False, 0)

        hero_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        hero_info.set_valign(Gtk.Align.CENTER)

        tag_lbl = Gtk.Label(label=f"★ ACTIVE MODEL ({st.tier.upper()} TIER)")
        tag_lbl.get_style_context().add_class("agy-active-tag")
        tag_lbl.set_xalign(0)
        hero_info.pack_start(tag_lbl, False, False, 0)

        name_lbl = Gtk.Label(label=act.label)
        name_lbl.get_style_context().add_class("agy-active-name")
        name_lbl.set_xalign(0)
        hero_info.pack_start(name_lbl, False, False, 0)

        wk_pct = act.weekly_fraction
        sub_lbl = Gtk.Label()
        sub_lbl.set_markup(
            f"<span foreground='#94a89b' size='small'>5h:</span> "
            f"<span foreground='{get_hex_color(fh_pct)}' weight='bold'>{fh_pct * 100:.1f}%</span>"
            f"   <span foreground='#94a89b' size='small'>Weekly:</span> "
            f"<span foreground='{get_hex_color(wk_pct)}' weight='bold'>{wk_pct * 100:.1f}%</span>"
        )
        sub_lbl.set_xalign(0)
        hero_info.pack_start(sub_lbl, False, False, 0)

        # 2-Ring Legend (Outer & Inner)
        legend_lbl = Gtk.Label()
        legend_parts = []
        for idx, tag in enumerate(("Outer", "Inner")):
            r_item = rings[idx]
            legend_parts.append(
                f"<span foreground='{r_item.color_hex}'>●</span> "
                f"<span foreground='#7c9082' size='small'>{tag}: {r_item.short} ({r_item.fraction*100:.0f}%)</span>"
            )
        legend_lbl.set_markup("   ".join(legend_parts))
        legend_lbl.set_xalign(0)
        hero_info.pack_start(legend_lbl, False, False, 1)

        hero_card.pack_start(hero_info, True, True, 0)
        body_box.pack_start(hero_card, False, False, 0)

        # 3. Compact Group Cards: Gemini Models and Claude/GPT Models
        for pool in (st.gemini_pool, st.claude_gpt_pool):
            is_act_group = (act.group_key == pool.key)

            gcard = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            gcard.get_style_context().add_class("agy-bucket-card")

            ghead = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            gtit = Gtk.Label()
            act_badge = " <span foreground='#62c98b' size='small'>[ACTIVE POOL]</span>" if is_act_group else ""
            gtit.set_markup(
                f"<span weight='bold' foreground='#d8e2dc'>{pool.icon} {pool.title}</span>"
                f"{act_badge}"
            )
            gtit.set_xalign(0)
            ghead.pack_start(gtit, True, True, 0)

            gsub = Gtk.Label()
            gsub.set_markup(f"<span foreground='#7c9082' size='small'>{pool.subtitle}</span>")
            gsub.set_xalign(1)
            ghead.pack_end(gsub, False, False, 0)
            gcard.pack_start(ghead, False, False, 0)

            # Two limits per pool
            for bucket, win_lbl in ((pool.five_hour, "⏱ 5-Hour Limit"), (pool.weekly, "📅 Weekly Limit")):
                wbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                wrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

                wlbl = Gtk.Label()
                wlbl.set_markup(f"<span foreground='#b7c9bd' size='small'>{win_lbl}</span>")
                wlbl.set_xalign(0)
                wrow.pack_start(wlbl, True, True, 0)

                wpct = Gtk.Label()
                rst_fmt = format_reset_time(bucket.reset_time, include_clock=True)
                rst_txt = f"Resets {rst_fmt}" if rst_fmt != "N/A" else ""
                col_hex = get_hex_color(bucket.fraction)
                wpct.set_markup(
                    f"<span foreground='#7c9082' size='small'>{rst_txt}</span>  "
                    f"<span weight='bold' foreground='{col_hex}' size='small'>{bucket.fraction * 100:.1f}%</span>"
                )
                wpct.set_xalign(1)
                wrow.pack_end(wpct, False, False, 0)
                wbox.pack_start(wrow, False, False, 0)

                bar = Gtk.DrawingArea()
                bar.set_size_request(-1, 6)
                bar.connect("draw", lambda _w, cr, f=bucket.fraction: draw_linear_progress_bar_cairo(cr, _w.get_allocation().width, _w.get_allocation().height, f))
                wbox.pack_start(bar, False, False, 0)

                gcard.pack_start(wbox, False, False, 0)

            body_box.pack_start(gcard, False, False, 0)

        self.root_box.pack_start(body_box, False, False, 0)
