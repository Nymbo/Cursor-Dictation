"""Where the app keeps settings, logs and sounds (all outside the repo).

The speech model is not here: onnx-asr downloads it into the Hugging Face cache.
"""

import os
from pathlib import Path

from . import APP_NAME


def _env_dir(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / fallback)


# Settings roam with the user profile; logs and generated sounds are machine-local.
CONFIG_DIR = _env_dir("APPDATA", "AppData/Roaming") / APP_NAME
DATA_DIR = _env_dir("LOCALAPPDATA", "AppData/Local") / APP_NAME
LOG_DIR = DATA_DIR / "logs"
SOUNDS_DIR = DATA_DIR / "sounds"
SETTINGS_FILE = CONFIG_DIR / "settings.json"


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, LOG_DIR, SOUNDS_DIR):
        d.mkdir(parents=True, exist_ok=True)
