"""Liste des enregistrements groupée par jour, avec glyphe d'état animé."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from noter.models import FR_DAYS, FR_MONTHS, Recording, RecordingStatus, format_month_fr
from noter.storage.repo import Repository
from noter.ui import theme
from noter.ui.theme import MONO, qcolor
from noter.ui.widgets.common import paint_status_glyph

RecordingRole = Qt.ItemDataRole.UserRole + 1
HeaderRole = Qt.ItemDataRole.UserRole + 2

STATUS_TEXT = {
    RecordingStatus.RECORDING: "Enregistrement…",
    RecordingStatus.RECORDED: "À traiter",
    RecordingStatus.TRANSCRIBING: "Transcription…",
    RecordingStatus.TRANSCRIBED: "Résumé en attente",
    RecordingStatus.SUMMARIZING: "Résumé…",
    RecordingStatus.FAILED: "Échec",
}


@dataclass
class ListFilter:
    kind: str = "all"  # all | active | failed | project | tag
    value: str | None = None


def group_label(d: date, today: date) -> str:
    if d == today:
        return "Aujourd’hui"
    if d == today - timedelta(days=1):
        return "Hier"
    if d > today - timedelta(days=7):
        return "Cette semaine"
    if d.year == today.year and d.month == today.month:
        return "Ce mois-ci"
    return format_month_fr(d)


class RecordingListModel(QAbstractListModel):
    def __init__(self, repo: Repository, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.filter = ListFilter()
        self._items: list[tuple[str, object]] = []  # ("header", str) | ("rec", Recording)

    def refresh(self) -> None:
        f = self.filter
        if f.kind == "failed":
            recs = self.repo.list_recordings(limit=1000, status=RecordingStatus.FAILED)
        elif f.kind == "active":
            recs = [r for r in self.repo.list_recordings(limit=1000) if r.status not in (RecordingStatus.DONE, RecordingStatus.FAILED)]
        elif f.kind == "project":
            recs = self.repo.list_recordings(limit=1000, project=f.value)
        elif f.kind == "tag":
            recs = self.repo.list_recordings(limit=1000, tag=f.value)
        else:
            recs = self.repo.list_recordings(limit=1000)
        today = date.today()
        items: list[tuple[str, object]] = []
        last = None
        for r in recs:
            g = group_label(r.started_at.date(), today)
            if g != last:
                items.append(("header", g))
                last = g
            items.append(("rec", r))
        self.beginResetModel()
        self._items = items
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self._items)

    def flags(self, index):
        kind, _ = self._items[index.row()]
        if kind == "header":
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        kind, val = self._items[index.row()]
        if role == HeaderRole:
            return val if kind == "header" else None
        if role == RecordingRole:
            return val if kind == "rec" else None
        if role == Qt.ItemDataRole.DisplayRole:
            return val if kind == "header" else val.display_title
        if role == Qt.ItemDataRole.ToolTipRole and kind == "rec":
            return f"{val.display_title}\n{val.started_at:%d/%m/%Y %H:%M} · {val.duration_text}\n{val.dir_path}"
        return None

    def row_of(self, recording_id: str) -> int:
        for i, (kind, val) in enumerate(self._items):
            if kind == "rec" and val.id == recording_id:
                return i
        return -1

    def first_recording_row(self) -> int:
        for i, (kind, _) in enumerate(self._items):
            if kind == "rec":
                return i
        return -1

    def recording_count(self) -> int:
        return sum(1 for k, _ in self._items if k == "rec")


class RecordingDelegate(QStyledItemDelegate):
    ROW_H = 60
    HEADER_H = 32
    PAD = 14

    def __init__(self, view: QListView):
        super().__init__(view)
        self.view = view
        self.phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self):
        self.phase = (self.phase + 0.05) % 1.0
        model = self.view.model()
        if model is None:
            return
        # Ne repeint que les lignes animées
        for row in range(model.rowCount()):
            rec = model.index(row).data(RecordingRole)
            if rec and rec.status not in (RecordingStatus.DONE, RecordingStatus.RECORDED):
                self.view.update(model.index(row))

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        if index.data(HeaderRole) is not None:
            return QSize(option.rect.width(), self.HEADER_H)
        return QSize(option.rect.width(), self.ROW_H)

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        t = theme.current()
        r: QRect = option.rect
        header = index.data(HeaderRole)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if header is not None:
            f = QFont(option.font)
            f.setPixelSize(11)
            f.setWeight(QFont.Weight.DemiBold)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
            p.setFont(f)
            p.setPen(qcolor(t.ink_3))
            p.drawText(QRect(r.left() + self.PAD + 2, r.top() + 4, r.width(), r.height() - 4), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, header.upper())
            p.restore()
            return

        rec: Recording = index.data(RecordingRole)
        inner = r.adjusted(8, 2, -8, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hovered:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(t.accent_soft if selected else t.sel))
            p.drawRoundedRect(inner, 10, 10)
        if selected:  # liseré iris, comme un marque-page
            p.setBrush(qcolor(t.accent))
            p.drawRoundedRect(QRect(inner.left(), inner.top() + 12, 3, inner.height() - 24), 1.5, 1.5)

        x = inner.left() + 12
        paint_status_glyph(p, x + 5, inner.top() + 21, rec.status, t, self.phase)
        x += 20
        right = inner.right() - 12

        mono = QFont(MONO)
        mono.setPixelSize(12)
        fm_mono = QFontMetrics(mono)
        dur = rec.duration_text if rec.status != RecordingStatus.RECORDING else ""
        dur_w = fm_mono.horizontalAdvance(dur) + 6 if dur else 0

        title_font = QFont(option.font)
        title_font.setWeight(QFont.Weight.DemiBold if selected else QFont.Weight.Medium)
        p.setFont(title_font)
        p.setPen(qcolor(t.accent_ink if selected else t.ink))
        fm = QFontMetrics(title_font)
        title_w = right - x - dur_w
        p.drawText(QRect(x, inner.top() + 11, title_w, 18), Qt.AlignmentFlag.AlignVCenter, fm.elidedText(rec.display_title, Qt.TextElideMode.ElideRight, title_w))
        if dur:
            p.setFont(mono)
            p.setPen(qcolor(t.ink_3))
            p.drawText(QRect(right - dur_w, inner.top() + 11, dur_w, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, dur)

        # Sous-ligne : heure (ou date), état si pas prêt, projet en capsule, tags
        sub_font = QFont(option.font)
        sub_font.setPixelSize(12)
        p.setFont(sub_font)
        fm2 = QFontMetrics(sub_font)
        y = inner.top() + 33
        cx = x
        if rec.status != RecordingStatus.DONE:
            txt = STATUS_TEXT.get(rec.status, "")
            p.setPen(qcolor(t.rec_ink if rec.status in (RecordingStatus.FAILED, RecordingStatus.RECORDING) else t.accent_ink))
            p.drawText(QRect(cx, y, right - cx, 16), Qt.AlignmentFlag.AlignVCenter, txt)
            cx += fm2.horizontalAdvance(txt) + 8
        else:
            d = rec.started_at
            txt = f"{d:%H:%M}" if (date.today() - d.date()).days < 2 else f"{FR_DAYS[d.weekday()]} {d.day} {FR_MONTHS[d.month - 1]} · {d:%H:%M}"
            p.setPen(qcolor(t.ink_3))
            p.drawText(QRect(cx, y, right - cx, 16), Qt.AlignmentFlag.AlignVCenter, txt)
            cx += fm2.horizontalAdvance(txt) + 8
        if rec.project and cx < right - 40:
            chip_font = QFont(option.font)
            chip_font.setPixelSize(11)
            fmc = QFontMetrics(chip_font)
            # Capsule teintée de la couleur du projet (la même que dans le rail)
            color = theme.speaker_color(t, rec.project)
            w = fmc.horizontalAdvance(rec.project) + 26
            w = min(w, right - cx)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.soft(color, 0.16))
            p.drawRoundedRect(QRect(cx, y, w, 17), 8.5, 8.5)
            p.setBrush(color)
            p.drawEllipse(QRect(cx + 7, y + 5, 7, 7))
            p.setFont(chip_font)
            p.setPen(qcolor(t.ink_2))
            p.drawText(QRect(cx + 18, y, w - 24, 17), Qt.AlignmentFlag.AlignVCenter, fmc.elidedText(rec.project, Qt.TextElideMode.ElideRight, w - 24))
            cx += w + 8
            p.setFont(sub_font)
        if rec.tags and cx < right - 20:
            p.setPen(qcolor(t.ink_3))
            tags = " ".join(f"#{tg}" for tg in rec.tags)
            p.drawText(QRect(cx, y, right - cx, 16), Qt.AlignmentFlag.AlignVCenter, fm2.elidedText(tags, Qt.TextElideMode.ElideRight, right - cx))
        p.restore()
