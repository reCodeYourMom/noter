"""Petits composants partagés : pastilles, labels de section, filets, glyphes d'état, avatars."""
from __future__ import annotations

import html

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton

from noter.models import RecordingStatus
from noter.ui import icons, theme
from noter.ui.theme import MONO, Tokens, qcolor


def clear_layout(lay) -> None:
    """Vide un layout sans laisser de widgets fantômes à l'écran."""
    while lay.count():
        it = lay.takeAt(0)
        w = it.widget()
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif it.layout() is not None:
            clear_layout(it.layout())


def section_label(text: str, color: str | None = None) -> QLabel:
    """Titre de section en petites capitales, éventuellement précédé d'une pastille de couleur."""
    lab = QLabel()
    lab.setObjectName("section")
    if color:
        lab.setText(f'<span style="color:{color}">●</span>&nbsp;&nbsp;{html.escape(text.upper())}')
    else:
        lab.setText(text.upper())
    return lab


def dot_icon(color: str, diameter: int = 8) -> QIcon:
    """Petit disque plein (ex. le point blanc du bouton Enregistrer)."""
    ic = QIcon()
    for scale in (1, 2):
        px = (diameter + 2) * scale
        pm = QPixmap(px, px)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(scale, scale, diameter * scale, diameter * scale))
        p.end()
        pm.setDevicePixelRatio(scale)
        ic.addPixmap(pm)
    return ic


def hline() -> QFrame:
    f = QFrame()
    f.setObjectName("hline")
    f.setFrameShape(QFrame.Shape.NoFrame)
    return f


def vline() -> QFrame:
    f = QFrame()
    f.setObjectName("vline")
    f.setFrameShape(QFrame.Shape.NoFrame)
    return f


def mono_label(text: str, size: int = 12) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("metaMono")
    f = QFont(MONO)
    f.setPixelSize(size)
    lab.setFont(f)
    return lab


class Pill(QFrame):
    """Petite capsule : texte, éventuellement précédé d'un carré de couleur (projet)."""

    def __init__(self, text: str, kind: str = "pill", swatch: QColor | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName(kind)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(6)
        if swatch is not None:
            sw = QLabel()
            sw.setFixedSize(8, 8)
            sw.setStyleSheet(f"background: {swatch.name()}; border-radius: 2px;")
            lay.addWidget(sw)
        self.label = QLabel(text)
        lay.addWidget(self.label)


def tool_button(name: str, text: str = "", tokens: Tokens | None = None, ghost: bool = False, tip: str = "") -> QToolButton:
    t = tokens or theme.current()
    b = QToolButton()
    b.setIcon(icons.icon(name, t.ink_2, 14))
    if text:
        b.setText(text)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    if ghost:
        b.setObjectName("ghost")
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


# ─── Dessin ─────────────────────────────────────────────────────────


def paint_status_glyph(p: QPainter, cx: float, cy: float, status: RecordingStatus, t: Tokens, phase: float = 0.0) -> None:
    """Glyphe d'état 10px centré en (cx, cy). `phase` 0..1 anime le spinner et la pulsation."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = 5.0
    if status == RecordingStatus.DONE:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(t.ok))
        p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
    elif status in (RecordingStatus.TRANSCRIBING, RecordingStatus.SUMMARIZING, RecordingStatus.TRANSCRIBED):
        pen = QPen(qcolor(t.busy), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        start = int(-phase * 360 * 16)
        p.drawArc(QRectF(cx - r + 1, cy - r + 1, 2 * r - 2, 2 * r - 2), start, 270 * 16)
    elif status == RecordingStatus.RECORDED:
        p.setPen(QPen(qcolor(t.ink_4), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(cx - r + 1, cy - r + 1, 2 * r - 2, 2 * r - 2))
    elif status == RecordingStatus.FAILED:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(t.rec))
        p.translate(cx, cy)
        p.rotate(45)
        p.drawRoundedRect(QRectF(-3.6, -3.6, 7.2, 7.2), 1.2, 1.2)
    elif status == RecordingStatus.RECORDING:
        halo = qcolor(t.rec_soft)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        k = 2 + 3 * abs(0.5 - phase) * 2
        p.drawEllipse(QRectF(cx - r - k, cy - r - k, 2 * (r + k), 2 * (r + k)))
        p.setBrush(qcolor(t.rec))
        p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
    p.restore()


def paint_avatar(p: QPainter, rect: QRectF, name: str | None, t: Tokens, font_px: int = 9) -> None:
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(theme.speaker_color(t, name))
    p.drawEllipse(rect)
    f = QFont()
    f.setPixelSize(font_px)
    f.setWeight(QFont.Weight.DemiBold)
    p.setFont(f)
    p.setPen(QColor("#FFFFFF"))
    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, theme.initials(name))
    p.restore()
