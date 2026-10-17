"""
Antigravity Quota Monitor - Cairo Gauge Renderer
Pure Cairo vector rendering for:
- 2-Ring Concentric Quota Gauge (Outer: 5-Hour Limit, Inner: Weekly Limit)
- Horizontal dual-limit progress bars
"""

import math
from typing import List, Optional
import cairo

from ..domain.models import RingSpec
from ..domain.policy import get_rgb_float


def draw_concentric_rings_cairo(
    cr: cairo.Context,
    width: float,
    height: float,
    rings: List[RingSpec],
    center_text: Optional[str] = None,
    error_state: bool = False
) -> None:
    """
    Draws 2 bold concentric quota rings on a Cairo context:
    - Outer Ring (index 0): Active Model Group 5-Hour Limit
    - Inner Ring (index 1): Active Model Group Weekly Limit
    """
    cr.save()
    cr.set_operator(cairo.OPERATOR_CLEAR)
    cr.paint()
    cr.set_operator(cairo.OPERATOR_OVER)

    cx = width / 2.0
    cy = height / 2.0
    scale = min(width, height) / 48.0

    if error_state or not rings:
        cr.set_source_rgba(0.973, 0.443, 0.443, 0.25)
        cr.arc(cx, cy, 18.0 * scale, 0, 2 * math.pi)
        cr.fill()

        cr.set_line_width(3.5 * scale)
        cr.set_source_rgba(0.973, 0.443, 0.443, 0.95)
        cr.arc(cx, cy, 18.0 * scale, 0, 2 * math.pi)
        cr.stroke()

        cr.arc(cx, cy, 4.5 * scale, 0, 2 * math.pi)
        cr.fill()
        cr.restore()
        return

    # 2 Ring Geometry Specs: (radius, stroke_thickness)
    specs = [
        (19.0 * scale, 5.6 * scale),  # Outer ring: 5-Hour Limit
        (11.0 * scale, 5.2 * scale),  # Inner ring: Weekly Limit
    ]

    start_angle = -math.pi / 2.0  # 12 o'clock

    for idx, (radius, thickness) in enumerate(specs):
        if idx < len(rings):
            ring = rings[idx]
            frac = max(0.0, min(1.0, float(ring.fraction)))
            r, g, b = ring.color_rgb
        else:
            frac = 1.0
            r, g, b = get_rgb_float(1.0)

        # 1. Background dark track
        cr.set_line_width(thickness)
        cr.set_line_cap(cairo.LINE_CAP_BUTT)
        cr.set_source_rgba(0.16, 0.24, 0.19, 0.55)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.stroke()

        # 2. Foreground progress arc (clockwise)
        if frac > 0.005:
            cr.set_source_rgba(r, g, b, 0.98)
            cr.set_line_width(thickness)
            cr.set_line_cap(cairo.LINE_CAP_ROUND if width >= 64 else cairo.LINE_CAP_BUTT)
            end_angle = start_angle + (frac * 2.0 * math.pi)
            cr.arc(cx, cy, radius, start_angle, end_angle)
            cr.stroke()

    # Optional center percentage text for hero widget
    if center_text and width >= 64:
        cr.select_font_face("Liberation Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(9.5 * scale)
        ext = cr.text_extents(center_text)
        tx = cx - (ext.width / 2.0 + ext.x_bearing)
        ty = cy - (ext.height / 2.0 + ext.y_bearing)

        cr.set_source_rgba(0.02, 0.05, 0.03, 0.88)
        cr.arc(cx, cy, 6.8 * scale, 0, 2 * math.pi)
        cr.fill()

        cr.set_source_rgba(0.97, 0.98, 0.99, 0.98)
        cr.move_to(tx, ty)
        cr.show_text(center_text)

    cr.restore()


def draw_linear_progress_bar_cairo(
    cr: cairo.Context,
    width: float,
    height: float,
    fraction: float
) -> None:
    """Draws a horizontal progress bar in the Midnight Forest aesthetic."""
    cr.set_source_rgba(0.09, 0.16, 0.11, 1.0)
    cr.rectangle(0, 0, width, height)
    cr.fill()

    frac = max(0.0, min(1.0, fraction))
    if frac > 0:
        r, g, b = get_rgb_float(frac)
        cr.set_source_rgba(r, g, b, 0.95)
        cr.rectangle(0, 0, max(2.0, width * frac), height)
        cr.fill()
