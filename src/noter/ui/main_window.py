"""Fenêtre principale : rail · liste · fiche / console / état vide."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from noter.models import Job, JobStatus, Recording, RecordingStatus, format_date_fr, format_timestamp
from noter.service import AUDIO_EXTENSIONS
from noter.storage.repo import SearchHit
from noter.ui import icons, theme
from noter.ui.bridge import ServiceBridge
from noter.ui.detail import RecordingDetail
from noter.ui.widgets.console import RecordingConsole
from noter.ui.widgets.empty import EmptyState
from noter.ui.widgets.rail import NavKey, NavRail
from noter.ui.widgets.recording_list import RecordingDelegate, RecordingListModel, RecordingRole

JOB_LABEL = {"transcribe": "Transcription", "summarize": "Résumé"}


class MainWindow(QMainWindow):
    def __init__(self, bridge: ServiceBridge):
        super().__init__()
        self.bridge = bridge
        self.service = bridge.service
        self.repo = self.service.repo
        self.setWindowTitle("Noter")
        self.resize(1180, 760)
        self.setMinimumSize(QSize(960, 600))
        self.setAcceptDrops(True)
        self._build()
        self._shortcuts()

        bridge.data_changed.connect(self._schedule_refresh)
        bridge.job_changed.connect(self._on_job)
        bridge.recording_started.connect(self._on_rec_started)
        bridge.recording_stopped.connect(self._on_rec_stopped)
        bridge.recording_tick.connect(self.console.tick)
        bridge.error.connect(lambda msg: QMessageBox.warning(self, "Noter", msg))

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(150)
        self._refresh_timer.timeout.connect(self.refresh)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1500)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start()
        self.refresh()
        if self.service.is_recording and self.service.current_recording:
            self._on_rec_started(self.service.current_recording)
        elif self.list_model.recording_count():
            self.list_view.setCurrentIndex(self.list_model.index(self.list_model.first_recording_row()))

    # ─── Construction ───────────────────────────────────────────────

    def _build(self) -> None:
        t = theme.current()
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.rail = NavRail()
        self.rail.selected.connect(self._on_nav)
        self.rail.settings_requested.connect(self._open_settings)
        root.addWidget(self.rail)

        # Colonne liste
        listcol = QWidget()
        listcol.setObjectName("listcol")
        listcol.setFixedWidth(340)
        ll = QVBoxLayout(listcol)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(14, 14, 14, 10)
        top.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher    ⌘F")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.icon("search", t.ink_3, 14), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._on_search_text)
        self.search.returnPressed.connect(self._run_search)
        self.btn_record = QPushButton("  Enregistrer")
        self.btn_record.setObjectName("primary")
        self.btn_record.setIcon(_rec_dot_icon(t))
        self.btn_record.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_record.setToolTip("Micro + audio système (⌘R)")
        self.btn_record.clicked.connect(lambda: self.bridge.start_recording(True))
        top.addWidget(self.search, 1)
        top.addWidget(self.btn_record)
        ll.addLayout(top)

        self.stack = QStackedWidget()
        self.list_model = RecordingListModel(self.repo)
        self.list_view = QListView()
        self.list_view.setModel(self.list_model)
        self.list_view.setItemDelegate(RecordingDelegate(self.list_view))
        self.list_view.setMouseTracking(True)
        self.list_view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.list_view.selectionModel().currentChanged.connect(self._on_select)
        self.stack.addWidget(self.list_view)
        self.results = QListWidget()
        self.results.setWordWrap(True)
        self.results.setMouseTracking(True)
        self.results.itemClicked.connect(self._on_result)
        self.stack.addWidget(self.results)
        self.list_empty = QLabel("Rien ici pour l’instant")
        self.list_empty.setObjectName("empty")
        self.list_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.list_empty)
        ll.addWidget(self.stack, 1)
        root.addWidget(listcol)

        # Zone principale
        self.main_stack = QStackedWidget()
        self.detail = RecordingDetail(self.service)
        self.detail.changed.connect(self._schedule_refresh)
        self.console = RecordingConsole()
        self.console.stop_requested.connect(self.bridge.stop_recording)
        self.console.title_changed.connect(self._set_live_title)
        self.empty = EmptyState(
            "Ton premier enregistrement",
            "Lance un call, clique Enregistrer, et Noter s’occupe du transcript et du compte-rendu. Tu peux aussi déposer un fichier audio ici.",
        )
        self.empty.record_requested.connect(lambda: self.bridge.start_recording(True))
        self.empty.import_requested.connect(self._import_dialog)
        self.placeholder = EmptyState("Sélectionne un enregistrement", "Ou lance-en un nouveau avec ⌘R.", actions=False)
        for w in (self.detail, self.console, self.empty, self.placeholder):
            self.main_stack.addWidget(w)
        self.main_stack.setCurrentWidget(self.placeholder)
        root.addWidget(self.main_stack, 1)
        self.setCentralWidget(central)

    def _shortcuts(self) -> None:
        def act(seq: str, fn):
            a = QAction(self)
            a.setShortcut(QKeySequence(seq))
            a.triggered.connect(fn)
            self.addAction(a)
            return a

        self.a_record = act("Ctrl+R", lambda: self.bridge.start_recording(True))
        self.a_record_mic = act("Ctrl+Shift+R", lambda: self.bridge.start_recording(False))
        self.a_stop = act("Ctrl+.", self.bridge.stop_recording)
        self.a_import = act("Ctrl+I", self._import_dialog)
        self.a_settings = act("Ctrl+,", self._open_settings)
        act("Ctrl+F", lambda: (self.search.setFocus(), self.search.selectAll()))
        act("Ctrl+Backspace", lambda: self.detail._delete() if self.detail.rec and self.main_stack.currentWidget() is self.detail else None)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._run_search)

    # ─── Rafraîchissement ───────────────────────────────────────────

    def _schedule_refresh(self) -> None:
        self._refresh_timer.start()

    def refresh(self) -> None:
        current = self.detail.rec.id if self.detail.rec else None
        all_recs = self.repo.list_recordings(limit=1000)
        counts = {
            "all": len(all_recs),
            "active": sum(1 for r in all_recs if r.status not in (RecordingStatus.DONE, RecordingStatus.FAILED)),
            "failed": sum(1 for r in all_recs if r.status == RecordingStatus.FAILED),
        }
        proj: dict[str, int] = {}
        tags: dict[str, int] = {}
        for r in all_recs:
            if r.project:
                proj[r.project] = proj.get(r.project, 0) + 1
            for tg in r.tags:
                tags[tg] = tags.get(tg, 0) + 1
        self.rail.populate(counts, sorted(proj.items()), sorted(tags.items()))

        self.list_model.refresh()
        searching = bool(self.search.text().strip())
        if not searching:
            if self.list_model.recording_count() == 0:
                self.stack.setCurrentWidget(self.list_empty)
            else:
                self.stack.setCurrentWidget(self.list_view)
        if not all_recs and not self.service.is_recording:
            self.main_stack.setCurrentWidget(self.empty)
        elif self.main_stack.currentWidget() is self.empty:
            self.main_stack.setCurrentWidget(self.placeholder)

        if current:
            row = self.list_model.row_of(current)
            if row >= 0:
                self.list_view.selectionModel().blockSignals(True)
                self.list_view.setCurrentIndex(self.list_model.index(row))
                self.list_view.selectionModel().blockSignals(False)
            if self.main_stack.currentWidget() is self.detail:
                self.detail.refresh_if(current)
        self._refresh_status()

    def _refresh_status(self) -> None:
        pending = self.repo.pending_job_count()
        cur = self.service.jobs.current
        if cur:
            rec = self.repo.get_recording(cur.recording_id)
            label = JOB_LABEL.get(str(cur.kind), str(cur.kind))
            sub = (rec.display_title if rec else cur.recording_id[:8]) + (f" · {pending - 1} en file" if pending > 1 else "")
            self.rail.set_status(label, sub, busy=True)
        elif pending:
            self.rail.set_status(f"{pending} en file", "", busy=True)
        else:
            self.rail.set_status(None)

    # ─── Navigation / sélection ─────────────────────────────────────

    def _on_nav(self, key: NavKey) -> None:
        f = self.list_model.filter
        f.kind, f.value = key.kind, key.value
        self.search.clear()
        self.refresh()
        row = self.list_model.first_recording_row()
        if row >= 0:
            self.list_view.setCurrentIndex(self.list_model.index(row))

    def _on_select(self, current, _previous) -> None:
        rec: Recording | None = current.data(RecordingRole) if current.isValid() else None
        if rec is None:
            return
        if rec.status == RecordingStatus.RECORDING and self.service.is_recording:
            self.main_stack.setCurrentWidget(self.console)
            return
        self.show_recording(rec.id)

    def show_recording(self, recording_id: str | None, seek_to: float | None = None, markers: list[float] | None = None) -> None:
        if recording_id is None:
            self.detail.load(None)
            self.main_stack.setCurrentWidget(self.placeholder)
            return
        self.detail.load(recording_id, seek_to=seek_to, markers=markers)
        self.main_stack.setCurrentWidget(self.detail)

    # ─── Recherche ──────────────────────────────────────────────────

    def _on_search_text(self, text: str) -> None:
        if not text.strip():
            self._search_timer.stop()
            self.refresh()
            return
        self._search_timer.start()

    def _run_search(self) -> None:
        q = self.search.text().strip()
        if not q:
            return
        hits = self.repo.search(q, limit=60)
        self.results.clear()
        if not hits:
            item = QListWidgetItem(f"Aucun résultat pour « {q} »")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.results.addItem(item)
        for h in hits:
            self.results.addItem(_hit_item(h))
        self.stack.setCurrentWidget(self.results)

    def _on_result(self, item: QListWidgetItem) -> None:
        hit: SearchHit | None = item.data(Qt.ItemDataRole.UserRole)
        if hit:
            markers = [x.start_s for x in self.repo.search(self.search.text().strip(), limit=200) if x.recording.id == hit.recording.id and x.start_s is not None]
            self.show_recording(hit.recording.id, seek_to=hit.start_s, markers=markers)

    # ─── Enregistrement ─────────────────────────────────────────────

    def _on_rec_started(self, rec: Recording) -> None:
        self.btn_record.setEnabled(False)
        self.a_record.setEnabled(False)
        self.a_record_mic.setEnabled(False)
        with_sys = "system" in str(rec.source)
        self.console.begin(rec, "Micro + audio système (BlackHole)" if with_sys else "Micro seul", with_sys)
        self.main_stack.setCurrentWidget(self.console)
        self.refresh()
        row = self.list_model.row_of(rec.id)
        if row >= 0:
            self.list_view.selectionModel().blockSignals(True)
            self.list_view.setCurrentIndex(self.list_model.index(row))
            self.list_view.selectionModel().blockSignals(False)

    def _on_rec_stopped(self, rec: Recording) -> None:
        self.console.end()
        self.btn_record.setEnabled(True)
        self.a_record.setEnabled(True)
        self.a_record_mic.setEnabled(True)
        self.show_recording(rec.id)
        self.refresh()

    def _set_live_title(self, title: str) -> None:
        rec = self.service.current_recording
        if rec and (title or None) != rec.title:
            self.repo.update_recording(rec.id, title=title or None)
            rec.title = title or None
            self._schedule_refresh()

    def _on_job(self, job: Job) -> None:
        if job.status == JobStatus.FAILED and job.error:
            self.statusBar().showMessage(f"Échec {JOB_LABEL.get(str(job.kind), job.kind)} : {job.error}", 10000)

    # ─── Import ─────────────────────────────────────────────────────

    def _import_dialog(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(AUDIO_EXTENSIONS))
        paths, _ = QFileDialog.getOpenFileNames(self, "Importer des fichiers audio", "", f"Audio ({exts})")
        if paths:
            self.bridge.import_files(paths)

    def dragEnterEvent(self, e: QDragEnterEvent) -> None:  # noqa: N802
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(tuple(AUDIO_EXTENSIONS)) for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent) -> None:  # noqa: N802
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile().lower().endswith(tuple(AUDIO_EXTENSIONS))]
        if paths:
            self.bridge.import_files(paths)

    # ─── Divers ─────────────────────────────────────────────────────

    def _open_settings(self) -> None:
        from noter.ui.settings_dialog import SettingsDialog

        dlg = SettingsDialog(self.service.settings, self)
        if dlg.exec():
            dlg.save()
            self.statusBar().showMessage("Réglages enregistrés : relance Noter pour les appliquer.", 6000)

    def closeEvent(self, e: QCloseEvent) -> None:  # noqa: N802
        e.ignore()
        self.hide()


def _rec_dot_icon(t):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

    ic = QIcon()
    for scale in (1, 2):
        px = 10 * scale
        pm = QPixmap(px, px)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t.rec))
        p.drawEllipse(QRectF(1 * scale, 1 * scale, 8 * scale, 8 * scale))
        p.end()
        pm.setDevicePixelRatio(scale)
        ic.addPixmap(pm)
    return ic


def _hit_item(h: SearchHit) -> QListWidgetItem:
    where = {"segment": "transcript", "summary": "résumé", "title": "titre"}[h.kind]
    ts = f" @ {format_timestamp(h.start_s)}" if h.start_s is not None else ""
    snippet = h.snippet.replace("[", "«").replace("]", "»")
    item = QListWidgetItem(f"{h.recording.display_title}  ·  {format_date_fr(h.recording.started_at, with_time=False)}  ·  {where}{ts}\n{snippet}")
    item.setData(Qt.ItemDataRole.UserRole, h)
    return item
