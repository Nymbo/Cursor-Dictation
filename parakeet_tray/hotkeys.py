"""Global hotkeys via Win32 RegisterHotKey, delivered through Qt's native event filter.

Hotkey strings use QKeySequence's portable text form, e.g. "Ctrl+\\" or "Ctrl+Shift+F9".
RegisterHotKey only reports presses; `key_down` lets the app see when a key is released.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter

logger = logging.getLogger(__name__)

WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN = 0x10, 0x11, 0x12, 0x5B, 0x5C
MODIFIER_KEYS = (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN)

_MODS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT,
         "meta": MOD_WIN, "win": MOD_WIN}
_NAMED = {"space": 0x20, "tab": 0x09, "esc": 0x1B, "escape": 0x1B, "return": 0x0D, "enter": 0x0D,
          "backspace": 0x08, "ins": 0x2D, "insert": 0x2D, "del": 0x2E, "delete": 0x2E,
          "home": 0x24, "end": 0x23, "pgup": 0x21, "pgdown": 0x22, "left": 0x25, "up": 0x26,
          "right": 0x27, "down": 0x28, "pause": 0x13, "print": 0x2C, "capslock": 0x14, "scrolllock": 0x91,
          "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC, ";": 0xBA,
          "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF}


def parse(text: str) -> tuple[int, int] | None:
    """'Ctrl+Alt+C' -> (modifiers, virtual-key). None if empty or unparseable."""
    if not text or not text.strip():
        return None
    text = text.replace(" ", "")
    if text.endswith("++"):          # the "+" key itself, e.g. "Ctrl++" (VK_OEM_PLUS)
        text = text[:-1] + "="
    mods, key = 0, None
    for part in text.split("+"):
        low = part.lower()
        if low in _MODS:
            mods |= _MODS[low]
        elif len(part) == 1 and part.isalnum():
            key = ord(part.upper())
        elif low.startswith("f") and low[1:].isdigit() and 1 <= int(low[1:]) <= 24:
            key = 0x70 + int(low[1:]) - 1
        elif low.startswith("num") and low[3:].isdigit():
            key = 0x60 + int(low[3:])
        elif low in _NAMED:
            key = _NAMED[low]
        else:
            return None
    if key is None:
        return None
    return mods, key


def key_down(vk: int) -> bool:
    """Is this key held right now (whichever window has focus)?"""
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


class HotkeyManager(QAbstractNativeEventFilter):
    """Owns the registered hotkeys, by name. Install with app.installNativeEventFilter(manager)."""

    def __init__(self):
        super().__init__()
        self._ids: dict[str, int] = {}
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._next_id = 0xB100

    def bind(self, name: str, text: str, callback: Callable[[], None]) -> bool:
        """(Re)register one hotkey. False if the text doesn't parse or another program has it."""
        self.unbind(name)
        parsed = parse(text)
        if parsed is None:
            return False
        mods, vk = parsed
        hk_id = self._next_id
        self._next_id += 1
        if not ctypes.windll.user32.RegisterHotKey(None, hk_id, mods | MOD_NOREPEAT, vk):
            logger.warning("Hotkey %s (%s) is taken by another program", name, text)
            return False
        self._ids[name] = hk_id
        self._callbacks[hk_id] = callback
        logger.info("Hotkey %s = %s", name, text)
        return True

    def unbind(self, name: str) -> None:
        hk_id = self._ids.pop(name, None)
        if hk_id is not None:
            ctypes.windll.user32.UnregisterHotKey(None, hk_id)
            self._callbacks.pop(hk_id, None)

    def clear(self) -> None:
        for name in list(self._ids):
            self.unbind(name)

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG" or event_type == "windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam in self._callbacks:
                try:
                    self._callbacks[msg.wParam]()
                except Exception:
                    logger.exception("Hotkey callback failed")
                return True, 0
        return False, 0
