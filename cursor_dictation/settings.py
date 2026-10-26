"""User settings: a dataclass persisted as JSON. Loading tolerates missing and unknown keys."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .paths import SETTINGS_FILE

logger = logging.getLogger(__name__)


@dataclass
class Settings:
    hotkey: str = "Ctrl+\\"         # tap to start and stop; hold to talk, release to stop
    mic: str = ""                   # "" = Windows default microphone (followed if it changes)
    recognizer: str = "auto"        # auto (GPU if available) | gpu | cpu
    model: str = "english"          # english (Parakeet v2) | multilingual (v3, 25 languages)
    sounds: bool = True             # tones on start, stop, cancel and error
    trailing_space: bool = True     # so consecutive dictations don't run together
    restore_clipboard: bool = True  # put back what was on the clipboard after pasting

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data) -> "Settings":
        if not isinstance(data, dict):
            return cls()
        base, kwargs = cls(), {}
        for f in fields(cls):
            if f.name in data and type(data[f.name]) is type(getattr(base, f.name)):
                kwargs[f.name] = data[f.name]
        return cls(**kwargs)


def load(path: Path = SETTINGS_FILE) -> Settings:
    try:
        return Settings.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return Settings()
    except Exception:
        logger.exception("Could not read %s; using defaults", path)
        return Settings()


def save(settings: Settings, path: Path = SETTINGS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)
