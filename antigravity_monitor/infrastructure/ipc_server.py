"""
Antigravity Quota Monitor - Single-Instance UNIX Socket IPC Service
Ensures only one instance of the daemon runs in the user's graphical session.
Allows secondary CLI invocations (e.g. `antigravity-indicator --show`, `--refresh`, `--host <target>`)
to send non-blocking JSON commands to the primary running daemon.
"""

import json
import logging
import os
import socket
from typing import Callable, Optional, Dict, Any

logger = logging.getLogger("antigravity_monitor.ipc")


class SingleInstanceIpcService:
    def __init__(self, command_handler: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None):
        self.command_handler = command_handler
        uid = os.getuid()
        runtime_dir = f"/run/user/{uid}" if os.path.isdir(f"/run/user/{uid}") else "/tmp"
        self.socket_path = os.path.join(runtime_dir, "antigravity-quota-monitor.sock")
        self.server_sock: Optional[socket.socket] = None

    def try_send_command_to_running_instance(self, command: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Attempts to connect to an existing running daemon instance and send a command.
        Returns the parsed JSON response if successful, or None if no daemon is listening.
        """
        if not os.path.exists(self.socket_path):
            return None

        client_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client_sock.settimeout(2.0)
        try:
            client_sock.connect(self.socket_path)
            payload = (json.dumps(command) + "\n").encode("utf-8")
            client_sock.sendall(payload)

            raw_resp = client_sock.recv(4096)
            if raw_resp:
                return json.loads(raw_resp.decode("utf-8").strip())
            return {"ok": True}
        except (socket.error, json.JSONDecodeError):
            # Stale socket file without running server
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass
            return None
        finally:
            client_sock.close()

    def start_listener(self) -> bool:
        """
        Binds and listens on the UNIX domain socket.
        Returns True if listener successfully started, or False if another daemon is running.
        """
        # First check if another live instance is listening
        test_resp = self.try_send_command_to_running_instance({"cmd": "ping"})
        if test_resp is not None:
            return False  # Another daemon is already running

        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass

        try:
            self.server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.server_sock.setblocking(False)
            self.server_sock.bind(self.socket_path)
            self.server_sock.listen(5)
            logger.info(f"IPC server listening on {self.socket_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to start IPC server: {e}")
            return False

    def handle_client_connection(self) -> None:
        """Called when server_sock has incoming client connection (via GLib.io_add_watch)."""
        if self.server_sock is None:
            return
        try:
            conn, _ = self.server_sock.accept()
            conn.settimeout(1.5)
            try:
                data = conn.recv(4096)
                if data:
                    cmd_obj = json.loads(data.decode("utf-8").strip())
                    resp_obj = {"ok": True}
                    if self.command_handler:
                        resp_obj = self.command_handler(cmd_obj) or {"ok": True}
                    conn.sendall(json.dumps(resp_obj).encode("utf-8") + b"\n")
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Error handling IPC connection: {e}")

    def cleanup(self) -> None:
        if self.server_sock:
            try:
                self.server_sock.close()
            except Exception:
                pass
            self.server_sock = None
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except Exception:
                pass
