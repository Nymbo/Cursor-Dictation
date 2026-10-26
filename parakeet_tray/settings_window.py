"""Settings. Changes save as you make them; a new microphone applies from the next dictation."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox, QKeySequenceEdit, QLabel,
                               QVBoxLayout, QWidget)

from . import DISPLAY_NAME, __version__, autostart
from .settings import Settings

LANGUAGES = (("English (Parakeet v2, most accurate)", "english"),
             ("Multilingual: 25 European languages (Parakeet v3)", "multilingual"))
RECOGNIZERS = (("Automatic (GPU if there is one)", "auto"), ("GPU (NVIDIA, CUDA)", "gpu"), ("CPU", "cpu"))


HOTKEY_HINT = "Tap to start and tap again to stop, or hold while you talk. Esc cancels."


def _muted_css() -> str:
    """Secondary text that stays readable in light and dark themes."""
    hints = QGuiApplication.styleHints()
    dark = hasattr(hints, "colorScheme") and hints.colorScheme().name == "Dark"
    return "color: #9AA0A6;" if dark else "color: #6B7280;"


def _note(text: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet(_muted_css())
    return lab


class SettingsWindow(QWidget):
    changed = Signal(str)           # the Settings field that changed

    def __init__(self, settings: Settings, list_mics, parent=None):
        super().__init__(parent)
        self.s = settings
        self.setWindowTitle("Settings")      # Qt appends " - Parakeet Tray"
        self.setMinimumWidth(460)
        self._loading = True
        lay = QVBoxLayout(self)

        box = QGroupBox("Dictation")
        f = QFormLayout(box)
        self.hotkey = QKeySequenceEdit(QKeySequence(self.s.hotkey))
        self.hotkey.setMaximumSequenceLength(1)
        self.hotkey.editingFinished.connect(lambda: self._set("hotkey", self.hotkey.keySequence().toString()))
        f.addRow("Hotkey:", self.hotkey)
        self.hotkey_note = _note(HOTKEY_HINT)
        f.addRow(self.hotkey_note)
        self.mic = QComboBox()
        self.mic.addItem("Windows default (follows changes)", "")
        for name in list_mics():
            self.mic.addItem(name, name)
        if self.s.mic and self.mic.findData(self.s.mic) < 0:
            self.mic.addItem(f"{self.s.mic} (not connected)", self.s.mic)
        self.mic.setCurrentIndex(max(0, self.mic.findData(self.s.mic)))
        self.mic.currentIndexChanged.connect(lambda: self._set("mic", self.mic.currentData()))
        f.addRow("Microphone:", self.mic)
        self.model = QComboBox()
        for label, value in LANGUAGES:
            self.model.addItem(label, value)
        self.model.setCurrentIndex(max(0, self.model.findData(self.s.model)))
        self.model.currentIndexChanged.connect(lambda: self._set("model", self.model.currentData()))
        f.addRow("Language:", self.model)
        self.recognizer = QComboBox()
        for label, value in RECOGNIZERS:
            self.recognizer.addItem(label, value)
        self.recognizer.setCurrentIndex(max(0, self.recognizer.findData(self.s.recognizer)))
        self.recognizer.currentIndexChanged.connect(lambda: self._set("recognizer", self.recognizer.currentData()))
        f.addRow("Speech model on:", self.recognizer)
        lay.addWidget(box)

        box = QGroupBox("Behaviour")
        v = QVBoxLayout(box)
        for name, label in (("sounds", "Play a tone when dictation starts and stops"),
                            ("trailing_space", "Add a space after each dictation"),
                            ("restore_clipboard", "Put back what was on the clipboard after pasting")):
            cb = QCheckBox(label)
            cb.setChecked(getattr(self.s, name))
            cb.toggled.connect(lambda on, n=name: self._set(n, on))
            v.addWidget(cb)
        self.autostart = QCheckBox("Start with Windows")
        self.autostart.setChecked(autostart.enabled())
        self.autostart.toggled.connect(autostart.set_enabled)
        v.addWidget(self.autostart)
        lay.addWidget(box)

        self.status = _note()
        lay.addWidget(self.status)
        lay.addWidget(_note(f"{DISPLAY_NAME} {__version__}: NVIDIA Parakeet TDT 0.6B, on this PC only."))
        lay.addStretch(1)
        self._loading = False

    def _set(self, name: str, value) -> None:
        if self._loading or getattr(self.s, name) == value:
            return
        setattr(self.s, name, value)
        self.changed.emit(name)

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def set_hotkey_failed(self, failed: bool) -> None:
        self.hotkey_note.setText("That hotkey is taken by another program; pick another." if failed else HOTKEY_HINT)
        self.hotkey_note.setStyleSheet("color: #E0A526;" if failed else _muted_css())
