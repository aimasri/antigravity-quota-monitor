"""
Antigravity Quota Monitor - SSH Host Discovery Service
Parses ~/.ssh/config to identify available compute hosts in the cluster,
differentiating local interfaces from remote SSH nodes.
"""

import os
import socket
from typing import List, Dict, Tuple, Optional


def discover_ssh_hosts(config_path: Optional[str] = None) -> Tuple[List[str], Dict[str, str]]:
    """
    Parses ~/.ssh/config for named compute hosts, excluding wildcards and git platforms.
    Returns:
        hosts: List of clean host identifiers (e.g. ['aim-stream', 'aim-home', 'aim-book'])
        host_map: Dictionary mapping Host alias to actual HostName (if defined)
    """
    if config_path is None:
        config_path = os.path.expanduser("~/.ssh/config")

    hosts: List[str] = []
    host_map: Dict[str, str] = {}
    current_hosts: List[str] = []

    if not os.path.isfile(config_path):
        return hosts, host_map

    try:
        with open(config_path, "r", encoding="utf-8", errors="ignore") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(None, 1)
                if len(parts) < 2:
                    continue
                key, val = parts[0].lower(), parts[1].strip()
                if key == "host":
                    current_hosts = []
                    for h in val.split():
                        if (
                            "*" in h
                            or "?" in h
                            or "github.com" in h.lower()
                            or "gitlab.com" in h.lower()
                        ):
                            continue
                        current_hosts.append(h)
                        if h not in hosts:
                            hosts.append(h)
                            host_map[h] = h
                elif key == "hostname" and current_hosts:
                    for h in current_hosts:
                        host_map[h] = val
    except Exception:
        pass

    return hosts, host_map


def is_local_target(target: str, host_map: Dict[str, str]) -> bool:
    """Returns True if the target maps to the current machine."""
    local_hostname = socket.gethostname()
    if target in ("localhost", local_hostname):
        return True
    resolved = host_map.get(target, target)
    if resolved in ("127.0.0.1", "::1", "localhost", local_hostname):
        return True
    return False
