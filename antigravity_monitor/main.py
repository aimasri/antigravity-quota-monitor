"""
Antigravity Quota Monitor - Application Entrypoint
Handles CLI argument parsing, single-instance forwarding via IPC,
background daemon forking, and GTK3 event loop initialization.
"""

import argparse
import json
import logging
import os
import subprocess
import sys

logger = logging.getLogger("antigravity_monitor")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Antigravity Quota Monitor (v3.0 Enterprise Edition)",
        prog="antigravity-indicator"
    )
    parser.add_argument(
        "--show", "--toggle",
        action="store_true",
        help="Toggle the visual quota popup dashboard"
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Trigger an immediate live cloud quota refresh"
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Set target compute host (e.g. 'auto', 'localhost', 'aim-stream', 'aim-home')"
    )
    parser.add_argument(
        "--dump-json",
        action="store_true",
        help="Query live quota and print normalized JSON state to stdout, then exit"
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run detached as a background daemon process"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose debugging logs"
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Logging setup
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # 1. Handle --dump-json standalone CLI query
    if args.dump_json:
        from .infrastructure.probe_service import QuotaProbeService
        from .infrastructure.ssh_discovery import discover_ssh_hosts
        from .domain.policy import build_host_snapshot

        ssh_hosts, host_map = discover_ssh_hosts()
        probe_svc = QuotaProbeService()
        target = args.host or "auto"
        raw = probe_svc.probe_target(
            target=target,
            host_map=host_map,
            ssh_hosts=ssh_hosts,
            force_refresh=True
        )
        snapshot = build_host_snapshot(raw)
        if snapshot:
            # Output full serializable snapshot dict
            data = {
                "hostname": snapshot.hostname,
                "surfaces": snapshot.surfaces,
                "tier": snapshot.tier,
                "email": snapshot.email,
                "active_model": snapshot.active_model.__dict__,
                "gemini_pool": {
                    "title": snapshot.gemini_pool.title,
                    "five_hour": snapshot.gemini_pool.five_hour.__dict__,
                    "weekly": snapshot.gemini_pool.weekly.__dict__,
                },
                "claude_gpt_pool": {
                    "title": snapshot.claude_gpt_pool.title,
                    "five_hour": snapshot.claude_gpt_pool.five_hour.__dict__,
                    "weekly": snapshot.claude_gpt_pool.weekly.__dict__,
                },
                "rings": [r.__dict__ for r in snapshot.rings],
                "updated_at": snapshot.updated_at
            }
            print(json.dumps(data, indent=2))
        else:
            print(json.dumps(raw, indent=2))
        return 0

    # 2. Check if an instance is already running via UNIX socket IPC
    from .infrastructure.ipc_server import SingleInstanceIpcService
    ipc_client = SingleInstanceIpcService()

    if args.show:
        resp = ipc_client.try_send_command_to_running_instance({"cmd": "toggle_popup"})
        if resp is not None:
            logger.info("Sent toggle_popup to running daemon.")
            return 0
    if args.refresh:
        resp = ipc_client.try_send_command_to_running_instance({"cmd": "refresh"})
        if resp is not None:
            logger.info("Sent refresh command to running daemon.")
            return 0
    if args.host:
        resp = ipc_client.try_send_command_to_running_instance({"cmd": "set_host", "host": args.host})
        if resp is not None:
            logger.info(f"Updated running daemon host to '{args.host}'.")
            return 0

    # If already running and no flags specified, default to toggling dashboard popup
    if not args.daemon:
        resp = ipc_client.try_send_command_to_running_instance({"cmd": "toggle_popup"})
        if resp is not None:
            logger.info("Daemon already running. Toggled visual dashboard.")
            return 0

    # 3. Ensure DISPLAY is configured before GTK import
    if not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = ":0"

    # 4. Handle detached --daemon invocation
    if args.daemon:
        cmd = [sys.executable, "-m", "antigravity_monitor.main"]
        if args.host:
            cmd.extend(["--host", args.host])
        subprocess.Popen(
            cmd,
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return 0

    # 5. Run full GTK3 Tray Daemon
    from .presentation.tray_daemon import QuotaTrayDaemon
    daemon = QuotaTrayDaemon()
    if args.host:
        daemon.switch_target_host(args.host)
    daemon.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
