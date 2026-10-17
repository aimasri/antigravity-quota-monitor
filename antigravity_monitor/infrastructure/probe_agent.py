#!/usr/bin/env python3
"""
Antigravity Quota Monitor - Self-Contained Probe Agent
Executable directly in-process for local queries, or read from disk and piped
over `ssh <host> python3 -` for remote compute hosts.
Requires ONLY Python standard library (>= 3.8).
"""

import json
import os
import re
import socket
import ssl
import sys
import urllib.request
from typing import Dict, List, Any, Optional, Set


def get_pid_listening_ports(pid: int) -> List[int]:
    """Finds all TCP listening ports bound by the specified PID via /proc."""
    inodes: Set[str] = set()
    try:
        for fd in os.listdir(f"/proc/{pid}/fd"):
            try:
                link = os.readlink(f"/proc/{pid}/fd/{fd}")
                m = re.match(r"socket:\[(\d+)\]", link)
                if m:
                    inodes.add(m.group(1))
            except Exception:
                continue
    except Exception:
        pass

    if not inodes:
        return []

    ports: List[int] = []
    for net_file in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(net_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f.readlines()[1:]:
                    parts = line.strip().split()
                    if len(parts) < 10:
                        continue
                    if parts[3] != "0A":  # TCP_LISTEN state
                        continue
                    if parts[9] in inodes:
                        port_hex = parts[1].split(":")[1]
                        port = int(port_hex, 16)
                        if port not in ports:
                            ports.append(port)
        except Exception:
            continue
    return sorted(ports)


def find_language_servers() -> List[Dict[str, Any]]:
    """Scans /proc for active Antigravity language_server processes."""
    servers: List[Dict[str, Any]] = []
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    raw = f.read()
                if not raw:
                    continue
                args = [a.decode("utf-8", errors="ignore") for a in raw.split(b"\x00") if a]
                if not args:
                    continue
                exe = os.path.basename(args[0])
                if not exe.startswith("language_server"):
                    continue

                csrf_token = None
                app_data_dir = "unknown"
                bin_path = args[0]
                for i, arg in enumerate(args):
                    if arg == "--csrf_token" and i + 1 < len(args):
                        csrf_token = args[i + 1]
                    elif arg.startswith("--csrf_token="):
                        csrf_token = arg.split("=", 1)[1]
                    elif arg == "--app_data_dir" and i + 1 < len(args):
                        app_data_dir = args[i + 1]
                    elif arg.startswith("--app_data_dir="):
                        app_data_dir = arg.split("=", 1)[1]

                if csrf_token:
                    surface = "AGY 2.0" if "/Antigravity2/" in bin_path else "AGY IDE"
                    servers.append({
                        "pid": int(pid),
                        "csrf_token": csrf_token,
                        "app_data_dir": app_data_dir,
                        "surface": surface,
                    })
            except Exception:
                continue
    except Exception:
        pass

    # Prioritize AGY 2.0 over IDE, then higher PID
    servers.sort(key=lambda s: (0 if s["surface"] == "AGY 2.0" else 1, -s["pid"]))
    return servers


def rpc_post(port: int, token: str, method: str, body: Dict[str, Any], timeout: float = 4.0) -> Optional[Dict[str, Any]]:
    """Sends a Connect-RPC JSON POST to the local language_server."""
    payload = json.dumps(body).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Connect-Protocol-Version": "1",
        "X-Codeium-Csrf-Token": token,
    }
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    for scheme in ("http", "https"):
        url = f"{scheme}://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/{method}"
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, context=ctx if scheme == "https" else None, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            continue
    return None


def read_active_model_from_pbtxt() -> Optional[str]:
    """Reads last_selected_agent_model from local antigravity_state.pbtxt."""
    state_path = os.path.expanduser("~/.gemini/antigravity/antigravity_state.pbtxt")
    try:
        with open(state_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        m = re.search(r"last_selected_agent_model:\s*([A-Za-z0-9_.-]+)", text)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return None


def _parse_fraction(qinfo: Optional[Dict[str, Any]]) -> float:
    """Proto3 zero-omission parser."""
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


def run_probe(force_refresh: bool = True) -> Dict[str, Any]:
    """Executes the probe against the active Antigravity language_server."""
    hostname = socket.gethostname()
    servers = find_language_servers()
    if not servers:
        return {
            "ok": False,
            "hostname": hostname,
            "error": "No Server",
            "detail": f"No running Antigravity language_server on {hostname}",
        }

    selected_model_id = read_active_model_from_pbtxt()
    default_override_id = None
    merged_models: Dict[str, Dict[str, Any]] = {}
    quota_groups: Dict[str, Dict[str, Any]] = {}
    surfaces_connected: List[str] = []
    tier_name = "Pro"
    user_email = ""

    for srv in servers:
        ports = get_pid_listening_ports(srv["pid"])
        srv_ok = False
        for port in ports:
            # 1. Query RetrieveUserQuotaSummary (gives 5h and weekly limit buckets per group)
            summary_resp = rpc_post(
                port,
                srv["csrf_token"],
                "RetrieveUserQuotaSummary",
                {"forceRefresh": bool(force_refresh)},
                timeout=5.0 if force_refresh else 2.5,
            )
            if summary_resp and isinstance(summary_resp.get("response"), dict):
                for grp in summary_resp["response"].get("groups", []):
                    gname = grp.get("displayName", "")
                    gkey = "gemini" if "gemini" in gname.lower() else "claude_gpt"
                    gentry = quota_groups.setdefault(
                        gkey,
                        {
                            "display_name": gname or ("Gemini Models" if gkey == "gemini" else "Claude & GPT Models"),
                            "description": grp.get("description", ""),
                            "five_hour": None,
                            "weekly": None,
                        },
                    )
                    for b in grp.get("buckets", []):
                        win = b.get("window", "")
                        frac = _parse_fraction(b)
                        rst = b.get("resetTime", "")
                        binfo = {
                            "bucket_id": b.get("bucketId", ""),
                            "display_name": b.get("displayName", ""),
                            "window": win,
                            "fraction": frac,
                            "reset": rst,
                        }
                        if win == "5h":
                            if gentry["five_hour"] is None or frac < gentry["five_hour"]["fraction"]:
                                gentry["five_hour"] = binfo
                        elif win == "weekly":
                            if gentry["weekly"] is None or frac < gentry["weekly"]["fraction"]:
                                gentry["weekly"] = binfo

            # 2. Query GetAvailableModels if force_refresh was requested and RetrieveUserQuotaSummary was empty
            if force_refresh and not quota_groups:
                rpc_post(
                    port,
                    srv["csrf_token"],
                    "GetAvailableModels",
                    {"forceRefresh": True},
                    timeout=5.0,
                )

            # 3. Query GetUserStatus for active model label resolution, user email, and plan tier
            status = rpc_post(
                port,
                srv["csrf_token"],
                "GetUserStatus",
                {
                    "metadata": {
                        "ideName": "antigravity",
                        "extensionName": "antigravity",
                        "locale": "en",
                    }
                },
                timeout=3.0,
            )
            if not status and not quota_groups:
                continue

            srv_ok = True
            surfaces_connected.append(f"{srv['surface']} (PID {srv['pid']})")
            if status:
                us = status.get("userStatus", {})
                user_email = us.get("email") or user_email
                plan_info = us.get("planStatus", {}).get("planInfo", {})
                tier_name = plan_info.get("planName") or tier_name

                cmcd = us.get("cascadeModelConfigData", {})
                if not default_override_id:
                    default_override_id = cmcd.get("defaultOverrideModelConfig", {}).get(
                        "modelOrAlias", {}
                    ).get("model")

                for c in cmcd.get("clientModelConfigs", []):
                    label = c.get("label", "").strip()
                    if not label:
                        continue
                    model_id = c.get("modelOrAlias", {}).get("model", "")
                    qinfo = c.get("quotaInfo") or {}
                    frac = _parse_fraction(qinfo)
                    rst = qinfo.get("resetTime", "")
                    prev = merged_models.get(label)
                    if prev is None or frac < prev["fraction"]:
                        merged_models[label] = {
                            "label": label,
                            "model_id": model_id,
                            "fraction": frac,
                            "reset": rst,
                        }
            break
        if srv_ok:
            break

    if not quota_groups and not merged_models:
        return {
            "ok": False,
            "hostname": hostname,
            "error": "Offline",
            "detail": f"Could not query LanguageServerService on {hostname}",
        }

    active_id = selected_model_id or default_override_id
    return {
        "ok": True,
        "hostname": hostname,
        "surfaces": surfaces_connected,
        "tier": tier_name,
        "email": user_email,
        "active_model_id": active_id,
        "groups": quota_groups,
        "models": list(merged_models.values()),
    }


if __name__ == "__main__":
    force = True
    if "--cached" in sys.argv:
        force = False
    result = run_probe(force_refresh=force)
    print(json.dumps(result))
