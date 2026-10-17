"""
Antigravity Quota Monitor - Domain Policies
Pure business rules:
- Proto3 zero-omission fraction parsing
- Quartile color threshold calculation
- Relative and clock reset time formatting
- Active model pool categorization
- 2-Ring concentric gauge specifications (Outer = 5h, Inner = Weekly)
"""

import re
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple, Any, List

from .models import QuotaBucket, PoolQuota, ActiveModelInfo, RingSpec, HostQuotaSnapshot


POOL_METADATA = {
    "gemini": {
        "title": "Gemini Models",
        "subtitle": "Argon • Pro • Flash",
        "short": "Gemini",
        "icon": "💎",
    },
    "claude_gpt": {
        "title": "Claude & GPT Models",
        "subtitle": "Opus • Sonnet • GPT-OSS",
        "short": "Claude/GPT",
        "icon": "🧠",
    },
}


def parse_proto3_fraction(qinfo: Optional[Dict[str, Any]]) -> float:
    """
    Parses quota fraction handling Go Proto3 zero-value omission.
    When quota drops to 0.0%, Proto3 omits the `remainingFraction` field
    while preserving `resetTime`.
    """
    if not qinfo:
        return 1.0
    if "remainingFraction" in qinfo:
        try:
            return float(qinfo["remainingFraction"])
        except (ValueError, TypeError):
            return 1.0
    if qinfo.get("resetTime"):
        return 0.0
    return 1.0


def get_rgb_float(fraction: float) -> Tuple[float, float, float]:
    """
    Returns (r, g, b) float tuple in [0.0, 1.0] across quartile health bands:
    - > 75%: Emerald Green (#62c98b)
    - 50% - 75%: Amber / Gold (#facc15)
    - 25% - 50%: Warning Orange (#fb923c)
    - <= 25%: Critical Crimson (#f87171)
    """
    frac = max(0.0, min(1.0, float(fraction)))
    if frac > 0.75:
        return (0.384, 0.788, 0.545)  # #62c98b
    elif frac > 0.50:
        return (0.980, 0.800, 0.082)  # #facc15
    elif frac > 0.25:
        return (0.984, 0.573, 0.235)  # #fb923c
    else:
        return (0.973, 0.443, 0.443)  # #f87171


def get_hex_color(fraction: float) -> str:
    r, g, b = get_rgb_float(fraction)
    return f"#{int(round(r * 255)):02x}{int(round(g * 255)):02x}{int(round(b * 255)):02x}"


def parse_reset_datetime(reset_str: Optional[str]) -> Optional[datetime]:
    if not reset_str or reset_str == "N/A":
        return None
    try:
        norm = reset_str.strip()
        if norm.endswith("Z"):
            norm = norm[:-1] + "+00:00"
        dt = datetime.fromisoformat(norm)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def format_reset_time(reset_str: Optional[str], include_clock: bool = False) -> str:
    dt = parse_reset_datetime(reset_str)
    if dt is None:
        return reset_str if reset_str and reset_str != "N/A" else "N/A"

    now = datetime.now(timezone.utc)
    total_seconds = (dt - now).total_seconds()
    if total_seconds <= 0:
        return "Ready"

    mins = int(total_seconds // 60)
    hours = mins // 60
    if mins < 60:
        rel = f"{mins}m"
    else:
        mins_rem = mins % 60
        if hours >= 24:
            days = hours // 24
            hrs_rem = hours % 24
            rel = f"{days}d {hrs_rem}h"
        else:
            rel = f"{hours}h {mins_rem:02d}m"

    if include_clock:
        local_dt = dt.astimezone()
        if hours >= 24:
            return f"{rel} ({local_dt.strftime('%a %H:%M')})"
        return f"{rel} ({local_dt.strftime('%H:%M')})"
    return rel


def classify_model_group(label: str) -> str:
    lower = label.lower()
    if re.search(r"argon|pro|flash|lite|gemini", lower):
        return "gemini"
    return "claude_gpt"


def build_host_snapshot(raw_data: Dict[str, Any]) -> Optional[HostQuotaSnapshot]:
    """
    Transforms raw probe output dict into an immutable HostQuotaSnapshot domain object.
    Computes the 2-ring gauge specs (Outer = Active 5h, Inner = Active Weekly).
    """
    if not raw_data or not raw_data.get("ok"):
        return None

    hostname = raw_data.get("hostname", "unknown")
    surfaces = raw_data.get("surfaces", [])
    tier = raw_data.get("tier", "Pro")
    email = raw_data.get("email", "")
    active_id = raw_data.get("active_model_id")
    models = raw_data.get("models", [])
    raw_groups = raw_data.get("groups") or {}

    # 1. Resolve Active Model Info
    resolved_label = None
    resolved_id = active_id or ""
    resolved_group = "gemini"

    for m in models:
        m_id = m.get("model_id", "")
        m_lbl = m.get("label", "")
        if (active_id and (m_id == active_id or m_lbl == active_id)) or resolved_label is None:
            resolved_label = m_lbl
            resolved_id = m_id
            resolved_group = classify_model_group(m_lbl)
            if active_id and (m_id == active_id or m_lbl == active_id):
                break

    if not resolved_label:
        resolved_label = "Gemini 4 Argon"

    # 2. Build Pool Quotas (Gemini and Claude/GPT)
    pools: Dict[str, PoolQuota] = {}
    for gkey in ("gemini", "claude_gpt"):
        meta = POOL_METADATA[gkey]
        rg = raw_groups.get(gkey) or {}

        # 5-Hour bucket
        fh_raw = rg.get("five_hour")
        if fh_raw:
            fh_bucket = QuotaBucket(
                bucket_id=fh_raw.get("bucket_id", f"{gkey}-5h"),
                display_name=fh_raw.get("display_name", f"{meta['title']} (5h)"),
                window="5h",
                fraction=float(fh_raw.get("fraction", 1.0)),
                reset_time=fh_raw.get("reset", "")
            )
        else:
            # Fallback to model min fraction if available
            g_models = [m for m in models if classify_model_group(m.get("label", "")) == gkey]
            frac = min((m.get("fraction", 1.0) for m in g_models), default=1.0)
            rst = next((m.get("reset", "") for m in g_models if m.get("reset")), "")
            fh_bucket = QuotaBucket(
                bucket_id=f"{gkey}-5h",
                display_name=f"{meta['title']} (5h)",
                window="5h",
                fraction=float(frac),
                reset_time=rst
            )

        # Weekly bucket
        wk_raw = rg.get("weekly")
        if wk_raw:
            wk_bucket = QuotaBucket(
                bucket_id=wk_raw.get("bucket_id", f"{gkey}-weekly"),
                display_name=wk_raw.get("display_name", f"{meta['title']} (Weekly)"),
                window="weekly",
                fraction=float(wk_raw.get("fraction", 1.0)),
                reset_time=wk_raw.get("reset", "")
            )
        else:
            wk_bucket = QuotaBucket(
                bucket_id=f"{gkey}-weekly",
                display_name=f"{meta['title']} (Weekly)",
                window="weekly",
                fraction=fh_bucket.fraction,
                reset_time=""
            )

        pools[gkey] = PoolQuota(
            key=gkey,
            title=meta["title"],
            subtitle=meta["subtitle"],
            short=meta["short"],
            icon=meta["icon"],
            five_hour=fh_bucket,
            weekly=wk_bucket
        )

    act_pool = pools[resolved_group]

    active_model = ActiveModelInfo(
        label=resolved_label,
        model_id=resolved_id,
        group_key=resolved_group,
        five_hour_fraction=act_pool.five_hour.fraction,
        five_hour_reset=act_pool.five_hour.reset_time,
        weekly_fraction=act_pool.weekly.fraction,
        weekly_reset=act_pool.weekly.reset_time
    )

    # 3. Construct 2-Ring Concentric Gauge Specs
    # Outer Ring: Active Pool 5-Hour Limit
    # Inner Ring: Active Pool Weekly Limit
    r0_frac = act_pool.five_hour.fraction
    r1_frac = act_pool.weekly.fraction

    rings = [
        RingSpec(
            role="Outer Ring (5-Hour Limit)",
            short=f"{act_pool.short} 5h",
            fraction=r0_frac,
            reset_time=act_pool.five_hour.reset_time,
            color_rgb=get_rgb_float(r0_frac),
            color_hex=get_hex_color(r0_frac)
        ),
        RingSpec(
            role="Inner Ring (Weekly Limit)",
            short=f"{act_pool.short} Wk",
            fraction=r1_frac,
            reset_time=act_pool.weekly.reset_time,
            color_rgb=get_rgb_float(r1_frac),
            color_hex=get_hex_color(r1_frac)
        )
    ]

    now_str = datetime.now().strftime("%H:%M:%S")

    return HostQuotaSnapshot(
        hostname=hostname,
        surfaces=surfaces,
        tier=tier,
        email=email,
        active_model=active_model,
        gemini_pool=pools["gemini"],
        claude_gpt_pool=pools["claude_gpt"],
        rings=rings,
        updated_at=now_str,
        is_live=True
    )
