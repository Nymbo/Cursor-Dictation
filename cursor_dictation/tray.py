"""Tray icon and menu. A click opens Settings; dictation itself lives on the hotkey."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import DISPLAY_NAME

STATE_COLORS = {"loading": "#E0A526", "idle": "#2F9E8F", "recording": "#E5484D",
                "transcribing": "#3E7BFA", "error": "#7C828C"}
STATE_LABELS = {"loading": "loading the speech model", "idle": "ready", "recording": "listening",
                "transcribing": "transcribing", "error": "speech model unavailable"}


def make_icon(state: str) -> QIcon:
    """A rounded tile with a white microphone; recording fills the capsule in."""
    icon = QIcon()
    color = QColor(STATE_COLORS.get(state, STATE_COLORS["idle"]))
    for size in (16, 20, 24, 32, 48, 64):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(0.5, 0.5, size - 1, size - 1), size * 0.22, size * 0.22)
        pen = QPen(QColor("white"))
        pen.setWidthF(max(1.4, size * 0.085))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        cx = size / 2
        capsule = QRectF(cx - size * 0.13, size * 0.16, size * 0.26, size * 0.42)
        p.setBrush(QColor("white") if state == "recording" else Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(capsule, size * 0.13, size * 0.13)
        p.setBrush(Qt.BrushStyle.NoBrush)
        cup = QPainterPath()
        cup.arcMoveTo(QRectF(cx - size * 0.24, size * 0.2, size * 0.48, size * 0.5), 180)
        cup.arcTo(QRectF(cx - size * 0.24, size * 0.2, size * 0.48, size * 0.5), 180, 180)
        p.drawPath(cup)
        p.drawLine(int(cx), int(size * 0.7), int(cx), int(size * 0.84))
        p.end()
        icon.addPixmap(pm)
    return icon


class Tray(QObject):
    toggle_requested = Signal()
    cancel_requested = Signal()
    copy_requested = Signal()
    settings_requested = Signal()
    logs_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.icons = {s: make_icon(s) for s in STATE_COLORS}
        self.tray = QSystemTrayIcon(self.icons["loading"])
        m = self.menu = QMenu()
        self.header = m.addAction(DISPLAY_NAME)
        self.header.setEnabled(False)
        m.addSeparator()
        self.toggle_action = m.addAction("Start dictation", self.toggle_requested.emit)
        self.cancel_action = m.addAction("Cancel\tEsc", self.cancel_requested.emit)
        self.copy_action = m.addAction("Copy last dictation", self.copy_requested.emit)
        self.copy_action.setEnabled(False)
        m.addSeparator()
        m.addAction("Settings…", self.settings_requested.emit)
        m.addAction("Open log folder", self.logs_requested.emit)
        m.addSeparator()
        m.addAction("Exit", self.quit_requested.emit)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(self._activated)
        self.set_state("loading")

    def show(self) -> None:
        self.tray.show()

    def hide(self) -> None:
        self.tray.hide()

    def set_state(self, state: str, detail: str = "", hotkey: str = "") -> None:
        self.tray.setIcon(self.icons.get(state, self.icons["idle"]))
        self.tray.setToolTip(f"{DISPLAY_NAME}: {STATE_LABELS.get(state, state)}" + (f"\n{detail}" if detail else ""))
        key = f"\t{hotkey}" if hotkey else ""
        self.toggle_action.setText(("Stop dictation" if state == "recording" else "Start dictation") + key)
        self.toggle_action.setEnabled(state != "transcribing")
        self.cancel_action.setEnabled(state == "recording")

    def set_has_last(self, has: bool) -> None:
        self.copy_action.setEnabled(has)

    def notify(self, title: str, message: str, error: bool = False, ms: int = 6000) -> None:
        icon = QSystemTrayIcon.MessageIcon.Warning if error else QSystemTrayIcon.MessageIcon.Information
        self.tray.showMessage(title, message, icon, ms)

    def _activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.settings_requested.emit()
