"""
Antigravity Quota Monitor - Settings Repository
Handles atomic persistence of application settings.
"""

import json
import os
import tempfile
from typing import Dict, Any, Optional


DEFAULT_SETTINGS = {
    "target_host": "auto"
}


class SettingsRepository:
    def __init__(self, config_dir: Optional[str] = None):
        if config_dir is None:
            config_dir = os.path.expanduser("~/.config/antigravity-quota-monitor")
        self.config_dir = config_dir
        self.config_file = os.path.join(self.config_dir, "settings.json")

    def load_target_host(self, allowed_hosts: list) -> str:
        if os.path.isfile(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                saved = data.get("target_host", "auto")
                if saved in ("auto", "localhost") or saved in allowed_hosts:
                    return saved
            except Exception:
                pass
        return "auto"

    def save_target_host(self, target_host: str) -> None:
        os.makedirs(self.config_dir, exist_ok=True)
        data = {"target_host": target_host}

        # Write to temporary file in same directory and atomic rename
        try:
            with tempfile.NamedTemporaryFile("w", dir=self.config_dir, delete=False, encoding="utf-8") as tf:
                json.dump(data, tf, indent=2)
                temp_name = tf.name
            os.replace(temp_name, self.config_file)
        except Exception:
            pass
