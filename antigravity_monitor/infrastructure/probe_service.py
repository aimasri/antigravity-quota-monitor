"""
Antigravity Quota Monitor - Probe Service
Coordinates local vs. remote SSH probe executions.
Features:
- Direct in-process invocation for local queries
- Streaming probe_agent.py over SSH for remote queries
- OpenSSH ControlMaster multiplexing with automatic stale socket recovery
"""

import json
import logging
import os
import subprocess
from typing import Dict, Any, Optional

from .probe_agent import run_probe as run_local_probe
from .ssh_discovery import is_local_target

logger = logging.getLogger("antigravity_monitor.probe_service")


class QuotaProbeService:
    def __init__(self, probe_agent_path: Optional[str] = None):
        if probe_agent_path is None:
            probe_agent_path = os.path.join(os.path.dirname(__file__), "probe_agent.py")
        self.probe_agent_path = probe_agent_path
        self._cached_agent_source: Optional[str] = None

    def _get_agent_source(self) -> str:
        if self._cached_agent_source is None:
            try:
                with open(self.probe_agent_path, "r", encoding="utf-8") as f:
                    self._cached_agent_source = f.read()
            except Exception as e:
                logger.error(f"Failed to read probe_agent.py from {self.probe_agent_path}: {e}")
                self._cached_agent_source = ""
        return self._cached_agent_source

    def _get_control_path(self) -> str:
        uid = os.getuid()
        runtime_dir = f"/run/user/{uid}" if os.path.isdir(f"/run/user/{uid}") else "/tmp"
        return os.path.join(runtime_dir, "agy-quota-ssh-%r@%h:%p")

    def execute_ssh_probe(self, ssh_host: str, force_refresh: bool = True, retry_stale: bool = True) -> Dict[str, Any]:
        """
        Executes probe_agent.py on the remote host over SSH.
        Automatically recovers from stale ControlMaster sockets (e.g. after sleep/suspend or network roam).
        """
        agent_code = self._get_agent_source()
        if not agent_code:
            return {
                "ok": False,
                "hostname": ssh_host,
                "error": "Internal Error",
                "detail": "Failed to read local probe agent payload",
            }

        ctl_path = self._get_control_path()
        flag = "--live" if force_refresh else "--cached"
        remote_exec_code = agent_code + f"\nif __name__ == '__main__':\n    import sys\n    print(json.dumps(run_probe(force_refresh={bool(force_refresh)})))\n"

        cmd = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=3",
            "-o", "ControlMaster=auto",
            "-o", f"ControlPath={ctl_path}",
            "-o", "ControlPersist=5m",
            ssh_host,
            "python3", "-",
        ]

        try:
            proc = subprocess.run(
                cmd,
                input=remote_exec_code,
                capture_output=True,
                text=True,
                timeout=8,
            )

            # Stale ControlMaster socket recovery (exit code 255 with socket error)
            if proc.returncode == 255 and retry_stale:
                logger.warning(f"SSH returned exit 255 for {ssh_host}. Testing socket reset...")
                try:
                    subprocess.run(
                        ["ssh", "-O", "exit", "-o", f"ControlPath={ctl_path}", ssh_host],
                        capture_output=True,
                        timeout=2
                    )
                except Exception:
                    pass
                return self.execute_ssh_probe(ssh_host, force_refresh=force_refresh, retry_stale=False)

            if proc.returncode != 0:
                err_lines = (proc.stderr or "").strip().splitlines()
                short_err = err_lines[-1] if err_lines else f"SSH exit {proc.returncode}"
                return {
                    "ok": False,
                    "hostname": ssh_host,
                    "error": f"SSH Unreachable ({ssh_host})",
                    "detail": short_err,
                }

            out_lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
            if not out_lines:
                return {
                    "ok": False,
                    "hostname": ssh_host,
                    "error": f"Empty response ({ssh_host})",
                    "detail": "Remote probe returned no output",
                }

            return json.loads(out_lines[-1])

        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "hostname": ssh_host,
                "error": f"Timeout ({ssh_host})",
                "detail": f"SSH connection to {ssh_host} timed out",
            }
        except Exception as e:
            return {
                "ok": False,
                "hostname": ssh_host,
                "error": f"Error ({ssh_host})",
                "detail": str(e),
            }

    def probe_target(self, target: str, host_map: Dict[str, str], ssh_hosts: list, force_refresh: bool = True) -> Dict[str, Any]:
        """
        Probes the requested target:
        - "auto": Checks local first; if no server, probes remote SSH hosts in cluster order.
        - "localhost" or local machine name: Probes locally.
        - specific SSH host: Probes target host over SSH.
        """
        if target == "auto":
            local_res = run_local_probe(force_refresh=force_refresh)
            if local_res.get("ok"):
                return local_res

            ordered = sorted(
                ssh_hosts,
                key=lambda h: (0 if "stream" in h else 1, ssh_hosts.index(h))
            )
            for h in ordered:
                if is_local_target(h, host_map):
                    continue
                res = self.execute_ssh_probe(h, force_refresh=force_refresh)
                if res.get("ok"):
                    return res
            return local_res

        elif is_local_target(target, host_map):
            return run_local_probe(force_refresh=force_refresh)
        else:
            return self.execute_ssh_probe(target, force_refresh=force_refresh)
