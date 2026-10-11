"""Modèle Qt de la liste d'enregistrements + delegate d'affichage."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from noter.models import Recording, RecordingStatus
from noter.storage.repo import Repository
from noter.ui.style import STATUS_COLOR, STATUS_LABEL

RecordingRole = Qt.ItemDataRole.UserRole + 1


@dataclass
class ListFilter:
    status: RecordingStatus | None = None
    project: str | None = None
    tag: str | None = None
    failed_only: bool = False
    active_only: bool = False


class RecordingListModel(QAbstractListModel):
    def __init__(self, repo: Repository, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.filter = ListFilter()
        self._items: list[Recording] = []

    def refresh(self) -> None:
        self.beginResetModel()
        f = self.filter
        if f.failed_only:
            items = self.repo.list_recordings(limit=500, status=RecordingStatus.FAILED, project=f.project, tag=f.tag)
        elif f.active_only:
            items = [
                r
                for r in self.repo.list_recordings(limit=500, project=f.project, tag=f.tag)
                if r.status not in (RecordingStatus.DONE, RecordingStatus.FAILED)
            ]
        else:
            items = self.repo.list_recordings(limit=500, status=f.status, project=f.project, tag=f.tag)
        self._items = items
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        rec = self._items[index.row()]
        if role == RecordingRole:
            return rec
        if role == Qt.ItemDataRole.DisplayRole:
            return rec.display_title
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{rec.display_title}\n{rec.started_at:%d/%m/%Y %H:%M} · {rec.duration_text}\n{rec.dir_path}"
        return None

    def recording_at(self, row: int) -> Recording | None:
        return self._items[row] if 0 <= row < len(self._items) else None

    def row_of(self, recording_id: str) -> int:
        for i, r in enumerate(self._items):
            if r.id == recording_id:
                return i
        return -1


class RecordingDelegate(QStyledItemDelegate):
    ROW_H = 58
    PAD = 10

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(option.rect.width(), self.ROW_H)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        rec: Recording = index.data(RecordingRole)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r: QRect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        pal: QPalette = option.palette
        if selected:
            painter.fillRect(r, pal.highlight())
            fg = pal.highlightedText().color()
            dim = QColor(fg)
            dim.setAlphaF(0.75)
        else:
            if option.state & QStyle.StateFlag.State_MouseOver:
                painter.fillRect(r, pal.alternateBase())
            fg = pal.text().color()
            dim = pal.color(QPalette.ColorRole.PlaceholderText)

        x = r.left() + self.PAD
        # Point de statut
        color = QColor(STATUS_COLOR[rec.status])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(x, r.top() + 22, 8, 8)
        x += 18

        title_font = QFont(option.font)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(fg)
        fm = QFontMetrics(title_font)
        width = r.right() - x - self.PAD
        dur = rec.duration_text
        dur_w = fm.horizontalAdvance(dur) + 8
        painter.drawText(QRect(x, r.top() + 8, width - dur_w, 20), Qt.AlignmentFlag.AlignVCenter,
                         fm.elidedText(rec.display_title, Qt.TextElideMode.ElideRight, width - dur_w))
        painter.setFont(option.font)
        painter.setPen(dim)
        painter.drawText(QRect(r.right() - self.PAD - dur_w, r.top() + 8, dur_w, 20),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, dur)

        sub = f"{rec.started_at:%a %d %b · %H:%M}"
        if rec.status != RecordingStatus.DONE:
            sub += f"  ·  {STATUS_LABEL[rec.status]}"
        if rec.project:
            sub += f"  ·  {rec.project}"
        if rec.tags:
            sub += "  ·  " + " ".join(f"#{t}" for t in rec.tags)
        fm2 = QFontMetrics(option.font)
        painter.drawText(QRect(x, r.top() + 30, width, 18), Qt.AlignmentFlag.AlignVCenter,
                         fm2.elidedText(sub, Qt.TextElideMode.ElideRight, width))
        painter.restore()
