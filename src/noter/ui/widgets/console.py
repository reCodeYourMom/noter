"""Console d'enregistrement : voyant, compteur, titre, vumètres, bouton Arrêter."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from noter.models import Recording
from noter.ui import icons, theme
from noter.ui.theme import MONO
from noter.ui.widgets.timeline import LevelMeter


def _timecode(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


class RecordingConsole(QWidget):
    stop_requested = Signal()
    title_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        t = theme.current()
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(0)
        root.addStretch(2)

        lamp_row = QHBoxLayout()
        lamp_row.setSpacing(10)
        lamp_row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.lamp = QLabel()
        self.lamp.setFixedSize(20, 20)
        self.lamp_text = QLabel("ENREGISTREMENT")
        self.lamp_text.setObjectName("lamp")
        lamp_row.addWidget(self.lamp)
        lamp_row.addWidget(self.lamp_text)
        root.addLayout(lamp_row)
        root.addSpacing(22)

        self.tc = QLabel("00:00:00")
        self.tc.setObjectName("timecode")
        f = QFont(MONO)
        f.setPixelSize(72)
        f.setWeight(QFont.Weight.Medium)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -2)
        self.tc.setFont(f)
        self.tc.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(self.tc)
        root.addSpacing(22)

        self.title = QLineEdit()
        self.title.setObjectName("recTitle")
        self.title.setPlaceholderText("Titre (optionnel), ex. Point client ACME")
        self.title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.title.setFixedWidth(380)
        self.title.editingFinished.connect(lambda: self.title_changed.emit(self.title.text().strip()))
        root.addWidget(self.title, 0, Qt.AlignmentFlag.AlignHCenter)
        root.addSpacing(28)

        meters = QWidget()
        meters.setFixedWidth(440)
        grid = QGridLayout(meters)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        self.mic_lab = self._meter_label("MIC")
        self.sys_lab = self._meter_label("SYS")
        self.mic = LevelMeter()
        self.sys = LevelMeter()
        grid.addWidget(self.mic_lab, 0, 0)
        grid.addWidget(self.mic, 0, 1)
        grid.addWidget(self.sys_lab, 1, 0)
        grid.addWidget(self.sys, 1, 1)
        root.addWidget(meters, 0, Qt.AlignmentFlag.AlignHCenter)
        root.addSpacing(12)

        self.source = QLabel("")
        self.source.setObjectName("meta")
        self.source.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(self.source)

        self.silence = QLabel(
            "Aucun son capté par le micro. macOS bloque sans doute l’accès : "
            "Réglages Système → Confidentialité et sécurité → Micro → autorise Noter, puis relance l’app."
        )
        self.silence.setObjectName("error")
        self.silence.setWordWrap(True)
        self.silence.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.silence.setFixedWidth(440)
        self.silence.hide()
        root.addSpacing(10)
        root.addWidget(self.silence, 0, Qt.AlignmentFlag.AlignHCenter)
        root.addSpacing(28)

        self.stop = QPushButton("  Arrêter")
        self.stop.setObjectName("stop")
        self.stop.setIcon(icons.icon("stop", "#FFFFFF", 12))
        self.stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop.clicked.connect(self.stop_requested.emit)
        glow = QGraphicsDropShadowEffect(self.stop)  # halo corail : le seul bouton qui compte pendant un call
        glow.setBlurRadius(28)
        glow.setOffset(0, 6)
        glow.setColor(theme.soft(t.rec, 0.45))
        self.stop.setGraphicsEffect(glow)
        root.addWidget(self.stop, 0, Qt.AlignmentFlag.AlignHCenter)
        root.addSpacing(14)

        hint = QLabel("⌘. pour arrêter · l’enregistrement continue si tu fermes la fenêtre")
        hint.setObjectName("gen")
        hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(hint)
        root.addStretch(3)

        self._blink = QTimer(self)
        self._blink.setInterval(600)
        self._blink.timeout.connect(self._toggle_lamp)
        self._lamp_on = True
        self._set_lamp(True)

    def _meter_label(self, text: str) -> QLabel:
        lab = QLabel(text)
        f = QFont(MONO)
        f.setPixelSize(11)
        lab.setFont(f)
        lab.setObjectName("meta")
        lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lab.setFixedWidth(40)
        return lab

    def _set_lamp(self, on: bool) -> None:
        t = theme.current()
        halo = t.rec_soft if on else "transparent"
        self.lamp.setStyleSheet(f"background: {t.rec if on else t.rec_soft}; border: 4px solid {halo}; border-radius: 10px;")

    def _toggle_lamp(self) -> None:
        self._lamp_on = not self._lamp_on
        self._set_lamp(self._lamp_on)

    def begin(self, rec: Recording, source_text: str, with_system: bool = True) -> None:
        self.title.setText(rec.title or "")
        self.tc.setText("00:00:00")
        self.source.setText(source_text)
        self.sys_lab.setVisible(with_system)
        self.sys.setVisible(with_system)
        self.mic.set_level(0)
        self.sys.set_level(0)
        self._mic_peak = 0.0
        self.silence.hide()
        self._blink.start()

    def end(self) -> None:
        self._blink.stop()
        self._set_lamp(True)

    SILENCE_AFTER_S = 3.0

    def tick(self, elapsed: float, levels: dict) -> None:
        self.tc.setText(_timecode(elapsed))
        mic = levels.get("MIC", 0.0)
        self.mic.set_level(mic)
        self.sys.set_level(levels.get("SYS", 0.0))
        # Un vrai micro a toujours un bruit de fond : un zéro parfait signifie accès refusé
        self._mic_peak = max(getattr(self, "_mic_peak", 0.0), mic)
        self.silence.setVisible(elapsed >= self.SILENCE_AFTER_S and self._mic_peak == 0.0)
