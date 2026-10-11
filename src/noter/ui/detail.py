"""Fiche d'un enregistrement : en-tête, timeline, transport, synthèse à gauche, transcript à droite."""
from __future__ import annotations

import bisect
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from noter.audio.waveform import compute_peaks, read_waveform
from noter.models import JobKind, Recording, RecordingStatus, Segment, format_date_fr, format_timestamp
from noter.service import Service
from noter.storage import files
from noter.ui import icons, theme
from noter.ui.player import AudioPlayer
from noter.ui.widgets.common import Pill, clear_layout, hline, mono_label, section_label, tool_button, vline
from noter.ui.widgets.timeline import WaveformTimeline
from noter.ui.widgets.transcript import TranscriptView

STATUS_LABEL = {
    RecordingStatus.RECORDING: ("Enregistrement", "pillRec"),
    RecordingStatus.RECORDED: ("À traiter", "pill"),
    RecordingStatus.TRANSCRIBING: ("Transcription…", "pillBusy"),
    RecordingStatus.TRANSCRIBED: ("Transcrit", "pillBusy"),
    RecordingStatus.SUMMARIZING: ("Résumé…", "pillBusy"),
    RecordingStatus.DONE: ("Prêt", "pillOk"),
    RecordingStatus.FAILED: ("Échec", "pillRec"),
}


def open_path(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif sys.platform.startswith("linux"):
        subprocess.Popen(["xdg-open", str(path)])
    else:
        subprocess.Popen(["explorer", str(path)])


class _PeaksSignals(QObject):
    done = Signal(str, list)


class _PeaksTask(QRunnable):
    """Calcule l'onde d'un ancien enregistrement sans la bloquer l'UI."""

    def __init__(self, recording_id: str, audio_path: Path, dir_path: Path):
        super().__init__()
        self.recording_id, self.audio_path, self.dir_path = recording_id, audio_path, dir_path
        self.signals = _PeaksSignals()

    def run(self) -> None:
        import json

        peaks = compute_peaks(self.audio_path)
        if peaks:
            try:
                (self.dir_path / "waveform.json").write_text(json.dumps(peaks), encoding="utf-8")
            except OSError:
                pass
        self.signals.done.emit(self.recording_id, peaks)


class RecordingDetail(QWidget):
    changed = Signal()

    def __init__(self, service: Service, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.service = service
        self.repo = service.repo
        self.rec: Recording | None = None
        self._segments: list[Segment] = []
        self._seg_starts: list[float] = []
        self._loading = False
        self._pool = QThreadPool.globalInstance()
        self._notes_timer = QTimer(self)
        self._notes_timer.setSingleShot(True)
        self._notes_timer.setInterval(800)
        self._notes_timer.timeout.connect(self._save_notes)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ─── En-tête ────────────────────────────────────────────
        head = QWidget()
        hl = QVBoxLayout(head)
        hl.setContentsMargins(28, 22, 28, 0)
        hl.setSpacing(8)
        self.title_edit = QLineEdit()
        self.title_edit.setObjectName("titleEdit")
        f = QFont()
        f.setPixelSize(24)
        f.setWeight(QFont.Weight.DemiBold)
        self.title_edit.setFont(f)
        self.title_edit.editingFinished.connect(self._save_title)
        hl.addWidget(self.title_edit)

        self.meta_row = QHBoxLayout()
        self.meta_row.setSpacing(14)
        self.meta_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        hl.addLayout(self.meta_row)

        edit_row = QHBoxLayout()
        edit_row.setSpacing(8)
        self.project = QComboBox()
        self.project.setEditable(True)
        self.project.setFixedWidth(180)
        self.project.lineEdit().setPlaceholderText("Projet")
        self.project.lineEdit().editingFinished.connect(self._save_project)
        self.project.activated.connect(lambda _: self._save_project())
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("tags, séparés par des virgules")
        self.tags.editingFinished.connect(self._save_tags)
        edit_row.addWidget(self.project)
        edit_row.addWidget(self.tags, 1)
        hl.addLayout(edit_row)

        tb = QHBoxLayout()
        tb.setSpacing(6)
        self.btn_retry = tool_button("refresh", "Relancer le traitement")
        self.btn_retry.clicked.connect(self._retry)
        self.btn_resum = tool_button("refresh", "Régénérer le résumé")
        self.btn_resum.clicked.connect(lambda: self._enqueue(JobKind.SUMMARIZE))
        self.btn_folder = tool_button("folder", "Dossier")
        self.btn_folder.clicked.connect(lambda: self.rec and open_path(self.rec.dir_path))
        self.btn_pdf = tool_button("file", "PDF")
        self.btn_pdf.clicked.connect(lambda: self.rec and open_path(self.rec.dir_path / files.PDF_NAME))
        self.btn_more = tool_button("more", "", tip="Plus")
        self.btn_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.btn_more)
        menu.addAction("Retranscrire", lambda: self._enqueue(JobKind.TRANSCRIBE))
        menu.addAction("Copier le résumé (Markdown)", self._copy_summary)
        menu.addAction("Copier le transcript", self._copy_transcript)
        menu.addSeparator()
        menu.addAction("Supprimer…", self._delete)
        self.btn_more.setMenu(menu)
        for b in (self.btn_retry, self.btn_resum, self.btn_folder, self.btn_pdf):
            tb.addWidget(b)
        tb.addStretch()
        tb.addWidget(self.btn_more)
        hl.addSpacing(4)
        hl.addLayout(tb)

        self.error_lab = QLabel()
        self.error_lab.setObjectName("error")
        self.error_lab.setWordWrap(True)
        self.error_lab.hide()
        hl.addWidget(self.error_lab)
        root.addWidget(head)

        # ─── Timeline + transport ───────────────────────────────
        tl_box = QWidget()
        tl = QVBoxLayout(tl_box)
        tl.setContentsMargins(28, 16, 28, 0)
        tl.setSpacing(6)
        self.timeline = WaveformTimeline()
        self.timeline.seek_requested.connect(lambda s: self.player.seek(s, play=False))
        tl.addWidget(self.timeline)
        tr = QHBoxLayout()
        tr.setSpacing(10)
        self.player = AudioPlayer()
        self.player.position_changed.connect(self._on_position)
        tr.addWidget(self.player, 1)
        self.legend = QHBoxLayout()
        self.legend.setSpacing(12)
        tr.addLayout(self.legend)
        tl.addLayout(tr)
        root.addWidget(tl_box)
        root.addSpacing(14)
        root.addWidget(hline())

        # ─── Corps : synthèse | transcript ───────────────────────
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.summary_area = QScrollArea()
        self.summary_area.setWidgetResizable(True)
        self.summary_area.setFrameShape(QFrame.Shape.NoFrame)
        self.summary_box = QWidget()
        self.summary_lay = QVBoxLayout(self.summary_box)
        self.summary_lay.setContentsMargins(28, 18, 24, 28)
        self.summary_lay.setSpacing(6)
        self.summary_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.summary_area.setWidget(self.summary_box)
        self.summary_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        body.addWidget(self.summary_area, 5)
        body.addWidget(vline())

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(24, 18, 20, 12)
        rl.setSpacing(10)
        tr_head = QHBoxLayout()
        tr_head.addWidget(section_label("Transcript"))
        tr_head.addStretch()
        self.follow = QCheckBox("Suivre la lecture")
        self.follow.setObjectName("follow")
        self.follow.setChecked(True)
        tr_head.addWidget(self.follow)
        rl.addLayout(tr_head)
        self.transcript = TranscriptView()
        self.transcript.doubleClicked.connect(lambda idx: self._seek_row(idx.row()))
        self.transcript.customContextMenuRequested.connect(self._segment_menu)
        self.transcript_stack = QStackedWidget()
        self.transcript_stack.addWidget(self.transcript)
        self.transcript_empty = QLabel("Pas encore de transcript.")
        self.transcript_empty.setObjectName("empty")
        self.transcript_empty.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.transcript_stack.addWidget(self.transcript_empty)
        rl.addWidget(self.transcript_stack, 1)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Notes…")
        self.notes.setFixedHeight(72)
        self.notes.textChanged.connect(self._notes_dirty)
        rl.addWidget(self.notes)
        body.addWidget(right, 6)
        root.addLayout(body, 1)

        self.setEnabled(False)

    # ─── Chargement ─────────────────────────────────────────────────

    def load(self, recording_id: str | None, seek_to: float | None = None, markers: list[float] | None = None) -> None:
        self._loading = True
        try:
            self.rec = self.repo.get_recording(recording_id) if recording_id else None
            if self.rec is None:
                self.setEnabled(False)
                self.player.load(None)
                return
            self.setEnabled(True)
            rec = self.rec
            t = theme.current()

            self.title_edit.setText(rec.title or "")
            self.title_edit.setPlaceholderText(rec.display_title)
            self._fill_meta(rec, t)

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
            self.btn_resum.setVisible(rec.status in (RecordingStatus.DONE, RecordingStatus.TRANSCRIBED, RecordingStatus.FAILED))
            self.btn_pdf.setVisible((rec.dir_path / files.PDF_NAME).exists())

            self._segments = self.repo.get_segments(rec.id)
            self._seg_starts = [s.start for s in self._segments]
            self.transcript.set_segments(self._segments)
            self.transcript_stack.setCurrentIndex(0 if self._segments else 1)
            self._fill_legend(t)
            self._fill_summary()

            peaks = read_waveform(rec.dir_path)
            self.timeline.set_data(peaks, rec.duration_s or 0.0, self._segments)
            self.timeline.set_markers(markers or [])
            if peaks is None and rec.audio_path.exists() and rec.status != RecordingStatus.RECORDING:
                task = _PeaksTask(rec.id, rec.audio_path, rec.dir_path)
                task.signals.done.connect(self._on_peaks)
                self._pool.start(task)

            self.player.load(rec.audio_path if rec.status != RecordingStatus.RECORDING else None)
            if seek_to is not None:
                self.player.seek(seek_to, play=False)
                self.timeline.set_position(seek_to)
                self._highlight_for(seek_to, scroll=True)
        finally:
            self._loading = False

    def refresh_if(self, recording_id: str) -> None:
        if self.rec and self.rec.id == recording_id:
            pos = self.player.position_seconds()
            self.load(recording_id)
            if pos:
                self.player.seek(pos, play=False)
                self.timeline.set_position(pos)

    def _on_peaks(self, recording_id: str, peaks: list) -> None:
        if self.rec and self.rec.id == recording_id and peaks:
            self.timeline.set_data(peaks, self.rec.duration_s or 0.0, self._segments)
            self.timeline.set_position(self.player.position_seconds())

    def _fill_meta(self, rec: Recording, t) -> None:
        clear_layout(self.meta_row)
        self.meta_row.addWidget(mono_label(format_date_fr(rec.started_at).capitalize()))
        self.meta_row.addWidget(mono_label(rec.duration_text))
        if rec.language:
            self.meta_row.addWidget(mono_label(rec.language.upper()))
        label, kind = STATUS_LABEL[rec.status]
        self.meta_row.addWidget(Pill(f"● {label}", kind))
        if rec.project:
            self.meta_row.addWidget(Pill(rec.project, "pill", swatch=theme.speaker_color(t, rec.project)))
        for tg in rec.tags[:4]:
            self.meta_row.addWidget(Pill(f"#{tg}", "pill"))
        self.meta_row.addStretch()

    def _fill_legend(self, t) -> None:
        clear_layout(self.legend)
        names: list[str] = []
        for s in self._segments:
            if s.speaker and s.speaker not in names:
                names.append(s.speaker)
        for name in names[:6]:
            w = QWidget()
            hl = QHBoxLayout(w)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(5)
            sw = QLabel()
            sw.setFixedSize(8, 8)
            sw.setStyleSheet(f"background: {theme.speaker_color(t, name).name()}; border-radius: 2px;")
            lab = QLabel(name)
            lab.setObjectName("meta")
            hl.addWidget(sw)
            hl.addWidget(lab)
            self.legend.addWidget(w)

    def _fill_summary(self) -> None:
        clear_layout(self.summary_lay)
        rec = self.rec
        summary = self.repo.get_summary(rec.id) if rec else None
        t = theme.current()
        if summary is None:
            msg = {
                RecordingStatus.RECORDING: "L’enregistrement est en cours.",
                RecordingStatus.RECORDED: "En attente de traitement.",
                RecordingStatus.TRANSCRIBING: "Transcription en cours…",
                RecordingStatus.TRANSCRIBED: "Transcrit. Le résumé arrive.",
                RecordingStatus.SUMMARIZING: "Résumé en cours…",
                RecordingStatus.FAILED: "Pas de résumé : le traitement a échoué.",
            }.get(rec.status if rec else RecordingStatus.RECORDED, "Pas encore de résumé.")
            self.summary_lay.addWidget(section_label("En bref"))
            lab = QLabel(msg)
            lab.setObjectName("empty")
            self.summary_lay.addWidget(lab)
            return

        self.summary_lay.addWidget(section_label("En bref"))
        tldr = QLabel(summary.tldr)
        tldr.setObjectName("tldr")
        tldr.setWordWrap(True)
        tldr.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary_lay.addWidget(tldr)

        for title, items, bullet in (("Points clés", summary.key_points, "•"), ("Décisions", summary.decisions, "▸")):
            if not items:
                continue
            self.summary_lay.addSpacing(12)
            self.summary_lay.addWidget(section_label(title))
            for it in items:
                lab = QLabel(f'<span style="color:{t.ink_4}">{bullet}</span>&nbsp;&nbsp;{_esc(it)}')
                lab.setObjectName("point")
                lab.setWordWrap(True)
                lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                self.summary_lay.addWidget(lab)

        if summary.actions:
            self.summary_lay.addSpacing(12)
            self.summary_lay.addWidget(section_label("Actions"))
            for i, a in enumerate(summary.actions):
                cb = QCheckBox()
                owner = f'<b style="color:{t.ink}">{_esc(a.owner)}</b>&nbsp;&nbsp;' if a.owner else ""
                due = f'&nbsp;&nbsp;<span style="font-family:\'{theme.MONO}\';font-size:11px;color:{t.ink_3}">{_esc(a.due)}</span>' if a.due else ""
                text = f'<s style="color:{t.ink_3}">{_esc(a.text)}</s>' if a.done else _esc(a.text)
                cb.setText("")
                row = QWidget()
                rl = QHBoxLayout(row)
                rl.setContentsMargins(0, 0, 0, 0)
                rl.setSpacing(0)
                cb.setChecked(a.done)
                cb.toggled.connect(lambda checked, idx=i: self._toggle_action(idx, checked))
                lab = QLabel(owner + text + due)
                lab.setObjectName("point")
                lab.setWordWrap(True)
                lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                lab.setCursor(Qt.CursorShape.PointingHandCursor)
                lab.mousePressEvent = lambda _e, c=cb: c.toggle()  # type: ignore[method-assign]
                rl.addWidget(cb, 0, Qt.AlignmentFlag.AlignTop)
                rl.addWidget(lab, 1)
                self.summary_lay.addWidget(row)

        self.summary_lay.addSpacing(14)
        foot = QLabel(f"Résumé généré par {summary.model}" + (f" · {summary.created_at:%d/%m %H:%M}" if summary.created_at else ""))
        foot.setObjectName("gen")
        self.summary_lay.addWidget(foot)

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
        if not self._loading and self.rec:
            self._notes_timer.start()

    def _save_notes(self) -> None:
        if self.rec and (self.notes.toPlainText() or None) != self.rec.notes:
            self._save(notes=self.notes.toPlainText() or None)

    def _toggle_action(self, idx: int, checked: bool) -> None:
        if not self.rec:
            return
        self.repo.set_action_done(self.rec.id, idx, checked)
        self.service.pipeline.render_outputs(self.rec.id)
        self._fill_summary()

    def _retry(self) -> None:
        if self.rec:
            self.service.jobs.retry(self.rec.id)
            self.changed.emit()

    def _enqueue(self, kind: JobKind) -> None:
        if self.rec:
            self.service.jobs.enqueue(self.rec.id, kind)
            self.changed.emit()

    def _copy_summary(self) -> None:
        if self.rec and (summary := self.repo.get_summary(self.rec.id)):
            QApplication.clipboard().setText(files.summary_markdown(self.rec, summary))

    def _copy_transcript(self) -> None:
        if self._segments:
            QApplication.clipboard().setText(files.transcript_plain(self._segments))

    def _delete(self) -> None:
        if not self.rec:
            return
        ok = QMessageBox.question(self, "Supprimer", f"Supprimer « {self.rec.display_title} » et ses fichiers ?",
                                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ok == QMessageBox.StandardButton.Yes:
            self.player.stop()
            self.service.delete_recording(self.rec.id)
            self.load(None)
            self.changed.emit()

    # ─── Transcript ↔ lecteur ───────────────────────────────────────

    def _seek_row(self, row: int) -> None:
        if 0 <= row < len(self._segments):
            self.player.seek(self._segments[row].start)

    def _on_position(self, seconds: float) -> None:
        self.timeline.set_position(seconds)
        self._highlight_for(seconds, scroll=self.follow.isChecked())

    def _highlight_for(self, seconds: float, scroll: bool) -> None:
        if not self._seg_starts:
            return
        row = max(0, bisect.bisect_right(self._seg_starts, seconds) - 1)
        self.transcript.set_current(row, scroll=scroll)

    def _segment_menu(self, pos) -> None:
        idx = self.transcript.indexAt(pos)
        seg = self.transcript.segment_at_row(idx.row()) if idx.isValid() else None
        if seg is None or not self.rec:
            return
        menu = QMenu(self)
        a = QAction("Écouter ce passage", menu)
        a.triggered.connect(lambda: self.player.seek(seg.start))
        menu.addAction(a)
        b = QAction(f"Renommer le speaker « {seg.speaker or '?'} »…", menu)
        b.triggered.connect(lambda: self._rename_speaker(seg.speaker))
        menu.addAction(b)
        c = QAction("Copier le texte", menu)
        c.triggered.connect(lambda: QApplication.clipboard().setText(seg.text))
        menu.addAction(c)
        menu.exec(self.transcript.mapToGlobal(pos))

    def _rename_speaker(self, old: str | None) -> None:
        if not self.rec:
            return
        new, ok = QInputDialog.getText(self, "Renommer le speaker", f"Nouveau nom pour « {old or '?'} » :")
        if ok and new.strip():
            self.repo.rename_speaker(self.rec.id, old, new.strip())
            self.service.pipeline.render_outputs(self.rec.id)
            self.load(self.rec.id)


def _esc(s: str | None) -> str:
    from html import escape

    return escape(s or "")


_ = (QPushButton, icons, format_timestamp)
