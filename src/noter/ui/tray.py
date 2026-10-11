"""Icône de barre de menu (QSystemTrayIcon)."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from noter.models import format_timestamp
from noter.ui.style import tray_icon


class Tray(QObject):
    record_requested = Signal(bool)  # with_system_audio
    stop_requested = Signal()
    open_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.icon = QSystemTrayIcon(tray_icon(False), self)
        self.icon.setToolTip("Noter")
        menu = QMenu()
        self.a_rec_sys = QAction("Enregistrer (micro + système)", menu)
        self.a_rec_sys.triggered.connect(lambda: self.record_requested.emit(True))
        self.a_rec_mic = QAction("Enregistrer (micro seul)", menu)
        self.a_rec_mic.triggered.connect(lambda: self.record_requested.emit(False))
        self.a_stop = QAction("Arrêter l'enregistrement", menu)
        self.a_stop.triggered.connect(self.stop_requested.emit)
        self.a_stop.setEnabled(False)
        self.a_status = QAction("Traitement : inactif", menu)
        self.a_status.setEnabled(False)
        a_open = QAction("Ouvrir Noter", menu)
        a_open.triggered.connect(self.open_requested.emit)
        a_quit = QAction("Quitter", menu)
        a_quit.triggered.connect(self.quit_requested.emit)
        for a in (self.a_rec_sys, self.a_rec_mic, self.a_stop):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(a_open)
        menu.addAction(self.a_status)
        menu.addSeparator()
        menu.addAction(a_quit)
        self._menu = menu
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._activated)
        self.icon.show()

    def _activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_requested.emit()

    def set_recording(self, recording: bool) -> None:
        self.icon.setIcon(tray_icon(recording))
        self.a_rec_sys.setEnabled(not recording)
        self.a_rec_mic.setEnabled(not recording)
        self.a_stop.setEnabled(recording)
        if not recording:
            self.icon.setToolTip("Noter")

    def set_elapsed(self, seconds: float) -> None:
        self.icon.setToolTip(f"Noter — REC {format_timestamp(seconds)}")
        self.a_stop.setText(f"Arrêter l'enregistrement ({format_timestamp(seconds)})")

    def set_status(self, text: str) -> None:
        self.a_status.setText(f"Traitement : {text}")

    def message(self, title: str, body: str) -> None:
        if self.icon.supportsMessages():
            self.icon.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information, 4000)
