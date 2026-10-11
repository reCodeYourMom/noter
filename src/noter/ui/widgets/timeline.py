"""La signature : timeline audio (onde + couloir des speakers + règle) et vumètres."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QFont, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QSizePolicy, QWidget

from noter.models import Segment, format_timestamp
from noter.ui import theme
from noter.ui.theme import MONO, qcolor


class WaveformTimeline(QWidget):
    seek_requested = Signal(float)  # secondes

    WAVE_H = 64
    LANE_H = 4
    RULER_H = 16

    def __init__(self, parent=None):
        super().__init__(parent)
        self.peaks: list[float] = []
        self.duration = 0.0
        self.position = 0.0
        self.segments: list[Segment] = []
        self.markers: list[float] = []  # résultats de recherche, etc.
        self.setMinimumHeight(self.WAVE_H + 4 + self.LANE_H + 4 + self.RULER_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(False)

    def set_data(self, peaks: list[float] | None, duration: float, segments: list[Segment]) -> None:
        self.peaks = peaks or []
        self.duration = max(0.0, duration)
        self.segments = segments
        self.position = 0.0
        self.update()

    def set_position(self, seconds: float) -> None:
        self.position = max(0.0, min(self.duration, seconds))
        self.update()

    def set_markers(self, seconds: list[float]) -> None:
        self.markers = seconds
        self.update()

    def _seek_from_x(self, x: float) -> None:
        if self.duration <= 0 or self.width() <= 0:
            return
        frac = min(1.0, max(0.0, x / self.width()))
        self.seek_requested.emit(frac * self.duration)

    def mousePressEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._seek_from_x(e.position().x())

    def mouseMoveEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._seek_from_x(e.position().x())

    def paintEvent(self, _e: QPaintEvent) -> None:  # noqa: N802
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        wave = QRectF(0, 0, w, self.WAVE_H)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(t.panel_2))
        p.drawRoundedRect(wave, 6, 6)

        frac = (self.position / self.duration) if self.duration > 0 else 0.0
        played_x = frac * w
        if self.peaks:
            n = len(self.peaks)
            gap = 2.0
            bw = max(1.0, (w - gap * n) / n)
            if bw < 1.5:  # trop de barres pour la largeur : on sous-échantillonne
                step = max(1, int(n / (w / 3.5)))
                peaks = [max(self.peaks[i : i + step]) for i in range(0, n, step)]
                n = len(peaks)
                bw = max(1.0, (w - gap * n) / n)
            else:
                peaks = self.peaks
            for i, v in enumerate(peaks):
                h = max(3.0, v * (self.WAVE_H - 12))
                x = i * (bw + gap) + 1
                y = (self.WAVE_H - h) / 2
                p.setBrush(qcolor(t.ink) if x <= played_x else qcolor(t.ink_4))
                p.drawRoundedRect(QRectF(x, y, bw, h), 1.5, 1.5)
        else:
            f = QFont()
            f.setPixelSize(11)
            p.setFont(f)
            p.setPen(qcolor(t.ink_4))
            p.drawText(wave, Qt.AlignmentFlag.AlignCenter, "Onde non disponible")

        # Couloir des speakers
        lane_y = self.WAVE_H + 4
        p.setPen(Qt.PenStyle.NoPen)
        if self.segments and self.duration > 0:
            for s in self.segments:
                x0 = s.start / self.duration * w
                x1 = max(x0 + 1.5, s.end / self.duration * w)
                p.setBrush(theme.speaker_color(t, s.speaker))
                p.drawRect(QRectF(x0, lane_y, x1 - x0, self.LANE_H))
        else:
            p.setBrush(qcolor(t.inset))
            p.drawRoundedRect(QRectF(0, lane_y, w, self.LANE_H), 2, 2)

        # Marqueurs de recherche
        for m in self.markers:
            if self.duration > 0:
                x = m / self.duration * w
                p.setBrush(qcolor(t.busy))
                p.drawRoundedRect(QRectF(x - 1.5, self.WAVE_H - 6, 3, 6), 1, 1)

        # Règle
        ruler_y = lane_y + self.LANE_H + 4
        f = QFont(MONO)
        f.setPixelSize(10)
        p.setFont(f)
        p.setPen(qcolor(t.ink_4))
        if self.duration > 0:
            ticks = 4
            for i in range(ticks + 1):
                sec = self.duration * i / ticks
                label = format_timestamp(sec)
                align = Qt.AlignmentFlag.AlignLeft if i == 0 else (Qt.AlignmentFlag.AlignRight if i == ticks else Qt.AlignmentFlag.AlignHCenter)
                x = w * i / ticks
                rect = QRectF(x - 40, ruler_y, 80, self.RULER_H)
                if i == 0:
                    rect = QRectF(0, ruler_y, 80, self.RULER_H)
                elif i == ticks:
                    rect = QRectF(w - 80, ruler_y, 80, self.RULER_H)
                p.drawText(rect, align | Qt.AlignmentFlag.AlignVCenter, label)

        # Tête de lecture
        if self.duration > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(t.rec))
            p.drawRect(QRectF(played_x - 0.5, 0, 1, lane_y + self.LANE_H))
            p.drawEllipse(QRectF(played_x - 3.5, -1, 7, 7))
        p.end()


class LevelMeter(QWidget):
    """Vumètre à segments : vert, ambre vers la fin, rouge sur les derniers."""

    def __init__(self, segments: int = 28, parent=None):
        super().__init__(parent)
        self.segments = segments
        self.level = 0.0  # 0..1
        self.setFixedHeight(14)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_level(self, rms: float) -> None:
        # rms 0..1 → échelle perceptive (≈ dB), 0.3 de RMS sature
        import math

        db = 20 * math.log10(max(rms, 1e-5))
        self.level = max(0.0, min(1.0, (db + 50) / 50))
        self.update()

    def paintEvent(self, _e: QPaintEvent) -> None:  # noqa: N802
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        w, h = self.width(), self.height()
        gap = 3.0
        sw = (w - gap * (self.segments - 1)) / self.segments
        on = round(self.level * self.segments)
        for i in range(self.segments):
            x = i * (sw + gap)
            if i < on:
                frac = i / self.segments
                color = t.rec if frac > 0.88 else (t.busy if frac > 0.72 else t.ok)
            else:
                color = t.inset
            p.setBrush(qcolor(color))
            p.drawRoundedRect(QRectF(x, 0, sw, h), 2, 2)
        p.end()
