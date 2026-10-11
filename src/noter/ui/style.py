"""Couleurs, icônes dessinées et feuille de style minimale (le style natif fait le reste)."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

from noter.models import RecordingStatus

STATUS_COLOR = {
    RecordingStatus.RECORDING: "#e5484d",
    RecordingStatus.RECORDED: "#8d8d8d",
    RecordingStatus.TRANSCRIBING: "#3b82f6",
    RecordingStatus.TRANSCRIBED: "#3b82f6",
    RecordingStatus.SUMMARIZING: "#3b82f6",
    RecordingStatus.DONE: "#22a06b",
    RecordingStatus.FAILED: "#e5484d",
}

STATUS_LABEL = {
    RecordingStatus.RECORDING: "Enregistrement",
    RecordingStatus.RECORDED: "À traiter",
    RecordingStatus.TRANSCRIBING: "Transcription…",
    RecordingStatus.TRANSCRIBED: "Transcrit",
    RecordingStatus.SUMMARIZING: "Résumé…",
    RecordingStatus.DONE: "Prêt",
    RecordingStatus.FAILED: "Échec",
}

ACCENT = "#e5484d"

QSS = """
QLabel#title { font-size: 20px; font-weight: 600; }
QLabel#meta { color: palette(mid); }
QLabel#section { font-size: 12px; font-weight: 600; color: palette(mid); letter-spacing: 1px; margin-top: 8px; }
QLabel#tldr { font-size: 14px; padding: 10px 12px; border-left: 3px solid #e5484d; background: palette(alternate-base); border-radius: 4px; }
QLabel#empty { color: palette(mid); font-size: 14px; }
QFrame#recbar { background: #e5484d; border-radius: 6px; }
QFrame#recbar QLabel { color: white; font-weight: 600; }
QFrame#recbar QPushButton { color: white; background: rgba(0,0,0,0.25); border: none; padding: 4px 12px; border-radius: 4px; }
QFrame#recbar QPushButton:hover { background: rgba(0,0,0,0.4); }
QListView#segments::item { padding: 4px; }
QLineEdit#titleEdit { font-size: 20px; font-weight: 600; border: none; background: transparent; }
QLineEdit#titleEdit:focus { border-bottom: 1px solid palette(highlight); }
"""


def dot_icon(color: str, size: int = 16, ring: bool = False) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    m = size * 0.2
    p.drawEllipse(QRectF(m, m, size - 2 * m, size - 2 * m))
    if ring:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QColor(color))
        p.drawEllipse(QRectF(1, 1, size - 2, size - 2))
    p.end()
    return QIcon(pm)


def tray_icon(recording: bool, size: int = 22) -> QIcon:
    """Icône de barre de menu : cercle plein (idle, template) ou point rouge (REC)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if recording:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(ACCENT))
        p.drawEllipse(QRectF(4, 4, size - 8, size - 8))
    else:
        p.setPen(QColor(0, 0, 0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        pen = p.pen()
        pen.setWidthF(1.8)
        p.setPen(pen)
        p.drawEllipse(QRectF(3, 3, size - 6, size - 6))
        p.setBrush(QColor(0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(size / 2 - 3, size / 2 - 3, 6, 6))
    p.end()
    icon = QIcon(pm)
    icon.setIsMask(not recording)  # template : s'adapte au mode sombre de la barre de menu
    return icon
