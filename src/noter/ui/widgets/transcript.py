"""Transcript : liste de segments avec timecode, avatar du speaker et texte replié."""
from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QTextOption
from PySide6.QtWidgets import QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from noter.models import Segment, format_timestamp
from noter.ui import theme
from noter.ui.theme import MONO, qcolor
from noter.ui.widgets.common import paint_avatar

SegmentRole = Qt.ItemDataRole.UserRole + 1


class TranscriptModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._segments: list[Segment] = []
        self.current = -1

    def set_segments(self, segments: list[Segment]) -> None:
        self.beginResetModel()
        self._segments = list(segments)
        self.current = -1
        self.endResetModel()

    def set_current(self, row: int) -> None:
        old = self.current
        self.current = row
        for r in (old, row):
            if 0 <= r < len(self._segments):
                idx = self.index(r)
                self.dataChanged.emit(idx, idx)

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self._segments)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        s = self._segments[index.row()]
        if role == SegmentRole:
            return s
        if role == Qt.ItemDataRole.DisplayRole:
            return s.text
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{format_timestamp(s.start)} → {format_timestamp(s.end)}"
        return None

    def segment(self, row: int) -> Segment | None:
        return self._segments[row] if 0 <= row < len(self._segments) else None


class TranscriptDelegate(QStyledItemDelegate):
    TC_W = 44
    AV = 20
    GAP = 10
    PAD_V = 6
    PAD_H = 8

    def __init__(self, view: QListView):
        super().__init__(view)
        self.view = view

    def _text_rect_width(self, total: int) -> int:
        return total - (self.PAD_H * 2 + self.TC_W + self.GAP + self.AV + self.GAP + 12)

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        width = self.view.viewport().width()
        fm = QFontMetrics(option.font)
        tw = max(60, self._text_rect_width(width))
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        rect = fm.boundingRect(QRect(0, 0, tw, 10_000), Qt.TextFlag.TextWordWrap, text)
        return QSize(width, max(self.AV, rect.height()) + self.PAD_V * 2 + 2)

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        t = theme.current()
        s: Segment = index.data(SegmentRole)
        model = index.model()
        is_current = getattr(model, "current", -1) == index.row()
        r: QRect = option.rect
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        inner = r.adjusted(0, 1, 0, -1)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if is_current or hovered:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(t.accent_soft if is_current else t.sel))
            p.drawRoundedRect(inner, 10, 10)

        x = inner.left() + self.PAD_H
        y = inner.top() + self.PAD_V
        mono = QFont(MONO)
        mono.setPixelSize(11)
        p.setFont(mono)
        p.setPen(qcolor(t.accent_ink if is_current else t.ink_4))
        p.drawText(QRect(x, y + 1, self.TC_W, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, format_timestamp(s.start))
        x += self.TC_W + self.GAP
        paint_avatar(p, QRectF(x, y, self.AV, self.AV), s.speaker, t)
        x += self.AV + self.GAP

        p.setFont(option.font)
        p.setPen(qcolor(t.ink if is_current else t.ink_2))
        tw = max(60, self._text_rect_width(r.width()))
        opt = QTextOption()
        opt.setWrapMode(QTextOption.WrapMode.WordWrap)
        p.drawText(QRectF(x, y, tw, inner.height() - self.PAD_V), s.text, opt)
        p.restore()


class TranscriptView(QListView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.model_ = TranscriptModel(self)
        self.setModel(self.model_)
        self.delegate = TranscriptDelegate(self)
        self.setItemDelegate(self.delegate)
        self.setMouseTracking(True)
        self.setSelectionMode(QListView.SelectionMode.NoSelection)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setWordWrap(True)
        self.setSpacing(0)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        # Les hauteurs dépendent de la largeur : on force le recalcul
        self.scheduleDelayedItemsLayout()

    def set_segments(self, segments: list[Segment]) -> None:
        self.model_.set_segments(segments)

    def set_current(self, row: int, scroll: bool = True) -> None:
        if row == self.model_.current:
            return
        self.model_.set_current(row)
        if scroll and row >= 0:
            self.scrollTo(self.model_.index(row), QListView.ScrollHint.PositionAtCenter)

    def segment_at_row(self, row: int) -> Segment | None:
        return self.model_.segment(row)
