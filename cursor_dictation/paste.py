"""Put text at the cursor: clipboard + Ctrl+V, then (optionally) give the clipboard back.

Pasting is the one way to insert text that works in nearly every app, including ones that
mangle simulated typing. What was on the clipboard before (text, images, files: any format
held in global memory) is copied aside first and restored once the paste has landed, and
the dictated text is kept out of Windows' clipboard history while it passes through.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import time

from .hotkeys import MODIFIER_KEYS, key_down

logger = logging.getLogger(__name__)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL, VK_V = 0x11, 0x56
# Formats that are GDI handles or owner-drawn, not global memory: can't be copied byte for byte.
# Windows re-synthesizes CF_BITMAP and friends from the CF_DIB copy we do keep.
_HANDLE_FORMATS = {2, 3, 9, 14, 0x80, 0x82, 0x83, 0x8E}
SNAPSHOT_LIMIT = 64 << 20
RESTORE_DELAY_S = 0.4      # how long the target app gets to read the clipboard before it is restored

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.OpenClipboard.argtypes = [wt.HWND]
user32.OpenClipboard.restype = wt.BOOL
user32.CloseClipboard.restype = wt.BOOL
user32.EmptyClipboard.restype = wt.BOOL
user32.EnumClipboardFormats.argtypes = [wt.UINT]
user32.EnumClipboardFormats.restype = wt.UINT
user32.GetClipboardData.argtypes = [wt.UINT]
user32.GetClipboardData.restype = wt.HANDLE
user32.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
user32.SetClipboardData.restype = wt.HANDLE
user32.RegisterClipboardFormatW.argtypes = [wt.LPCWSTR]
user32.RegisterClipboardFormatW.restype = wt.UINT
user32.keybd_event.argtypes = [wt.BYTE, wt.BYTE, wt.DWORD, ctypes.c_size_t]
kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wt.HGLOBAL
kernel32.GlobalLock.argtypes = [wt.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wt.HGLOBAL]
kernel32.GlobalUnlock.restype = wt.BOOL
kernel32.GlobalSize.argtypes = [wt.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalFree.argtypes = [wt.HGLOBAL]
kernel32.GlobalFree.restype = wt.HGLOBAL

_EXCLUDE_HISTORY = user32.RegisterClipboardFormatW("ExcludeClipboardContentFromMonitorProcessing")

Snapshot = list[tuple[int, bytes]]


class _Clipboard:
    """`with _Clipboard():` opens the clipboard, retrying while another app holds it."""

    def __enter__(self):
        for _ in range(50):
            if user32.OpenClipboard(None):
                return self
            time.sleep(0.02)
        raise ctypes.WinError(ctypes.get_last_error())

    def __exit__(self, *exc):
        user32.CloseClipboard()


def _put(fmt: int, data: bytes) -> None:
    """Hand one format to the clipboard (which then owns the memory). Clipboard must be open."""
    h = kernel32.GlobalAlloc(GMEM_MOVEABLE, max(1, len(data)))
    if not h:
        raise ctypes.WinError(ctypes.get_last_error())
    ptr = kernel32.GlobalLock(h)
    if not ptr:
        kernel32.GlobalFree(h)
        raise ctypes.WinError(ctypes.get_last_error())
    ctypes.memmove(ptr, data, len(data))
    kernel32.GlobalUnlock(h)
    if not user32.SetClipboardData(fmt, h):
        kernel32.GlobalFree(h)
        raise ctypes.WinError(ctypes.get_last_error())


def snapshot() -> Snapshot | None:
    """Every global-memory format on the clipboard, or None if it can't all be kept."""
    out: Snapshot = []
    total = 0
    with _Clipboard():
        fmt = user32.EnumClipboardFormats(0)
        while fmt:
            if fmt not in _HANDLE_FORMATS:
                h = user32.GetClipboardData(fmt)
                size = kernel32.GlobalSize(h) if h else 0
                total += size
                if total > SNAPSHOT_LIMIT:
                    return None
                ptr = kernel32.GlobalLock(h) if size else None
                if ptr:
                    try:
                        out.append((fmt, ctypes.string_at(ptr, size)))
                    finally:
                        kernel32.GlobalUnlock(h)
            fmt = user32.EnumClipboardFormats(fmt)
    return out


def restore(saved: Snapshot) -> None:
    with _Clipboard():
        user32.EmptyClipboard()
        for fmt, data in saved:
            try:
                _put(fmt, data)
            except OSError:
                logger.debug("Could not restore clipboard format %d", fmt)


def set_text(text: str, transient: bool = False) -> None:
    """Replace the clipboard with text. transient: keep it out of clipboard history (Win+V)."""
    with _Clipboard():
        if not user32.EmptyClipboard():
            raise ctypes.WinError(ctypes.get_last_error())
        _put(CF_UNICODETEXT, text.encode("utf-16-le") + b"\x00\x00")
        if transient and _EXCLUDE_HISTORY:
            _put(_EXCLUDE_HISTORY, b"\x00\x00\x00\x00")


def wait_for_modifiers(timeout: float = 1.5) -> None:
    """Wait until Ctrl, Alt, Shift and Win are up, so our Ctrl+V isn't Ctrl+Alt+V."""
    end = time.monotonic() + timeout
    while any(key_down(vk) for vk in MODIFIER_KEYS) and time.monotonic() < end:
        time.sleep(0.015)


def send_paste() -> None:
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_V, 0, 0, 0)
    user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def insert_text(text: str, restore_clipboard: bool = True) -> None:
    """Paste text at the cursor of whatever window has focus. Blocks for about half a second."""
    if not text:
        return
    saved = None
    if restore_clipboard:
        try:
            saved = snapshot()
        except OSError:
            logger.warning("Could not read the clipboard; it won't be restored", exc_info=True)
    set_text(text, transient=saved is not None)
    wait_for_modifiers()
    time.sleep(0.03)
    send_paste()
    logger.info("Pasted %d chars", len(text))
    if saved is not None:
        time.sleep(RESTORE_DELAY_S)
        try:
            restore(saved)
        except OSError:
            logger.warning("Could not restore the clipboard", exc_info=True)
