"""
Antigravity Quota Monitor - Automated Unit Tests
Tests domain policies, Proto3 parsing, quartile color thresholds, 2-ring mapping,
and IPC dispatch.
"""

import os
import unittest
from datetime import datetime, timezone

from antigravity_monitor.domain.policy import (
    parse_proto3_fraction,
    get_rgb_float,
    get_hex_color,
    classify_model_group,
    format_reset_time,
    build_host_snapshot,
)
from antigravity_monitor.infrastructure.ssh_discovery import is_local_target


class TestDomainPolicies(unittest.TestCase):

    def test_proto3_zero_value_omission(self):
        """When quota is 0.0%, Proto3 omits remainingFraction while keeping resetTime."""
        # 1. Normal quota with fraction
        q_normal = {"remainingFraction": 0.65, "resetTime": "2026-10-15T18:00:00Z"}
        self.assertAlmostEqual(parse_proto3_fraction(q_normal), 0.65)

        # 2. Exhausted quota (omitted remainingFraction)
        q_exhausted = {"resetTime": "2026-10-15T18:00:00Z"}
        self.assertAlmostEqual(parse_proto3_fraction(q_exhausted), 0.0)

        # 3. Unconstrained / full quota (no quota info)
        self.assertAlmostEqual(parse_proto3_fraction(None), 1.0)
        self.assertAlmostEqual(parse_proto3_fraction({}), 1.0)

    def test_quartile_color_thresholds(self):
        """Verifies quartile color bands."""
        # > 75% -> Emerald Green (#62c98b)
        self.assertEqual(get_hex_color(0.85), "#62c98b")
        self.assertEqual(get_hex_color(1.0), "#62c98b")

        # 50% - 75% -> Amber / Gold (#facc15)
        self.assertEqual(get_hex_color(0.64), "#facc15")
        self.assertEqual(get_hex_color(0.55), "#facc15")

        # 25% - 50% -> Warning Orange (#fb923c)
        self.assertEqual(get_hex_color(0.40), "#fb923c")
        self.assertEqual(get_hex_color(0.26), "#fb923c")

        # <= 25% -> Critical Crimson (#f87171)
        self.assertEqual(get_hex_color(0.20), "#f87171")
        self.assertEqual(get_hex_color(0.0), "#f87171")

    def test_model_classification(self):
        """Verifies classification of model names into 'gemini' or 'claude_gpt'."""
        self.assertEqual(classify_model_group("Gemini 4 Argon (Low)"), "gemini")
        self.assertEqual(classify_model_group("Gemini 3.8 Flash (High)"), "gemini")
        self.assertEqual(classify_model_group("Claude Opus 5.5"), "claude_gpt")
        self.assertEqual(classify_model_group("Claude Sonnet 5.5"), "claude_gpt")
        self.assertEqual(classify_model_group("GPT-OSS 120B"), "claude_gpt")

    def test_snapshot_and_two_ring_builder(self):
        """Verifies that HostQuotaSnapshot creates exactly 2 rings (Outer=5h, Inner=Weekly)."""
        raw_probe = {
            "ok": True,
            "hostname": "test-host",
            "surfaces": ["AGY 2.0 (PID 1234)"],
            "tier": "Pro",
            "email": "dev@test.org",
            "active_model_id": "MODEL_ARGON",
            "groups": {
                "gemini": {
                    "display_name": "Gemini Models",
                    "five_hour": {"fraction": 0.58, "reset": "2026-10-15T18:42:35Z"},
                    "weekly": {"fraction": 0.83, "reset": "2026-10-21T04:53:04Z"}
                },
                "claude_gpt": {
                    "display_name": "Claude & GPT Models",
                    "five_hour": {"fraction": 1.0, "reset": ""},
                    "weekly": {"fraction": 1.0, "reset": ""}
                }
            },
            "models": [
                {"label": "Gemini 4 Argon (Low)", "model_id": "MODEL_ARGON", "fraction": 0.58, "reset": ""}
            ]
        }

        snapshot = build_host_snapshot(raw_probe)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.hostname, "test-host")
        self.assertEqual(snapshot.active_model.label, "Gemini 4 Argon (Low)")

        # Verify exactly 2 rings
        self.assertEqual(len(snapshot.rings), 2)
        r_outer, r_inner = snapshot.rings[0], snapshot.rings[1]

        # Outer: 5h limit (58% -> Amber)
        self.assertEqual(r_outer.role, "Outer Ring (5-Hour Limit)")
        self.assertAlmostEqual(r_outer.fraction, 0.58)
        self.assertEqual(r_outer.color_hex, "#facc15")

        # Inner: Weekly limit (83% -> Green)
        self.assertEqual(r_inner.role, "Inner Ring (Weekly Limit)")
        self.assertAlmostEqual(r_inner.fraction, 0.83)
        self.assertEqual(r_inner.color_hex, "#62c98b")

    def test_local_target_resolution(self):
        """Verifies local target detection logic."""
        import socket
        local_h = socket.gethostname()
        host_map = {"aim-stream": "127.0.0.1", "remote-node": "192.168.1.100"}

        self.assertTrue(is_local_target("localhost", host_map))
        self.assertTrue(is_local_target(local_h, host_map))
        self.assertTrue(is_local_target("aim-stream", host_map))
        self.assertFalse(is_local_target("remote-node", host_map))


if __name__ == "__main__":
    unittest.main()
