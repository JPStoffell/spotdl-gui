"""Small JSON-backed settings store for SpotDL UI.

Keeps the handful of preferences (output folder, format, bitrate, ...) that
should survive between runs. Deliberately tiny - no schema migrations, no
external dependency, just a dict written to
``~/.config/spotdl-ui/config.json``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

if sys.platform == "win32":
    _config_root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
else:
    _config_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))

CONFIG_DIR = _config_root / "spotdl-ui"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_OUTPUT_DIR = str(Path.home() / "Music" / "SpotDL")

DEFAULTS: Dict[str, Any] = {
    "output_dir": DEFAULT_OUTPUT_DIR,
    "format": "mp3",
    "bitrate": "320k",
    "threads": 4,
    "overwrite": "skip",
}


def load() -> Dict[str, Any]:
    """Load settings, falling back to defaults for anything missing/invalid."""

    settings = dict(DEFAULTS)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
            saved = json.load(fh)
        if isinstance(saved, dict):
            settings.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return settings


def save(settings: Dict[str, Any]) -> None:
    """Persist settings, ignoring failures (best-effort only)."""

    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump({k: settings.get(k, v) for k, v in DEFAULTS.items()}, fh, indent=2)
    except OSError:
        pass
