"""
Antigravity Quota Monitor - Domain Models
Immutable, strongly typed data structures representing quota states, buckets, and snapshots.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class QuotaBucket:
    bucket_id: str
    display_name: str
    window: str  # "5h" or "weekly"
    fraction: float  # [0.0, 1.0]
    reset_time: str  # ISO-8601 UTC string (e.g. "2026-10-15T18:42:35Z")


@dataclass(frozen=True)
class PoolQuota:
    key: str  # "gemini" or "claude_gpt"
    title: str
    subtitle: str
    short: str
    icon: str
    five_hour: QuotaBucket
    weekly: QuotaBucket


@dataclass(frozen=True)
class ActiveModelInfo:
    label: str
    model_id: str
    group_key: str
    five_hour_fraction: float
    five_hour_reset: str
    weekly_fraction: float
    weekly_reset: str


@dataclass(frozen=True)
class RingSpec:
    role: str
    short: str
    fraction: float
    reset_time: str
    color_rgb: Tuple[float, float, float]
    color_hex: str


@dataclass(frozen=True)
class HostQuotaSnapshot:
    hostname: str
    surfaces: List[str]
    tier: str
    email: str
    active_model: ActiveModelInfo
    gemini_pool: PoolQuota
    claude_gpt_pool: PoolQuota
    rings: List[RingSpec]
    updated_at: str  # "HH:MM:SS"
    is_live: bool = True
    error_message: Optional[str] = None
    error_detail: Optional[str] = None
