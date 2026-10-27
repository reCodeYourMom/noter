"""Fenêtre d'une carte : titre, étiquettes, échéance, description, checklist, déplacement, suppression.

Tout s'enregistre au fil de l'eau (comme la fiche d'un enregistrement) : il n'y a pas de bouton Valider.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from noter.models import LABEL_KEYS, LABEL_NAMES_FR, Card, ChecklistItem
from noter.storage.repo import Repository
from noter.ui import icons, theme
from noter.ui.widgets.common import clear_layout, section_label, tool_button


class CardDialog(QDialog):
    changed = Signal()            # la carte a été modifiée / déplacée / supprimée
    recording_requested = Signal(str)

    def __init__(self, repo: Repository, card_id: int, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.card_id = card_id
        self._loading = True
        self._deleted = False
        card = repo.get_card(card_id)
        if card is None:
            raise ValueError(f"Carte {card_id} introuvable")
        self.card: Card = card
        self.setWindowTitle("Carte")
        self.setModal(True)
        self.resize(760, 640)
        t = theme.current()

        self._desc_timer = QTimer(self)
        self._desc_timer.setSingleShot(True)
        self._desc_timer.setInterval(600)
        self._desc_timer.timeout.connect(self._save_description)

        root = QHBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(24)

        # ─── Colonne principale ─────────────────────────────────
        main = QVBoxLayout()
        main.setSpacing(8)
        self.title_edit = QLineEdit()
        self.title_edit.setObjectName("titleEdit")
        f = QFont()
        f.setPixelSize(22)
        f.setWeight(QFont.Weight.DemiBold)
        self.title_edit.setFont(f)
        self.title_edit.editingFinished.connect(self._save_title)
        main.addWidget(self.title_edit)
        self.where = QLabel("")
        self.where.setObjectName("meta")
        main.addWidget(self.where)

        main.addSpacing(8)
        main.addWidget(section_label("Étiquettes", t.accent))
        row = QHBoxLayout()
        row.setSpacing(6)
        self.label_buttons: dict[str, QToolButton] = {}
        for key in LABEL_KEYS:
            b = QToolButton()
            b.setObjectName("labelPick")
            b.setCheckable(True)
            b.setToolTip(LABEL_NAMES_FR[key])
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setText(LABEL_NAMES_FR[key])
            b.setStyleSheet(
                f"QToolButton#labelPick {{ background: {theme.rgba(t.labels[key], 0.18)}; color: {t.ink_2}; font-size: 12px; }}"
                f"QToolButton#labelPick:hover {{ border: 2px solid {t.labels[key]}; }}"
                f"QToolButton#labelPick:checked {{ background: {t.labels[key]}; color: white; font-weight: 600; }}"
            )
            b.toggled.connect(self._save_labels)
            self.label_buttons[key] = b
            row.addWidget(b)
        row.addStretch()
        main.addLayout(row)

        main.addSpacing(8)
        main.addWidget(section_label("Échéance", t.rec))
        row = QHBoxLayout()
        row.setSpacing(10)
        self.has_due = QCheckBox("Date limite")
        self.has_due.toggled.connect(self._save_due)
        self.due_edit = QDateEdit()
        self.due_edit.setCalendarPopup(True)
        self.due_edit.setDisplayFormat("dd/MM/yyyy")
        self.due_edit.setDate(QDate.currentDate())
        self.due_edit.dateChanged.connect(lambda _d: self._save_due())
        self.due_done = QCheckBox("Terminée")
        self.due_done.toggled.connect(self._save_due)
        row.addWidget(self.has_due)
        row.addWidget(self.due_edit)
        row.addWidget(self.due_done)
        row.addStretch()
        main.addLayout(row)

        main.addSpacing(8)
        main.addWidget(section_label("Description", t.accent))
        self.desc = QPlainTextEdit()
        self.desc.setPlaceholderText("Ajoute une description plus détaillée…")
        self.desc.setMinimumHeight(110)
        self.desc.textChanged.connect(self._desc_dirty)
        main.addWidget(self.desc)

        main.addSpacing(8)
        head = QHBoxLayout()
        head.addWidget(section_label("Checklist", t.ok))
        self.progress_text = QLabel("")
        self.progress_text.setObjectName("meta")
        head.addStretch()
        head.addWidget(self.progress_text)
        main.addLayout(head)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        main.addWidget(self.progress)
        self.items_host = QWidget()
        self.items_lay = QVBoxLayout(self.items_host)
        self.items_lay.setContentsMargins(0, 0, 0, 0)
        self.items_lay.setSpacing(0)
        main.addWidget(self.items_host)
        self.new_item = QLineEdit()
        self.new_item.setPlaceholderText("Ajouter un élément…")
        self.new_item.returnPressed.connect(self._add_item)
        main.addWidget(self.new_item)
        main.addStretch(1)
        root.addLayout(main, 1)

        # ─── Colonne latérale ───────────────────────────────────
        side = QVBoxLayout()
        side.setSpacing(8)
        side.addWidget(section_label("Déplacer vers"))
        self.list_combo = QComboBox()
        self.list_combo.activated.connect(self._move)
        side.addWidget(self.list_combo)
        self.rec_btn = QPushButton("  Ouvrir l’enregistrement")
        self.rec_btn.setIcon(icons.icon("mic", t.ink_2, 14))
        self.rec_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rec_btn.clicked.connect(lambda: self.card.recording_id and self.recording_requested.emit(self.card.recording_id))
        self.rec_label = section_label("Source")
        side.addSpacing(8)
        side.addWidget(self.rec_label)
        side.addWidget(self.rec_btn)
        side.addStretch(1)
        delete = QPushButton("  Supprimer la carte")
        delete.setObjectName("danger")
        delete.setIcon(icons.icon("trash", t.rec_ink, 14))
        delete.setCursor(Qt.CursorShape.PointingHandCursor)
        delete.clicked.connect(self._delete)
        close = QPushButton("Fermer")
        close.setObjectName("primary")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.accept)
        side.addWidget(delete)
        side.addWidget(close)
        side_w = QWidget()
        side_w.setFixedWidth(190)
        side_w.setLayout(side)
        side.setContentsMargins(0, 0, 0, 0)
        root.addWidget(side_w)

        self._load()
        self._loading = False

    # ─── Chargement ─────────────────────────────────────────────────

    def _load(self) -> None:
        was, self._loading = self._loading, True
        c = self.card
        self.title_edit.setText(c.title)
        board = self.repo.board_of_card(c.id)
        lists = self.repo.get_lists(board.id) if board else []
        current = next((lst for lst in lists if lst.id == c.list_id), None)
        self.where.setText(f"dans la liste « {current.name} »" + (f" · {board.name}" if board else "") if current else "")
        for key, b in self.label_buttons.items():
            b.setChecked(key in c.labels)
        self.has_due.setChecked(c.due is not None)
        if c.due:
            self.due_edit.setDate(QDate(c.due.year, c.due.month, c.due.day))
        self.due_edit.setEnabled(c.due is not None)
        self.due_done.setEnabled(c.due is not None)
        self.due_done.setChecked(c.done)
        # Une description en cours de saisie (pas encore enregistrée) ne doit pas être écrasée par un rechargement.
        if not self._desc_timer.isActive() and self.desc.toPlainText() != c.description:
            self.desc.setPlainText(c.description)
        self.list_combo.clear()
        for lst in lists:
            self.list_combo.addItem(lst.name, lst.id)
        self.list_combo.setCurrentIndex(max(0, self.list_combo.findData(c.list_id)))
        self._fill_checklist()
        rec = self.repo.get_recording(c.recording_id) if c.recording_id else None
        self.rec_btn.setVisible(rec is not None)
        self.rec_label.setVisible(rec is not None)
        if rec:
            self.rec_btn.setToolTip(rec.display_title)
        self._loading = was

    def _fill_checklist(self) -> None:
        clear_layout(self.items_lay)
        done, total = self.card.checklist_progress
        self.progress.setValue(int(100 * done / total) if total else 0)
        self.progress_text.setText(f"{done}/{total}" if total else "")
        self.progress.setVisible(bool(total))
        for i, item in enumerate(self.card.checklist):
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(0)
            cb = QCheckBox(item.text)
            cb.setChecked(item.done)
            cb.toggled.connect(lambda checked, idx=i: self._toggle_item(idx, checked))
            rm = tool_button("x", ghost=True, tip="Supprimer cet élément")
            rm.clicked.connect(lambda _=False, idx=i: self._remove_item(idx))
            rl.addWidget(cb, 1)
            rl.addWidget(rm)
            self.items_lay.addWidget(row)

    def _reload(self) -> None:
        card = self.repo.get_card(self.card_id)
        if card is not None:
            self.card = card
            self._load()

    # ─── Enregistrement au fil de l'eau ─────────────────────────────

    def _update(self, **fields) -> None:
        if self._loading or self._deleted:
            return
        self.repo.update_card(self.card_id, **fields)
        self._reload()
        self.changed.emit()

    def _save_title(self) -> None:
        title = self.title_edit.text().strip()
        if not title:
            self.title_edit.setText(self.card.title)
        elif title != self.card.title:
            self._update(title=title)

    def _save_labels(self) -> None:
        labels = [k for k, b in self.label_buttons.items() if b.isChecked()]
        if labels != self.card.labels:
            self._update(labels=labels)

    def _save_due(self) -> None:
        if self._loading:
            return
        if not self.has_due.isChecked():
            self._update(due=None, done=False)
            return
        d = self.due_edit.date()
        self._update(due=date(d.year(), d.month(), d.day()), done=self.due_done.isChecked())

    def _desc_dirty(self) -> None:
        if not self._loading:
            self._desc_timer.start()

    def _save_description(self) -> None:
        self._desc_timer.stop()
        text = self.desc.toPlainText()
        if not self._deleted and text != self.card.description:
            self._update(description=text)

    def _save_checklist(self, items: list[ChecklistItem]) -> None:
        self._update(checklist=items)

    def _add_item(self) -> None:
        text = self.new_item.text().strip()
        if text:
            self._save_checklist([*self.card.checklist, ChecklistItem(text)])
        self.new_item.clear()

    def _toggle_item(self, idx: int, checked: bool) -> None:
        if self._loading:
            return
        items = [ChecklistItem(i.text, i.done) for i in self.card.checklist]
        items[idx].done = checked
        self._save_checklist(items)

    def _remove_item(self, idx: int) -> None:
        items = [i for n, i in enumerate(self.card.checklist) if n != idx]
        self._save_checklist(items)

    def _move(self, _index: int) -> None:
        target = self.list_combo.currentData()
        if target is not None and target != self.card.list_id:
            self.repo.move_card(self.card_id, target, 0)
            self._reload()
            self.changed.emit()

    def _delete(self) -> None:
        if QMessageBox.question(self, "Supprimer la carte", f"Supprimer « {self.card.title} » ?") != QMessageBox.StandardButton.Yes:
            return
        self.delete_card()
        self.accept()

    def delete_card(self) -> None:
        self._deleted = True
        self.repo.delete_card(self.card_id)
        self.changed.emit()

    def done(self, result: int) -> None:
        # Une saisie en cours (description / titre) ne doit jamais se perdre à la fermeture.
        if not self._deleted:
            self._save_description()
            self._save_title()
        super().done(result)
