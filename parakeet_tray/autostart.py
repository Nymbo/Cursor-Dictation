"""Start with Windows: a value under HKCU\\...\\Run that launches run.pyw with pythonw."""

from __future__ import annotations

import logging
import sys
import winreg
from pathlib import Path

from . import DISPLAY_NAME

logger = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
PROJECT_DIR = Path(__file__).resolve().parent.parent


def command() -> str:
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    return f'"{pythonw if pythonw.exists() else exe}" "{PROJECT_DIR / "run.pyw"}"'


def enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, DISPLAY_NAME)
            return True
    except OSError:
        return False


def set_enabled(on: bool) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, DISPLAY_NAME, 0, winreg.REG_SZ, command())
            else:
                try:
                    winreg.DeleteValue(k, DISPLAY_NAME)
                except FileNotFoundError:
                    pass
    except OSError:
        logger.exception("Could not change the startup entry")
