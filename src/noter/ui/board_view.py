"""Vue d'un board : titre éditable, filtre, rangée de listes qui défile horizontalement."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QFont, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from noter.service import Service
from noter.ui import icons
from noter.ui.card_dialog import CardDialog
from noter.ui.widgets.board import AddListColumn, ListColumn, ListStrip
from noter.ui.widgets.common import tool_button

AUTOSCROLL_EDGE = 56  # px depuis le bord où le défilement automatique démarre


def _speed(depth: int) -> int:
    """Vitesse de défilement : plus le pointeur s'enfonce dans la zone de bord, plus ça va vite."""
    return max(2, min(28, depth // 2))


class BoardView(QWidget):
    changed = Signal()                 # cartes / listes modifiées (compteurs du rail)
    board_changed = Signal()           # board renommé ou supprimé (liste du rail)
    recording_requested = Signal(str)

    def __init__(self, service: Service, parent=None):
        super().__init__(parent)
        self.setObjectName("board")
        self.service = service
        self.repo = service.repo
        self.board_id: int | None = None
        self._dragging = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QHBoxLayout()
        bar.setContentsMargins(28, 22, 28, 10)
        bar.setSpacing(10)
        self.title_edit = QLineEdit()
        self.title_edit.setObjectName("titleEdit")
        f = QFont()
        f.setPixelSize(24)
        f.setWeight(QFont.Weight.DemiBold)
        self.title_edit.setFont(f)
        self.title_edit.editingFinished.connect(self._save_title)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtrer les cartes")
        self.filter.setClearButtonEnabled(True)
        self.filter.setFixedWidth(220)
        icons.bind(self.filter.addAction(QIcon(), QLineEdit.ActionPosition.LeadingPosition), "search", "ink_3", 14)
        self.filter.textChanged.connect(self._apply_filter)
        self.menu_btn = tool_button("more", ghost=True, tip="Actions du board")
        self.menu_btn.clicked.connect(self._open_menu)
        bar.addWidget(self.title_edit, 1)
        bar.addWidget(self.filter)
        bar.addWidget(self.menu_btn)
        root.addLayout(bar)

        self.empty = QLabel("Aucun board")
        self.empty.setObjectName("empty")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.empty, 1)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.strip = ListStrip()
        self.strip.list_dropped.connect(self._on_list_dropped)
        self.tail = AddListColumn()
        self.tail.submitted.connect(self._add_list)
        self.strip.tail = self.tail
        self.strip.lay.addWidget(self.tail, 0, Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.strip)
        root.addWidget(self.scroll, 1)
        self.scroll.hide()

        self._autoscroll = QTimer(self)
        self._autoscroll.setInterval(30)
        self._autoscroll.timeout.connect(self._autoscroll_tick)

    # ─── Données ────────────────────────────────────────────────────

    def set_board(self, board_id: int | None) -> None:
        self.board_id = board_id
        self.filter.clear()
        self.refresh()

    def refresh(self) -> None:
        if self._dragging:  # ne jamais détruire les widgets pendant un glisser-déposer
            return
        board = self.repo.get_board(self.board_id) if self.board_id is not None else None
        if board is None:
            self.title_edit.setText("")
            self.title_edit.setEnabled(False)
            self.menu_btn.setEnabled(False)
            self.filter.setEnabled(False)
            self.scroll.hide()
            self.empty.show()
            return
        self.empty.hide()
        self.scroll.show()
        self.title_edit.setEnabled(True)
        self.menu_btn.setEnabled(True)
        self.filter.setEnabled(True)
        if not self.title_edit.hasFocus():
            self.title_edit.setText(board.name)

        lists = self.repo.get_lists(board.id)
        cards = self.repo.cards_for_board(board.id)
        rec_titles = self._recording_titles(c for cs in cards.values() for c in cs)
        existing = {col.list.id: col for col in self.strip.columns if col.list}
        columns: list[ListColumn] = []
        for lst in lists:
            col = existing.pop(lst.id, None) or self._make_column()
            col.load(lst, cards.get(lst.id, []), rec_titles)
            columns.append(col)
        for stale in existing.values():
            self.strip.lay.removeWidget(stale)
            stale.hide()
            stale.deleteLater()
        for col in columns:  # ordre de la base
            self.strip.lay.removeWidget(col)
        for i, col in enumerate(columns):
            self.strip.lay.insertWidget(i, col, 0, Qt.AlignmentFlag.AlignTop)
            col.show()
        self.strip.columns = columns
        self._fit_columns()
        self._apply_filter(self.filter.text())

    def _fit_columns(self) -> None:
        m = self.strip.lay.contentsMargins()
        avail = self.scroll.viewport().height() - m.top() - m.bottom()
        for col in self.strip.columns:
            col.set_max_height(avail)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._fit_columns()

    def _recording_titles(self, cards) -> dict[str, str]:
        out: dict[str, str] = {}
        for c in cards:
            if c.recording_id and c.recording_id not in out:
                rec = self.repo.get_recording(c.recording_id)
                if rec:
                    out[c.recording_id] = rec.display_title
        return out

    def _make_column(self) -> ListColumn:
        col = ListColumn(self.repo)
        col.strip = self.strip
        # Connexions différées : ces actions ouvrent une boucle modale (fiche, confirmation) puis reconstruisent
        # le board. Lancées depuis le clic, elles détruiraient la carte ou la liste dont le gestionnaire de clic
        # est encore en cours → plantage natif sous macOS. En file, elles partent une fois le clic terminé.
        queued = Qt.ConnectionType.QueuedConnection
        col.card_open.connect(self.open_card, queued)
        col.card_done.connect(self._set_card_done, queued)
        col.changed.connect(self._on_changed)
        col.move_requested.connect(self._move_list, queued)
        col.sort_requested.connect(self._sort_list, queued)
        col.delete_requested.connect(self._delete_list, queued)
        col.drag_started.connect(self._drag_started)
        col.drag_finished.connect(self._drag_finished)
        return col

    # ─── Glisser-déposer ────────────────────────────────────────────

    def _drag_started(self) -> None:
        self._dragging = True
        self._autoscroll.start()

    def _drag_finished(self) -> None:
        # Différé : la source du glisser est encore sur la pile d'appels de Qt.
        QTimer.singleShot(0, self._after_drag)

    def _after_drag(self) -> None:
        self._dragging = False
        self._autoscroll.stop()
        self.refresh()
        self.changed.emit()

    def _autoscroll_tick(self) -> None:
        self.autoscroll_step(QCursor.pos())

    def autoscroll_step(self, global_pos: QPoint) -> None:
        """Pendant un glisser : le board défile quand le pointeur longe un bord, comme sur Trello."""
        bar = self.scroll.horizontalScrollBar()
        view = self.scroll.viewport()
        p = view.mapFromGlobal(global_pos)
        if 0 <= p.y() <= view.height():
            if p.x() < AUTOSCROLL_EDGE:
                bar.setValue(bar.value() - _speed(AUTOSCROLL_EDGE - p.x()))
            elif p.x() > view.width() - AUTOSCROLL_EDGE:
                bar.setValue(bar.value() + _speed(p.x() - (view.width() - AUTOSCROLL_EDGE)))
        for col in self.strip.columns:  # et la liste sous le pointeur, verticalement
            area = col.scroll.viewport()
            q = area.mapFromGlobal(global_pos)
            if 0 <= q.x() <= area.width() and -AUTOSCROLL_EDGE <= q.y() <= area.height() + AUTOSCROLL_EDGE:
                vbar = col.scroll.verticalScrollBar()
                if q.y() < AUTOSCROLL_EDGE:
                    vbar.setValue(vbar.value() - _speed(AUTOSCROLL_EDGE - q.y()))
                elif q.y() > area.height() - AUTOSCROLL_EDGE:
                    vbar.setValue(vbar.value() + _speed(q.y() - (area.height() - AUTOSCROLL_EDGE)))
                break

    def _on_list_dropped(self, list_id: int, index: int) -> None:
        self.repo.move_list(list_id, index)

    # ─── Actions ────────────────────────────────────────────────────

    def _on_changed(self) -> None:
        self.refresh()
        self.changed.emit()

    def _add_list(self, name: str) -> None:
        if self.board_id is not None:
            self.repo.create_list(self.board_id, name)
            self._on_changed()
            QTimer.singleShot(0, lambda: self.scroll.horizontalScrollBar().setValue(self.scroll.horizontalScrollBar().maximum()))

    def _move_list(self, list_id: int, delta: int) -> None:
        if self.board_id is None:
            return
        ids = [lst.id for lst in self.repo.get_lists(self.board_id)]
        if list_id in ids:
            self.repo.move_list(list_id, max(0, min(len(ids) - 1, ids.index(list_id) + delta)))
            self._on_changed()

    def _sort_list(self, list_id: int) -> None:
        self.repo.sort_list_by_due(list_id)
        self._on_changed()

    def _sort_all_lists(self) -> None:
        if self.board_id is not None:
            for lst in self.repo.get_lists(self.board_id):
                self.repo.sort_list_by_due(lst.id)
            self._on_changed()

    def _delete_list(self, list_id: int) -> None:
        lst = self.repo.get_list(list_id)
        if lst is None:
            return
        n = len(self.repo.cards_in_list(list_id))
        detail = f" et ses {n} carte{'s' if n > 1 else ''}" if n else ""
        if QMessageBox.question(self, "Supprimer la liste", f"Supprimer « {lst.name} »{detail} ?") == QMessageBox.StandardButton.Yes:
            self.repo.delete_list(list_id)
            self._on_changed()

    def _save_title(self) -> None:
        board = self.repo.get_board(self.board_id) if self.board_id is not None else None
        name = self.title_edit.text().strip()
        if board is None:
            return
        if not name:
            self.title_edit.setText(board.name)
        elif name != board.name:
            self.repo.rename_board(board.id, name)
            self.board_changed.emit()

    def _open_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction("Ajouter une liste", self.tail.open)
        menu.addAction("Trier toutes les listes par échéance", self._sort_all_lists)
        menu.addSeparator()
        menu.addAction("Supprimer le board…", self._delete_board)
        menu.exec(self.menu_btn.mapToGlobal(self.menu_btn.rect().bottomLeft()))

    def _delete_board(self) -> None:
        board = self.repo.get_board(self.board_id) if self.board_id is not None else None
        if board is None:
            return
        n = sum(len(cs) for cs in self.repo.cards_for_board(board.id).values())
        detail = f" et ses {n} carte{'s' if n > 1 else ''}" if n else ""
        if QMessageBox.question(self, "Supprimer le board", f"Supprimer « {board.name} »{detail} ? Les enregistrements ne sont pas touchés.") == QMessageBox.StandardButton.Yes:
            self.repo.delete_board(board.id)
            self.board_id = None
            self.board_changed.emit()

    def _apply_filter(self, text: str) -> None:
        for col in self.strip.columns:
            col.apply_filter(text)

    # ─── Cartes ─────────────────────────────────────────────────────

    def _set_card_done(self, card_id: int, done: bool) -> None:
        self.repo.update_card(card_id, done=done)
        self._on_changed()

    def open_card(self, card_id: int) -> None:
        dlg = CardDialog(self.repo, card_id, self)
        dlg.changed.connect(self._on_changed)
        dlg.recording_requested.connect(lambda rid: (dlg.accept(), self.recording_requested.emit(rid)))
        dlg.exec()
        self._on_changed()
