"""Widgets d'un board façon Trello : cartes, listes, composeurs inline, glisser-déposer.

- Une `CardTile` se glisse d'une liste à l'autre (ou dans la même) ; un cadre pointillé montre où elle atterrit.
- Une `ListColumn` se déplace en glissant son titre ; clic sur le titre pour le renommer.
- Le dépôt écrit en base ; c'est la source du glisser (qui survit au dépôt) qui demande ensuite le
  rafraîchissement, pour ne jamais détruire un widget pendant que Qt le manipule.
"""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QEvent, QMimeData, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QDrag, QFont, QKeyEvent, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from noter.models import FR_MONTHS, LABEL_NAMES_FR, BoardList, Card
from noter.storage.repo import Repository
from noter.ui import icons, theme
from noter.ui.theme import MONO, Tokens
from noter.ui.widgets.common import DoneToggle, clear_layout, tool_button

CARD_MIME = "application/x-noter-card"
CARD_HEIGHT_MIME = "application/x-noter-card-height"
LIST_MIME = "application/x-noter-list"
LIST_WIDTH = 272


# ─── Aides ──────────────────────────────────────────────────────────


def due_text(d: date, today: date | None = None) -> str:
    today = today or date.today()
    out = f"{d.day} {FR_MONTHS[d.month - 1]}"
    return out if d.year == today.year else f"{out} {d.year}"


def due_colors(card: Card, t: Tokens, today: date | None = None) -> tuple[str, str | None]:
    """(texte, fond) de la pastille d'échéance : terminée = menthe, en retard = corail, imminente = iris."""
    today = today or date.today()
    if card.done:
        return "#FFFFFF", t.ok
    if card.due and card.due < today:
        return "#FFFFFF", t.rec
    if card.due and card.due <= today + timedelta(days=1):
        return "#FFFFFF", t.accent
    return t.ink_3, None


def list_color(position: int) -> str:
    """Chaque liste reçoit une des trois couleurs, à tour de rôle : iris, corail, menthe."""
    t = theme.current()
    return (t.accent, t.rec, t.ok)[position % 3]


def _tilted_pixmap(pm: QPixmap, degrees: float = 3.0, margin: int = 14) -> QPixmap:
    """Image de glisser : la carte légèrement inclinée, comme sur Trello."""
    dpr = pm.devicePixelRatio()
    w, h = pm.width() / dpr, pm.height() / dpr
    out = QPixmap(int((w + 2 * margin) * dpr), int((h + 2 * margin) * dpr))
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.setOpacity(0.92)
    p.translate((w + 2 * margin) / 2, (h + 2 * margin) / 2)
    p.rotate(degrees)
    p.drawPixmap(int(-w / 2), int(-h / 2), pm)
    p.end()
    return out


def _passive(widget: QWidget) -> None:
    """Rend les enfants de `widget` (pas `widget` lui-même) transparents à la souris : le clic revient à la carte."""
    for w in widget.findChildren(QWidget):
        w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def _badge(icon_name: str, text: str, color: str, bg: str | None = None, tip: str = "") -> QWidget:
    f = QFrame()
    lay = QHBoxLayout(f)
    lay.setContentsMargins(5 if bg else 0, 1, 5 if bg else 0, 1)
    lay.setSpacing(4)
    ic = QLabel()
    ic.setPixmap(icons.icon(icon_name, color, 12).pixmap(12, 12))
    lab = QLabel(text)
    lab.setObjectName("badge")
    font = QFont(MONO)
    font.setPixelSize(11)
    lab.setFont(font)
    lab.setStyleSheet(f"color: {color};")
    lay.addWidget(ic)
    if text:
        lay.addWidget(lab)
    if bg:
        f.setStyleSheet(f"QFrame {{ background: {bg}; border-radius: 4px; }}")
    if tip:
        f.setToolTip(tip)
    return f


# ─── Carte ──────────────────────────────────────────────────────────


class CardTile(QFrame):
    clicked = Signal(int)
    done_toggled = Signal(int, bool)
    drag_started = Signal()
    drag_finished = Signal()

    def __init__(self, card: Card, recording_title: str | None = None, parent=None):
        super().__init__(parent)
        self.card = card
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        t = theme.current()
        self._press: QPoint | None = None
        self._haystack = " ".join(
            [card.title, card.description, *(LABEL_NAMES_FR[k] for k in card.labels)]
        ).lower()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        if card.labels:
            row = QHBoxLayout()
            row.setSpacing(4)
            for key in card.labels:
                chip = QFrame()
                chip.setFixedSize(36, 8)
                chip.setStyleSheet(f"background: {t.labels[key]}; border-radius: 4px;")
                chip.setToolTip(LABEL_NAMES_FR[key])
                row.addWidget(chip)
            row.addStretch()
            lay.addLayout(row)

        # Le rond « Terminer » n'apparaît qu'au survol (toujours visible une fois la carte terminée), comme sur Trello.
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.done_toggle = DoneToggle()
        self.done_toggle.setChecked(card.done)
        self.done_toggle.setVisible(card.done)
        self.done_toggle.toggled.connect(lambda checked: self.done_toggled.emit(self.card.id, checked))
        title_row.addWidget(self.done_toggle, 0, Qt.AlignmentFlag.AlignTop)
        title = QLabel(card.title)
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        title_row.addWidget(title, 1)
        lay.addLayout(title_row)

        badges: list[QWidget] = []
        if card.due:
            fg, bg = due_colors(card, t)
            icon_name = "check" if card.done else "calendar"
            badges.append(_badge(icon_name, due_text(card.due), fg, bg, "Échéance" + (" (terminée)" if card.done else "")))
        if card.description.strip():
            badges.append(_badge("text", "", t.ink_3, tip="Cette carte a une description"))
        done, total = card.checklist_progress
        if total:
            complete = done == total
            badges.append(_badge("checklist", f"{done}/{total}", t.ok if complete else t.ink_3, tip="Checklist"))
        if card.recording_id:
            badges.append(_badge("mic", "", t.ink_3, tip=f"Issue de « {recording_title} »" if recording_title else "Issue d’un enregistrement"))
        if badges:
            row = QHBoxLayout()
            row.setSpacing(10)
            for b in badges:
                row.addWidget(b)
            row.addStretch()
            lay.addLayout(row)
        _passive(self)
        self.done_toggle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

    def enterEvent(self, e) -> None:  # noqa: N802
        self.done_toggle.show()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self.done_toggle.setVisible(self.card.done)
        super().leaveEvent(e)

    def matches(self, text: str) -> bool:
        return not text or text.lower() in self._haystack

    # — Souris : clic = ouvrir, déplacement = glisser —

    def mousePressEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if self._press is not None and e.buttons() & Qt.MouseButton.LeftButton:
            if (e.position().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance():
                self._start_drag(self._press)
                return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        was_click = self._press is not None and e.button() == Qt.MouseButton.LeftButton
        self._press = None
        super().mouseReleaseEvent(e)
        if was_click and self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.card.id)

    def _start_drag(self, hot: QPoint) -> None:
        self._press = None
        pm = self.grab()
        mime = QMimeData()
        mime.setData(CARD_MIME, str(self.card.id).encode())
        mime.setData(CARD_HEIGHT_MIME, str(self.height()).encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(_tilted_pixmap(pm))
        drag.setHotSpot(hot + QPoint(14, 14))
        self.drag_started.emit()
        self.hide()
        drag.exec(Qt.DropAction.MoveAction)
        self.drag_finished.emit()  # le refresh est différé par le receveur


# ─── Composeurs inline ──────────────────────────────────────────────


class _Composer(QPlainTextEdit):
    """Zone de saisie d'une carte : Entrée valide, Maj+Entrée = saut de ligne, Échap annule."""

    submitted = Signal(str)
    cancelled = Signal()

    def __init__(self, placeholder: str, parent=None):
        super().__init__(parent)
        self.setObjectName("composer")
        self.setPlaceholderText(placeholder)
        self.setFixedHeight(62)
        self.setTabChangesFocus(True)

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            text = self.toPlainText().strip()
            if text:
                self.submitted.emit(text)
            self.clear()
            return
        if e.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(e)


class _LineComposer(QLineEdit):
    cancelled = Signal()

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(e)


class _AddRow(QWidget):
    """« + Ajouter … » qui se déplie en champ de saisie + bouton valider + annuler."""

    submitted = Signal(str)

    def __init__(self, button_text: str, placeholder: str, confirm_text: str, multiline: bool, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.button = QToolButton()
        self.button.setObjectName("addCard")
        self.button.setText(" " + button_text)
        icons.bind(self.button, "plus", "ink_3", 14)
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self.open)
        lay.addWidget(self.button)

        self.form = QWidget()
        fl = QVBoxLayout(self.form)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(6)
        if multiline:
            self.field: QPlainTextEdit | QLineEdit = _Composer(placeholder)
            self.field.submitted.connect(self.submitted.emit)
        else:
            self.field = _LineComposer()
            self.field.setPlaceholderText(placeholder)
            self.field.returnPressed.connect(self._submit_line)
        self.field.cancelled.connect(self.close_form)
        fl.addWidget(self.field)
        row = QHBoxLayout()
        row.setSpacing(6)
        ok = QPushButton(confirm_text)
        ok.setObjectName("primary")
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.clicked.connect(self._confirm)
        cancel = tool_button("x", ghost=True, tip="Annuler (Échap)")
        cancel.clicked.connect(self.close_form)
        row.addWidget(ok)
        row.addWidget(cancel)
        row.addStretch()
        fl.addLayout(row)
        lay.addWidget(self.form)
        self.form.hide()

    @property
    def is_open(self) -> bool:
        return not self.form.isHidden()

    def open(self) -> None:
        self.button.hide()
        self.form.show()
        self.field.setFocus()

    def close_form(self) -> None:
        self.form.hide()
        self.button.show()
        self.field.clear()

    def _submit_line(self) -> None:
        text = self.field.text().strip()  # type: ignore[union-attr]
        if text:
            self.submitted.emit(text)
        self.field.clear()

    def _confirm(self) -> None:
        if isinstance(self.field, QLineEdit):
            self._submit_line()
        else:
            text = self.field.toPlainText().strip()
            if text:
                self.submitted.emit(text)
            self.field.clear()
        self.field.setFocus()


# ─── Titre de liste ─────────────────────────────────────────────────


class _TitleEdit(QLineEdit):
    cancelled = Signal()

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(e)


class _ListTitle(QLabel):
    """Titre cliquable (renommer) et saisissable (déplacer la liste)."""

    edit_requested = Signal()
    drag_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("listTitle")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._press: QPoint | None = None

    def mousePressEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if self._press is not None and (e.position().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance():
            self._press = None
            self.drag_requested.emit()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if self._press is not None and e.button() == Qt.MouseButton.LeftButton:
            self._press = None
            self.edit_requested.emit()


# ─── Liste ──────────────────────────────────────────────────────────


class ListColumn(QFrame):
    card_open = Signal(int)
    card_done = Signal(int, bool)  # card_id, terminée
    changed = Signal()           # la base a changé : le board doit se recharger
    drag_started = Signal()
    drag_finished = Signal()
    move_requested = Signal(int, int)  # list_id, delta (-1 / +1)
    delete_requested = Signal(int)
    sort_requested = Signal(int)  # list_id : trier par échéance

    def __init__(self, repo: Repository, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.list: BoardList | None = None
        self.strip: ListStrip | None = None
        self.setObjectName("boardList")
        self.setFixedWidth(LIST_WIDTH)
        self.setAcceptDrops(True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)
        self._filter = ""
        self._max_height = 10_000
        self._mark = QFrame()
        self._mark.setObjectName("dropMark")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        head.addWidget(self.dot)
        self.title = _ListTitle()
        self.title.edit_requested.connect(self._begin_rename)
        self.title.drag_requested.connect(self._start_drag)
        self.title_edit = _TitleEdit()
        self.title_edit.setObjectName("listTitleEdit")
        self.title_edit.editingFinished.connect(self._end_rename)
        self.title_edit.cancelled.connect(self._cancel_rename)
        self.title_edit.hide()
        self.count = QLabel("")
        self.count.setObjectName("listCount")
        self.menu_btn = tool_button("more", ghost=True, tip="Actions de la liste")
        icons.bind(self.menu_btn, "more", "ink_3", 14)
        self.menu_btn.clicked.connect(self._open_menu)
        head.addWidget(self.title, 1)
        head.addWidget(self.title_edit, 1)
        head.addWidget(self.count)
        head.addWidget(self.menu_btn)
        root.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.host = QWidget()
        self.host.setMinimumHeight(1)  # sinon le minimum « cartes étroites » dépasse la hauteur réelle et force un défilement
        self.host.installEventFilter(self)
        self.cards_lay = QVBoxLayout(self.host)
        self.cards_lay.setContentsMargins(0, 0, 4, 0)
        self.cards_lay.setSpacing(6)
        self.cards_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.host)
        root.addWidget(self.scroll)

        self.adder = _AddRow("Ajouter une carte", "Titre de la carte…", "Ajouter la carte", multiline=True)
        self.adder.submitted.connect(self._add_card)
        root.addWidget(self.adder)

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        if obj is self.host and ev.type() == QEvent.Type.LayoutRequest:
            self._refit()
        return super().eventFilter(obj, ev)

    # — Contenu —

    def load(self, lst: BoardList, cards: list[Card], rec_titles: dict[str, str]) -> None:
        self.list = lst
        self._remove_mark()
        clear_layout(self.cards_lay)
        for card in cards:
            tile = CardTile(card, rec_titles.get(card.recording_id or ""))
            tile.clicked.connect(self.card_open)
            tile.done_toggled.connect(self.card_done)
            tile.drag_started.connect(self.drag_started)
            tile.drag_finished.connect(self.drag_finished)
            self.cards_lay.addWidget(tile)
        self.title.setText(lst.name)
        self.count.setText(str(len(cards)))
        self.count.setVisible(bool(cards))
        self.dot.setStyleSheet(f"background: {list_color(lst.position)}; border-radius: 5px;")
        self.apply_filter(self._filter)
        self._refit()
        QTimer.singleShot(0, self._refit)  # une fois les cartes stylées, leur hauteur réelle est connue

    def set_max_height(self, height: int) -> None:
        """Hauteur disponible dans le board : au-delà, la liste défile."""
        self._max_height = height
        self._refit()

    def _refit(self) -> None:
        """La liste épouse ses cartes (comme sur Trello) tant qu'elle tient dans le board, puis elle défile."""
        # Les titres passent à la ligne : la hauteur du contenu dépend de la largeur utile.
        content = self.cards_lay.totalHeightForWidth(LIST_WIDTH - 16)
        chrome = self.layout().sizeHint().height() - self.scroll.height()
        self.scroll.setFixedHeight(max(8, min(content + 2, self._max_height - chrome)))

    def tiles(self) -> list[CardTile]:
        return [w for i in range(self.cards_lay.count()) if isinstance((w := self.cards_lay.itemAt(i).widget()), CardTile)]

    def apply_filter(self, text: str) -> None:
        self._filter = text.strip()
        for tile in self.tiles():
            tile.setVisible(tile.matches(self._filter))

    def open_composer(self) -> None:
        self.adder.open()

    @property
    def composing(self) -> bool:
        return self.adder.is_open

    def _add_card(self, title: str) -> None:
        if self.list is not None:
            self.repo.create_card(self.list.id, title)
            self.changed.emit()

    # — Titre —

    def _begin_rename(self) -> None:
        if self.list is None:
            return
        self.title.hide()
        self.title_edit.setText(self.list.name)
        self.title_edit.show()
        self.title_edit.setFocus()
        self.title_edit.selectAll()

    def _end_rename(self) -> None:
        if self.title_edit.isHidden() or self.list is None:
            return
        name = self.title_edit.text().strip()
        self.title_edit.hide()
        self.title.show()
        if name and name != self.list.name:
            self.repo.rename_list(self.list.id, name)
            self.changed.emit()

    def _cancel_rename(self) -> None:
        self.title_edit.hide()
        self.title.show()

    def _open_menu(self) -> None:
        if self.list is None:
            return
        menu = QMenu(self)
        menu.addAction("Ajouter une carte", self.open_composer)
        menu.addAction("Renommer la liste", self._begin_rename)
        menu.addAction("Trier par échéance", lambda: self.sort_requested.emit(self.list.id))  # type: ignore[union-attr]
        menu.addSeparator()
        menu.addAction("Déplacer à gauche", lambda: self.move_requested.emit(self.list.id, -1))  # type: ignore[union-attr]
        menu.addAction("Déplacer à droite", lambda: self.move_requested.emit(self.list.id, +1))  # type: ignore[union-attr]
        menu.addSeparator()
        menu.addAction("Supprimer la liste…", lambda: self.delete_requested.emit(self.list.id))  # type: ignore[union-attr]
        menu.exec(self.menu_btn.mapToGlobal(QPoint(0, self.menu_btn.height())))

    # — Glisser la liste —

    def _start_drag(self) -> None:
        if self.list is None:
            return
        pm = self.grab()
        mime = QMimeData()
        mime.setData(LIST_MIME, str(self.list.id).encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(_tilted_pixmap(pm, 2.0))
        drag.setHotSpot(self.mapFromGlobal(self.cursor().pos()) + QPoint(14, 14))
        self.drag_started.emit()
        self.hide()
        drag.exec(Qt.DropAction.MoveAction)
        self.drag_finished.emit()

    # — Déposer une carte —

    def _drop_slot(self, pos: QPoint, dragged: int) -> tuple[int, int]:
        """(position dans le layout, index logique parmi les autres cartes) pour un point en coordonnées de la liste."""
        y = self.host.mapFrom(self, pos).y()
        lay_index = self.cards_lay.count()
        for i in range(self.cards_lay.count()):
            w = self.cards_lay.itemAt(i).widget()
            if isinstance(w, CardTile) and w.card.id != dragged and not w.isHidden() and w.geometry().center().y() > y:
                lay_index = i
                break
        logical = sum(
            1 for i in range(lay_index)
            if isinstance((w := self.cards_lay.itemAt(i).widget()), CardTile) and w.card.id != dragged
        )
        return lay_index, logical

    def _remove_mark(self) -> None:
        if self.cards_lay.indexOf(self._mark) >= 0:
            self.cards_lay.removeWidget(self._mark)
            self._mark.hide()  # pas de setParent(None) : voir clear_layout

    def _dragged_card(self, e) -> int | None:
        md = e.mimeData()
        if not md.hasFormat(CARD_MIME):
            return None
        try:
            return int(bytes(md.data(CARD_MIME)).decode())
        except ValueError:
            return None

    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if e.mimeData().hasFormat(CARD_MIME):
            e.acceptProposedAction()
        elif self.strip is not None and e.mimeData().hasFormat(LIST_MIME):
            self.strip.list_drag_move(self.strip.mapFromGlobal(self.mapToGlobal(e.position().toPoint())), e)

    def dragMoveEvent(self, e) -> None:  # noqa: N802
        dragged = self._dragged_card(e)
        if dragged is None:
            if self.strip is not None and e.mimeData().hasFormat(LIST_MIME):
                self.strip.list_drag_move(self.strip.mapFromGlobal(self.mapToGlobal(e.position().toPoint())), e)
            return
        self._remove_mark()
        lay_index, _ = self._drop_slot(e.position().toPoint(), dragged)
        h = int(bytes(e.mimeData().data(CARD_HEIGHT_MIME)).decode() or 40) if e.mimeData().hasFormat(CARD_HEIGHT_MIME) else 40
        self._mark.setFixedHeight(h)
        self.cards_lay.insertWidget(lay_index, self._mark)
        self._mark.show()
        e.acceptProposedAction()

    def dragLeaveEvent(self, e) -> None:  # noqa: N802
        self._remove_mark()
        if self.strip is not None:
            self.strip.list_drag_leave()
        super().dragLeaveEvent(e)

    def dropEvent(self, e) -> None:  # noqa: N802
        dragged = self._dragged_card(e)
        if dragged is None:
            if self.strip is not None and e.mimeData().hasFormat(LIST_MIME):
                self.strip.list_drop(self.strip.mapFromGlobal(self.mapToGlobal(e.position().toPoint())), e)
            return
        _, logical = self._drop_slot(e.position().toPoint(), dragged)
        self._remove_mark()
        if self.list is not None:
            self.repo.move_card(dragged, self.list.id, logical)
        e.acceptProposedAction()


# ─── Rangée de listes ───────────────────────────────────────────────


class AddListColumn(QFrame):
    submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("addList")
        self.setFixedWidth(LIST_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.row = _AddRow("Ajouter une liste", "Nom de la liste…", "Ajouter la liste", multiline=False)
        self.row.submitted.connect(self.submitted)
        lay.addWidget(self.row)

    def open(self) -> None:
        self.row.open()


class ListStrip(QWidget):
    """Conteneur horizontal des listes ; reçoit le dépôt d'une liste (réordonnancement)."""

    list_dropped = Signal(int, int)  # list_id, index

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("board")
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(20, 6, 20, 16)
        self.lay.setSpacing(10)
        self.lay.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.columns: list[ListColumn] = []
        self.tail: AddListColumn | None = None
        self._mark = QFrame()
        self._mark.setObjectName("dropMark")
        self._mark.setFixedWidth(LIST_WIDTH)

    def _slot(self, pos: QPoint, dragged: int) -> tuple[int, int]:
        lay_index = self.lay.indexOf(self.tail) if self.tail is not None else self.lay.count()
        for i in range(self.lay.count()):
            w = self.lay.itemAt(i).widget()
            if isinstance(w, ListColumn) and w.list and w.list.id != dragged and not w.isHidden() and w.geometry().center().x() > pos.x():
                lay_index = i
                break
        logical = sum(
            1 for i in range(lay_index)
            if isinstance((w := self.lay.itemAt(i).widget()), ListColumn) and w.list and w.list.id != dragged
        )
        return lay_index, logical

    def _dragged(self, e) -> int | None:
        if not e.mimeData().hasFormat(LIST_MIME):
            return None
        try:
            return int(bytes(e.mimeData().data(LIST_MIME)).decode())
        except ValueError:
            return None

    def _remove_mark(self) -> None:
        if self.lay.indexOf(self._mark) >= 0:
            self.lay.removeWidget(self._mark)
            self._mark.hide()  # pas de setParent(None) : voir clear_layout

    def list_drag_move(self, pos: QPoint, e) -> None:
        dragged = self._dragged(e)
        if dragged is None:
            return
        self._remove_mark()
        lay_index, _ = self._slot(pos, dragged)
        self.lay.insertWidget(lay_index, self._mark)
        self._mark.show()
        e.acceptProposedAction()

    def list_drag_leave(self) -> None:
        self._remove_mark()

    def list_drop(self, pos: QPoint, e) -> None:
        dragged = self._dragged(e)
        if dragged is None:
            return
        _, logical = self._slot(pos, dragged)
        self._remove_mark()
        self.list_dropped.emit(dragged, logical)
        e.acceptProposedAction()

    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if e.mimeData().hasFormat(LIST_MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e) -> None:  # noqa: N802
        self.list_drag_move(e.position().toPoint(), e)

    def dragLeaveEvent(self, e) -> None:  # noqa: N802
        self._remove_mark()
        super().dragLeaveEvent(e)

    def dropEvent(self, e) -> None:  # noqa: N802
        self.list_drop(e.position().toPoint(), e)

