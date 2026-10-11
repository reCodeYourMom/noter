"""États vides : première ouverture, liste vide pour un filtre, rien sélectionné."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from noter.ui import icons, theme
from noter.ui.theme import qcolor


class WaveGlyph(QWidget):
    """Petite onde décorative, déterministe."""

    def __init__(self, bars: int = 46, parent=None):
        super().__init__(parent)
        self.bars = bars
        self.setFixedSize(280, 56)
        seed = 7
        vals = []
        env = 0.3
        for _ in range(bars):
            seed = (seed * 9301 + 49297) % 233280
            r = seed / 233280
            env = max(0.12, min(1.0, env + (r - 0.5) * 0.3))
            vals.append(env)
        self.vals = vals

    def paintEvent(self, _e: QPaintEvent) -> None:  # noqa: N802
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(t.ink_4))
        w, h = self.width(), self.height()
        gap = 3
        bw = (w - gap * (self.bars - 1)) / self.bars
        for i, v in enumerate(self.vals):
            bh = max(3.0, v * h * 0.9)
            p.drawRoundedRect(QRectF(i * (bw + gap), (h - bh) / 2, bw, bh), 1.5, 1.5)
        p.end()


class EmptyState(QWidget):
    record_requested = Signal()
    import_requested = Signal()

    def __init__(self, title: str, text: str, actions: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 40, 40, 40)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glyph = WaveGlyph()
        lay.addWidget(glyph, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(6)
        self.title = QLabel(title)
        self.title.setObjectName("emptyTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.title)
        self.text = QLabel(text)
        self.text.setObjectName("empty")
        self.text.setWordWrap(True)
        self.text.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.text.setFixedWidth(360)
        lay.addWidget(self.text, 0, Qt.AlignmentFlag.AlignHCenter)
        if actions:
            t = theme.current()
            row = QHBoxLayout()
            row.setSpacing(8)
            row.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            rec = QPushButton("  Enregistrer")
            rec.setObjectName("primary")
            rec.setIcon(icons.icon("mic", t.panel, 14))
            rec.setCursor(Qt.CursorShape.PointingHandCursor)
            rec.clicked.connect(self.record_requested.emit)
            imp = QPushButton("Importer un fichier…")
            imp.setCursor(Qt.CursorShape.PointingHandCursor)
            imp.clicked.connect(self.import_requested.emit)
            row.addWidget(rec)
            row.addWidget(imp)
            lay.addSpacing(8)
            lay.addLayout(row)
