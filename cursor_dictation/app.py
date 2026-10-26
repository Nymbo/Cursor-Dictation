"""Tray application: the hotkey, recording, transcription, pasting, settings, notifications.

One dictation at a time: idle -> recording -> transcribing -> idle. The hotkey starts a
recording; a quick tap leaves it running until the next press, holding it records until
release (push-to-talk). Esc cancels while recording.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from . import APP_NAME, DISPLAY_NAME, __version__
from . import settings as settings_mod
from .asr import Engine
from .capture import Recorder, list_microphones
from .hotkeys import HotkeyManager, key_down, parse
from .paste import insert_text
from .paths import LOG_DIR, ensure_dirs
from .sounds import Sounds
from .tray import Tray

logger = logging.getLogger(__name__)
INSTANCE_KEY = f"{APP_NAME}-{os.environ.get('USERNAME', 'user')}"
ERROR_ALREADY_EXISTS = 183
_instance_mutex = None
HOLD_S = 0.4               # held at least this long = push-to-talk: releasing stops
MIN_RECORDING_S = 0.25     # anything shorter is a slip of the finger
MAX_RECORDING_S = 15 * 60  # stop on our own after this; a forgotten recording shouldn't run all day


class Bridge(QObject):
    """Engine and transcription callbacks arrive on worker threads; these bring them to the UI thread."""

    engine_state = Signal(str, str)     # loading | ready | error, detail
    done = Signal(str, str)             # text, error


class App(QObject):
    def __init__(self, qapp: QApplication):
        super().__init__()
        self.qapp = qapp
        self.s = settings_mod.load()
        self.bridge = Bridge()
        self.tray = Tray()
        self.hotkeys = HotkeyManager()
        qapp.installNativeEventFilter(self.hotkeys)
        self.engine = Engine(on_state=self.bridge.engine_state.emit)
        self.recorder = Recorder()
        self.sounds = Sounds(self.s.sounds)
        self.settings_window = None
        self.state = "idle"                 # idle | recording | transcribing
        self.engine_status = ("loading", "")
        self.last_text = ""
        self._hotkey_ok = True
        self._pressed_at = 0.0
        self._vk = 0
        self._hold_timer = QTimer(self, interval=25, timeout=self._poll_hold)
        self._max_timer = QTimer(self, singleShot=True, interval=MAX_RECORDING_S * 1000, timeout=self._max_reached)
        self._save_timer = QTimer(self, singleShot=True, interval=600, timeout=self._save)

        self.bridge.engine_state.connect(self._on_engine_state)
        self.bridge.done.connect(self._on_done)
        t = self.tray
        t.toggle_requested.connect(self.toggle)
        t.cancel_requested.connect(self.cancel)
        t.copy_requested.connect(self.copy_last)
        t.settings_requested.connect(self.show_settings)
        t.logs_requested.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_DIR))))
        t.quit_requested.connect(self.quit)

    # -- lifecycle -----------------------------------------------------------------------
    def run(self) -> None:
        self.tray.show()
        self._register_hotkey()
        self._refresh_tray()
        self.engine.load(self.s.recognizer, self.s.model)
        if self._hotkey_ok:
            self.tray.notify(DISPLAY_NAME, f"Press {self.s.hotkey} to dictate: tap to start and stop, or hold "
                                           "while you talk.", ms=4000)

    def quit(self) -> None:
        if self.state == "recording":
            self.recorder.stop()
        self.hotkeys.clear()
        self._save()
        self.tray.hide()
        self.qapp.quit()

    def _save(self) -> None:
        try:
            settings_mod.save(self.s)
        except Exception:
            logger.exception("Could not save settings")

    # -- dictation -----------------------------------------------------------------------
    def _on_hotkey(self) -> None:
        if self.state == "recording":
            self.stop()
        elif self.state == "idle" and self.start():
            self._pressed_at = time.monotonic()
            self._hold_timer.start()

    def toggle(self) -> None:
        if self.state == "recording":
            self.stop()
        elif self.state == "idle":
            self.start()

    def start(self) -> bool:
        if self.state != "idle":
            return False
        if self.engine_status[0] == "error":
            self.sounds.play("error")
            self.tray.notify("Speech model unavailable", f"{self.engine.error}\nTrying to load it again.", error=True)
            self.engine.load(self.s.recognizer, self.s.model)
            return False
        try:
            self.recorder.start(self.s.mic)
        except Exception as exc:
            logger.exception("Could not open the microphone")
            self.sounds.play("error")
            self.tray.notify("Could not open the microphone", str(exc), error=True)
            return False
        self.sounds.play("start")
        self.hotkeys.bind("cancel", "Esc", self.cancel)
        self._max_timer.start()
        self._set_state("recording")
        return True

    def stop(self) -> None:
        if self.state != "recording":
            return
        self._end_recording()
        audio = self.recorder.stop()
        if audio.size < MIN_RECORDING_S * 16000:
            self.sounds.play("cancel")
            self._set_state("idle")
            return
        self.sounds.play("stop")
        self._set_state("transcribing")
        threading.Thread(target=self._transcribe, args=(audio,), name="dictation", daemon=True).start()

    def cancel(self) -> None:
        if self.state != "recording":
            return
        self._end_recording()
        self.recorder.stop()
        self.sounds.play("cancel")
        logger.info("Dictation cancelled")
        self._set_state("idle")

    def _end_recording(self) -> None:
        self._hold_timer.stop()
        self._max_timer.stop()
        self.hotkeys.unbind("cancel")

    def _poll_hold(self) -> None:
        if self._vk and key_down(self._vk):
            return
        self._hold_timer.stop()
        if self.state == "recording" and time.monotonic() - self._pressed_at >= HOLD_S:
            self.stop()

    def _max_reached(self) -> None:
        self.tray.notify(DISPLAY_NAME, f"Stopped after {MAX_RECORDING_S // 60} minutes.")
        self.stop()

    def _transcribe(self, audio) -> None:
        t0 = time.perf_counter()
        try:
            text = self.engine.transcribe(audio)
            logger.info("%.1f s of audio -> %d chars in %.2f s", audio.size / 16000, len(text),
                        time.perf_counter() - t0)
            if text:
                insert_text(text + (" " if self.s.trailing_space else ""), self.s.restore_clipboard)
            self.bridge.done.emit(text, "")
        except Exception as exc:
            logger.exception("Dictation failed")
            self.bridge.done.emit("", str(exc))

    def _on_done(self, text: str, error: str) -> None:
        self._set_state("idle")
        if error:
            self.sounds.play("error")
            self.tray.notify("Dictation failed", error, error=True)
        elif not text:
            self.tray.notify(DISPLAY_NAME, "Didn't catch anything.", ms=2000)
        else:
            self.last_text = text
            self.tray.set_has_last(True)

    def copy_last(self) -> None:
        if self.last_text:
            QGuiApplication.clipboard().setText(self.last_text)

    # -- engine --------------------------------------------------------------------------
    def _on_engine_state(self, state: str, detail: str) -> None:
        self.engine_status = (state, detail)
        if state == "loading" and detail:
            self.tray.notify(DISPLAY_NAME, detail[0].upper() + detail[1:] + ".", ms=5000)
        elif state == "error":
            self.tray.notify("Speech model unavailable", detail, error=True)
        if self.settings_window:
            self.settings_window.set_status(self._engine_text())
        self._refresh_tray()

    def _engine_text(self) -> str:
        state, detail = self.engine_status
        if state == "ready":
            return f"Speech model ready on the {detail}."
        if state == "error":
            return f"Speech model unavailable: {detail}"
        return "Loading the speech model" + (f": {detail}." if detail else "…")

    # -- tray and settings ---------------------------------------------------------------
    def _set_state(self, state: str) -> None:
        self.state = state
        self._refresh_tray()

    def _refresh_tray(self) -> None:
        if self.state != "idle":
            shown = self.state
        else:
            shown = {"ready": "idle", "loading": "loading", "error": "error"}[self.engine_status[0]]
        detail = self.engine_status[1] if shown in ("loading", "error") else ""
        if shown == "idle" and self.engine.device:
            detail = f"Parakeet on the {self.engine.device}"
        if not self._hotkey_ok:
            detail = (detail + "\n" if detail else "") + f"{self.s.hotkey} is taken; change it in Settings"
        self.tray.set_state(shown, detail, self.s.hotkey if self._hotkey_ok else "")

    def show_settings(self) -> None:
        if self.settings_window is None:
            from .settings_window import SettingsWindow

            self.settings_window = SettingsWindow(self.s, list_microphones)
            self.settings_window.changed.connect(self._on_settings_changed)
        self.settings_window.set_hotkey_failed(not self._hotkey_ok)
        self.settings_window.set_status(self._engine_text())
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def _on_settings_changed(self, name: str) -> None:
        if name == "hotkey":
            self._register_hotkey()
            self.settings_window.set_hotkey_failed(not self._hotkey_ok)
            self._refresh_tray()
        elif name in ("recognizer", "model"):
            self.engine.load(self.s.recognizer, self.s.model)
        elif name == "sounds":
            self.sounds.enabled = self.s.sounds
        self._save_timer.start()

    def _register_hotkey(self) -> None:
        parsed = parse(self.s.hotkey)
        self._vk = parsed[1] if parsed else 0
        self._hotkey_ok = self.hotkeys.bind("dictate", self.s.hotkey, self._on_hotkey)
        if not self._hotkey_ok:
            self.tray.notify(DISPLAY_NAME, f"{self.s.hotkey or 'The hotkey'} is taken by another program; "
                                           "pick another in Settings.", error=True)


def _setup_logging() -> None:
    ensure_dirs()
    handlers: list[logging.Handler] = [
        RotatingFileHandler(LOG_DIR / "cursor-dictation.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                        handlers=handlers)


def main() -> int:
    _setup_logging()
    qapp = QApplication(sys.argv)
    qapp.setApplicationName(APP_NAME)
    qapp.setApplicationDisplayName(DISPLAY_NAME)
    qapp.setQuitOnLastWindowClosed(False)

    # Single instance: a second launch opens the first one's settings. A named mutex decides
    # who is first (Windows lets two processes listen on one pipe name, so the socket can't).
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    global _instance_mutex      # never closed: Windows releases it when this process exits
    _instance_mutex = kernel32.CreateMutexW(None, False, f"Local\\{INSTANCE_KEY}")
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        probe = QLocalSocket()
        for _ in range(20):          # the first copy may still be starting up
            probe.connectToServer(INSTANCE_KEY)
            if probe.waitForConnected(250):
                probe.write(b"settings")
                probe.waitForBytesWritten(300)
                break
            time.sleep(0.25)
        return 0
    server = QLocalServer()
    server.listen(INSTANCE_KEY)

    logger.info("%s %s starting", DISPLAY_NAME, __version__)
    app = App(qapp)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), app.show_settings()))
    app.run()
    return qapp.exec()
