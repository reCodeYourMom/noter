"""Panneau de détail d'un enregistrement : en-tête éditable, résumé, actions, transcript synchronisé."""
from __future__ import annotations

import bisect
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from noter.models import JobKind, Recording, RecordingStatus, Segment, format_timestamp
from noter.service import Service
from noter.storage import files
from noter.ui.player import AudioPlayer
from noter.ui.style import STATUS_COLOR, STATUS_LABEL


def _section(text: str) -> QLabel:
    lab = QLabel(text.upper())
    lab.setObjectName("section")
    return lab


def _open_path(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif sys.platform.startswith("linux"):
        subprocess.Popen(["xdg-open", str(path)])
    else:
        subprocess.Popen(["explorer", str(path)])


class RecordingDetail(QWidget):
    changed = Signal()  # métadonnées modifiées → la liste se rafraîchit

    def __init__(self, service: Service, parent=None):
        super().__init__(parent)
        self.service = service
        self.repo = service.repo
        self.rec: Recording | None = None
        self._segments: list[Segment] = []
        self._seg_starts: list[float] = []
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        # ─── En-tête ────────────────────────────────────────────
        self.title_edit = QLineEdit()
        self.title_edit.setObjectName("titleEdit")
        self.title_edit.setPlaceholderText("Titre de l'enregistrement")
        self.title_edit.editingFinished.connect(self._save_title)
        root.addWidget(self.title_edit)

        meta_row = QHBoxLayout()
        self.meta = QLabel()
        self.meta.setObjectName("meta")
        self.status_lab = QLabel()
        meta_row.addWidget(self.meta)
        meta_row.addWidget(self.status_lab)
        meta_row.addStretch()
        root.addLayout(meta_row)

        tag_row = QHBoxLayout()
        self.project = QComboBox()
        self.project.setEditable(True)
        self.project.setMinimumWidth(160)
        self.project.lineEdit().setPlaceholderText("Projet")
        self.project.lineEdit().editingFinished.connect(self._save_project)
        self.project.activated.connect(lambda _: self._save_project())
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("tags, séparés, par, des, virgules")
        self.tags.editingFinished.connect(self._save_tags)
        tag_row.addWidget(QLabel("Projet"))
        tag_row.addWidget(self.project)
        tag_row.addWidget(QLabel("Tags"))
        tag_row.addWidget(self.tags, 1)
        root.addLayout(tag_row)

        # ─── Barre d'actions ────────────────────────────────────
        btn_row = QHBoxLayout()
        self.btn_retry = QPushButton("Relancer le traitement")
        self.btn_retry.clicked.connect(self._retry)
        self.btn_resum = QPushButton("Régénérer le résumé")
        self.btn_resum.clicked.connect(lambda: self._enqueue(JobKind.SUMMARIZE))
        self.btn_more = QToolButton()
        self.btn_more.setText("Plus ▾")
        self.btn_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.btn_more)
        menu.addAction("Retranscrire", lambda: self._enqueue(JobKind.TRANSCRIBE))
        menu.addAction("Ouvrir le dossier", lambda: self.rec and _open_path(self.rec.dir_path))
        menu.addAction("Ouvrir le PDF", lambda: self.rec and _open_path(self.rec.dir_path / files.PDF_NAME))
        menu.addAction("Copier le résumé (Markdown)", self._copy_summary)
        menu.addSeparator()
        menu.addAction("Supprimer…", self._delete)
        self.btn_more.setMenu(menu)
        btn_row.addWidget(self.btn_retry)
        btn_row.addWidget(self.btn_resum)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_more)
        root.addLayout(btn_row)

        self.error_lab = QLabel()
        self.error_lab.setWordWrap(True)
        self.error_lab.setStyleSheet(f"color: {STATUS_COLOR[RecordingStatus.FAILED]};")
        self.error_lab.hide()
        root.addWidget(self.error_lab)

        # ─── Lecteur ────────────────────────────────────────────
        self.player = AudioPlayer()
        self.player.position_changed.connect(self._on_position)
        root.addWidget(self.player)

        # ─── Onglets résumé / transcript / notes ────────────────
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        # Résumé
        self.summary_area = QScrollArea()
        self.summary_area.setWidgetResizable(True)
        self.summary_area.setFrameShape(QFrame.Shape.NoFrame)
        self.summary_box = QWidget()
        self.summary_lay = QVBoxLayout(self.summary_box)
        self.summary_lay.setContentsMargins(4, 4, 4, 4)
        self.summary_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.summary_area.setWidget(self.summary_box)
        self.tabs.addTab(self.summary_area, "Résumé")

        # Transcript
        self.seg_list = QListWidget()
        self.seg_list.setObjectName("segments")
        self.seg_list.setWordWrap(True)
        self.seg_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.seg_list.customContextMenuRequested.connect(self._segment_menu)
        self.seg_list.itemDoubleClicked.connect(self._seek_item)
        tr_box = QWidget()
        tr_lay = QVBoxLayout(tr_box)
        tr_lay.setContentsMargins(0, 0, 0, 0)
        tr_top = QHBoxLayout()
        self.follow = QCheckBox("Suivre la lecture")
        self.follow.setChecked(True)
        tr_top.addWidget(QLabel("Double-clic sur une ligne pour écouter ce passage"))
        tr_top.addStretch()
        tr_top.addWidget(self.follow)
        tr_lay.addLayout(tr_top)
        tr_lay.addWidget(self.seg_list, 1)
        self.tabs.addTab(tr_box, "Transcript")

        # Notes
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Notes libres sur cet enregistrement…")
        self.notes.textChanged.connect(self._notes_dirty)
        self._notes_timer = None
        self.tabs.addTab(self.notes, "Notes")

        self.setEnabled(False)

    # ─── Chargement ─────────────────────────────────────────────────

    def load(self, recording_id: str | None, seek_to: float | None = None) -> None:
        self._loading = True
        try:
            self.rec = self.repo.get_recording(recording_id) if recording_id else None
            if self.rec is None:
                self.setEnabled(False)
                self.player.load(None)
                return
            self.setEnabled(True)
            rec = self.rec
            self.title_edit.setText(rec.title or "")
            self.title_edit.setPlaceholderText(rec.display_title)
            self.meta.setText(f"{rec.started_at:%A %d %B %Y · %H:%M}   ·   {rec.duration_text}   ·   {(rec.language or '').upper()}")
            self.status_lab.setText(f"● {STATUS_LABEL[rec.status]}")
            self.status_lab.setStyleSheet(f"color: {STATUS_COLOR[rec.status]}; font-weight: 600;")

            self.project.blockSignals(True)
            self.project.clear()
            self.project.addItem("")
            self.project.addItems(self.repo.all_projects())
            self.project.setCurrentText(rec.project or "")
            self.project.blockSignals(False)
            self.tags.setText(", ".join(rec.tags))
            self.notes.blockSignals(True)
            self.notes.setPlainText(rec.notes or "")
            self.notes.blockSignals(False)

            jobs = self.repo.list_jobs(recording_id=rec.id, limit=1)
            if rec.status == RecordingStatus.FAILED and jobs and jobs[0].error:
                self.error_lab.setText(f"Dernière erreur : {jobs[0].error}")
                self.error_lab.show()
            else:
                self.error_lab.hide()
            self.btn_retry.setVisible(rec.status in (RecordingStatus.FAILED, RecordingStatus.RECORDED))
            self.btn_resum.setEnabled(rec.status in (RecordingStatus.DONE, RecordingStatus.TRANSCRIBED, RecordingStatus.FAILED))

            self._segments = self.repo.get_segments(rec.id)
            self._seg_starts = [s.start for s in self._segments]
            self._fill_segments()
            self._fill_summary()
            self.player.load(rec.audio_path)
            if seek_to is not None:
                self.player.seek(seek_to, play=False)
                self._highlight_for(seek_to, scroll=True)
                self.tabs.setCurrentIndex(1)
        finally:
            self._loading = False

    def refresh_if(self, recording_id: str) -> None:
        if self.rec and self.rec.id == recording_id:
            pos = self.player.slider.value() / 1000
            self.load(recording_id, seek_to=None)
            if pos:
                self.player.seek(pos, play=False)

    def _fill_summary(self) -> None:
        while self.summary_lay.count():
            item = self.summary_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        rec = self.rec
        summary = self.repo.get_summary(rec.id) if rec else None
        if summary is None:
            msg = {
                RecordingStatus.RECORDED: "En attente de traitement.",
                RecordingStatus.TRANSCRIBING: "Transcription en cours…",
                RecordingStatus.TRANSCRIBED: "Transcrit. Résumé en attente.",
                RecordingStatus.SUMMARIZING: "Résumé en cours…",
                RecordingStatus.FAILED: "Pas de résumé (traitement en échec).",
            }.get(rec.status if rec else RecordingStatus.RECORDED, "Pas encore de résumé.")
            lab = QLabel(msg)
            lab.setObjectName("empty")
            self.summary_lay.addWidget(lab)
            return
        tldr = QLabel(summary.tldr)
        tldr.setObjectName("tldr")
        tldr.setWordWrap(True)
        tldr.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary_lay.addWidget(tldr)

        for title, items in (("Points clés", summary.key_points), ("Décisions", summary.decisions)):
            if not items:
                continue
            self.summary_lay.addWidget(_section(title))
            for it in items:
                lab = QLabel(f"•  {it}")
                lab.setWordWrap(True)
                lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                self.summary_lay.addWidget(lab)

        if summary.actions:
            self.summary_lay.addWidget(_section("Actions"))
            for i, a in enumerate(summary.actions):
                cb = QCheckBox(a.display)
                cb.setChecked(a.done)
                cb.toggled.connect(lambda checked, idx=i: self._toggle_action(idx, checked))
                self.summary_lay.addWidget(cb)

        foot = QLabel(f"Généré par {summary.model}" + (f" · {summary.created_at:%d/%m %H:%M}" if summary.created_at else ""))
        foot.setObjectName("meta")
        self.summary_lay.addWidget(foot)

    def _fill_segments(self) -> None:
        self.seg_list.clear()
        mono = QFont("Menlo" if sys.platform == "darwin" else "monospace")
        mono.setPointSize(10)
        for s in self._segments:
            spk = f"{s.speaker}  " if s.speaker else ""
            item = QListWidgetItem(f"{format_timestamp(s.start)}   {spk}{s.text}")
            item.setToolTip(f"{format_timestamp(s.start)} → {format_timestamp(s.end)}")
            self.seg_list.addItem(item)
        if not self._segments:
            self.seg_list.addItem(QListWidgetItem("Pas encore de transcript."))

    # ─── Édition ────────────────────────────────────────────────────

    def _save(self, **fields) -> None:
        if self._loading or not self.rec:
            return
        self.rec = self.service.update_metadata(self.rec.id, **fields)
        self.changed.emit()

    def _save_title(self) -> None:
        if self.rec and (self.title_edit.text().strip() or None) != self.rec.title:
            self._save(title=self.title_edit.text().strip() or None)
            self.title_edit.setPlaceholderText(self.rec.display_title)

    def _save_project(self) -> None:
        if self.rec and (self.project.currentText().strip() or None) != self.rec.project:
            self._save(project=self.project.currentText().strip() or None)

    def _save_tags(self) -> None:
        if not self.rec:
            return
        tags = [t.strip() for t in self.tags.text().split(",") if t.strip()]
        if tags != self.rec.tags:
            self._save(tags=tags)
            self.tags.setText(", ".join(self.rec.tags))

    def _notes_dirty(self) -> None:
        if self._loading or not self.rec:
            return
        from PySide6.QtCore import QTimer

        if self._notes_timer is None:
            self._notes_timer = QTimer(self)
            self._notes_timer.setSingleShot(True)
            self._notes_timer.setInterval(800)
            self._notes_timer.timeout.connect(lambda: self._save(notes=self.notes.toPlainText() or None))
        self._notes_timer.start()

    def _toggle_action(self, idx: int, checked: bool) -> None:
        if not self.rec:
            return
        self.repo.set_action_done(self.rec.id, idx, checked)
        self.service.pipeline.render_outputs(self.rec.id)

    def _retry(self) -> None:
        if self.rec:
            self.service.jobs.retry(self.rec.id)
            self.changed.emit()

    def _enqueue(self, kind: JobKind) -> None:
        if self.rec:
            self.service.jobs.enqueue(self.rec.id, kind)
            self.changed.emit()

    def _copy_summary(self) -> None:
        if not self.rec:
            return
        summary = self.repo.get_summary(self.rec.id)
        if summary is None:
            return
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(files.summary_markdown(self.rec, summary))

    def _delete(self) -> None:
        if not self.rec:
            return
        ok = QMessageBox.question(
            self, "Supprimer", f"Supprimer « {self.rec.display_title} » et ses fichiers ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ok == QMessageBox.StandardButton.Yes:
            self.player.stop()
            self.service.delete_recording(self.rec.id)
            self.load(None)
            self.changed.emit()

    # ─── Transcript ↔ lecteur ───────────────────────────────────────

    def _seek_item(self, item: QListWidgetItem) -> None:
        row = self.seg_list.row(item)
        if 0 <= row < len(self._segments):
            self.player.seek(self._segments[row].start)

    def _on_position(self, seconds: float) -> None:
        if self.follow.isChecked() and self.tabs.currentIndex() == 1:
            self._highlight_for(seconds, scroll=True)

    def _highlight_for(self, seconds: float, scroll: bool) -> None:
        if not self._seg_starts:
            return
        row = max(0, bisect.bisect_right(self._seg_starts, seconds) - 1)
        if self.seg_list.currentRow() != row:
            self.seg_list.setCurrentRow(row)
            if scroll:
                self.seg_list.scrollToItem(self.seg_list.item(row))

    def _segment_menu(self, pos) -> None:
        item = self.seg_list.itemAt(pos)
        row = self.seg_list.row(item) if item else -1
        if row < 0 or row >= len(self._segments) or not self.rec:
            return
        seg = self._segments[row]
        menu = QMenu(self)
        a_play = QAction("Écouter ce passage", menu)
        a_play.triggered.connect(lambda: self.player.seek(seg.start))
        menu.addAction(a_play)
        a_rename = QAction(f"Renommer le speaker « {seg.speaker or '?'} »…", menu)
        a_rename.triggered.connect(lambda: self._rename_speaker(seg.speaker))
        menu.addAction(a_rename)
        a_copy = QAction("Copier le texte", menu)
        a_copy.triggered.connect(lambda: __import__("PySide6.QtWidgets").QtWidgets.QApplication.clipboard().setText(seg.text))
        menu.addAction(a_copy)
        menu.exec(self.seg_list.mapToGlobal(pos))

    def _rename_speaker(self, old: str | None) -> None:
        if not self.rec:
            return
        new, ok = QInputDialog.getText(self, "Renommer le speaker", f"Nouveau nom pour « {old or '?'} » :")
        if ok and new.strip():
            self.repo.rename_speaker(self.rec.id, old, new.strip())
            self.service.pipeline.render_outputs(self.rec.id)
            self.load(self.rec.id)
            self.tabs.setCurrentIndex(1)


_ = (QColor, QSizePolicy, QSplitter)  # imports gardés pour les sous-classes futures
