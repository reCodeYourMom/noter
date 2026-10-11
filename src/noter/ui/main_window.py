"""Fenêtre principale : barre d'outils, filtres, liste, détail, barre d'enregistrement, recherche."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from noter.models import Job, JobStatus, Recording, RecordingStatus, format_timestamp
from noter.service import AUDIO_EXTENSIONS
from noter.storage.repo import SearchHit
from noter.ui.bridge import ServiceBridge
from noter.ui.detail import RecordingDetail
from noter.ui.models import RecordingDelegate, RecordingListModel, RecordingRole
from noter.ui.style import ACCENT, QSS, dot_icon

FILTER_ALL, FILTER_ACTIVE, FILTER_FAILED, FILTER_PROJECT, FILTER_TAG = range(5)


class RecordingBar(QFrame):
    """Bandeau rouge visible pendant un enregistrement."""

    def __init__(self, bridge: ServiceBridge, parent=None):
        super().__init__(parent)
        self.setObjectName("recbar")
        self.bridge = bridge
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        self.label = QLabel("● REC 00:00")
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setTextVisible(False)
        self.level.setFixedWidth(120)
        self.level.setFixedHeight(8)
        self.sys_label = QLabel("")
        stop = QPushButton("Arrêter")
        stop.clicked.connect(bridge.stop_recording)
        lay.addWidget(self.label)
        lay.addWidget(self.level)
        lay.addWidget(self.sys_label)
        lay.addStretch()
        lay.addWidget(stop)
        bridge.recording_tick.connect(self._tick)
        self.hide()

    def _tick(self, elapsed: float, levels: dict) -> None:
        self.label.setText(f"● REC {format_timestamp(elapsed)}")
        mic = levels.get("MIC", 0.0)
        self.level.setValue(min(100, int(mic * 400)))
        self.sys_label.setText("micro + système" if "SYS" in levels else "micro seul")


class MainWindow(QMainWindow):
    def __init__(self, bridge: ServiceBridge):
        super().__init__()
        self.bridge = bridge
        self.service = bridge.service
        self.repo = self.service.repo
        self.setWindowTitle("Noter")
        self.resize(1180, 760)
        self.setMinimumSize(QSize(900, 560))
        self.setAcceptDrops(True)
        self.setStyleSheet(QSS)

        self._build_toolbar()
        self._build_body()
        self.setStatusBar(QStatusBar())
        self.status_job = QLabel("")
        self.statusBar().addPermanentWidget(self.status_job)

        bridge.data_changed.connect(self._schedule_refresh)
        bridge.job_changed.connect(self._on_job)
        bridge.recording_started.connect(self._on_rec_started)
        bridge.recording_stopped.connect(self._on_rec_stopped)
        bridge.error.connect(lambda msg: QMessageBox.warning(self, "Noter", msg))

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(150)
        self._refresh_timer.timeout.connect(self.refresh)
        self.refresh()
        if self.service.is_recording:
            self._on_rec_started(self.service.current_recording)

    # ─── Construction ───────────────────────────────────────────────

    def _build_toolbar(self) -> None:
        tb = QToolBar("Principal")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        tb.setIconSize(QSize(14, 14))
        self.addToolBar(tb)

        self.a_record = QAction(dot_icon(ACCENT), "Enregistrer", self)
        self.a_record.setShortcut(QKeySequence("Ctrl+R"))
        self.a_record.setToolTip("Micro + audio système (⌘R)")
        self.a_record.triggered.connect(lambda: self.bridge.start_recording(True))
        self.a_record_mic = QAction("Micro seul", self)
        self.a_record_mic.setShortcut(QKeySequence("Ctrl+Shift+R"))
        self.a_record_mic.triggered.connect(lambda: self.bridge.start_recording(False))
        self.a_stop = QAction("Arrêter", self)
        self.a_stop.setShortcut(QKeySequence("Ctrl+."))
        self.a_stop.triggered.connect(self.bridge.stop_recording)
        self.a_stop.setEnabled(False)
        self.a_import = QAction("Importer…", self)
        self.a_import.setShortcut(QKeySequence("Ctrl+I"))
        self.a_import.triggered.connect(self._import_dialog)
        self.a_settings = QAction("Réglages…", self)
        self.a_settings.setShortcut(QKeySequence("Ctrl+,"))
        self.a_settings.triggered.connect(self._open_settings)

        for a in (self.a_record, self.a_record_mic, self.a_stop):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.a_import)
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy().Expanding, spacer.sizePolicy().verticalPolicy())
        tb.addWidget(spacer)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher dans les transcripts, résumés, titres…  (⌘F)")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(360)
        self.search.textChanged.connect(self._on_search_text)
        self.search.returnPressed.connect(self._run_search)
        tb.addWidget(self.search)
        tb.addAction(self.a_settings)
        a_focus = QAction(self)
        a_focus.setShortcut(QKeySequence("Ctrl+F"))
        a_focus.triggered.connect(lambda: (self.search.setFocus(), self.search.selectAll()))
        self.addAction(a_focus)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._run_search)

    def _build_body(self) -> None:
        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)
        self.recbar = RecordingBar(self.bridge)
        v.addWidget(self.recbar)

        split = QSplitter(Qt.Orientation.Horizontal)
        v.addWidget(split, 1)

        # Filtres
        self.filters = QTreeWidget()
        self.filters.setHeaderHidden(True)
        self.filters.setMinimumWidth(170)
        self.filters.setMaximumWidth(260)
        self.filters.itemClicked.connect(self._on_filter)
        split.addWidget(self.filters)

        # Liste / résultats de recherche
        self.stack = QStackedWidget()
        self.list_model = RecordingListModel(self.repo)
        self.list_view = QListView()
        self.list_view.setModel(self.list_model)
        self.list_view.setItemDelegate(RecordingDelegate(self.list_view))
        self.list_view.setUniformItemSizes(True)
        self.list_view.setMouseTracking(True)
        self.list_view.setMinimumWidth(300)
        self.list_view.selectionModel().currentChanged.connect(self._on_select)
        self.stack.addWidget(self.list_view)

        self.results = QListWidget()
        self.results.setWordWrap(True)
        self.results.itemClicked.connect(self._on_result)
        self.stack.addWidget(self.results)

        self.empty = QLabel("Aucun enregistrement.\n\n⌘R pour enregistrer, ⌘I pour importer un fichier,\nou glisse un fichier audio ici.")
        self.empty.setObjectName("empty")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.empty)
        split.addWidget(self.stack)

        # Détail
        self.detail = RecordingDetail(self.service)
        self.detail.changed.connect(self._schedule_refresh)
        self.detail_stack = QStackedWidget()
        self.detail_stack.addWidget(self.detail)
        placeholder = QLabel("Sélectionne un enregistrement")
        placeholder.setObjectName("empty")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_stack.addWidget(placeholder)
        self.detail_stack.setCurrentIndex(1)
        split.addWidget(self.detail_stack)

        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 2)
        split.setStretchFactor(2, 4)
        split.setSizes([190, 360, 630])
        self.setCentralWidget(central)

        a_del = QAction(self)
        a_del.setShortcut(QKeySequence.StandardKey.Delete)
        a_del.triggered.connect(lambda: self.detail._delete() if self.detail.rec else None)
        self.list_view.addAction(a_del)

    # ─── Rafraîchissement ───────────────────────────────────────────

    def _schedule_refresh(self) -> None:
        self._refresh_timer.start()

    def refresh(self) -> None:
        current = self.detail.rec.id if self.detail.rec else None
        self._fill_filters()
        self.list_model.refresh()
        if self.list_model.rowCount() == 0 and not self.search.text().strip():
            self.stack.setCurrentWidget(self.empty)
        elif not self.search.text().strip():
            self.stack.setCurrentWidget(self.list_view)
        if current:
            row = self.list_model.row_of(current)
            if row >= 0:
                self.list_view.selectionModel().blockSignals(True)
                self.list_view.setCurrentIndex(self.list_model.index(row))
                self.list_view.selectionModel().blockSignals(False)
            self.detail.refresh_if(current)
        pending = self.repo.pending_job_count()
        cur = self.service.jobs.current
        if cur:
            rec = self.repo.get_recording(cur.recording_id)
            label = {"transcribe": "Transcription", "summarize": "Résumé"}.get(str(cur.kind), str(cur.kind))
            txt = f"{label} : {rec.display_title if rec else cur.recording_id[:8]}" + (f"  ·  {pending - 1} en file" if pending > 1 else "")
        elif pending:
            txt = f"{pending} job(s) en file"
        else:
            txt = ""
        self.status_job.setText(txt)

    def _fill_filters(self) -> None:
        f = self.list_model.filter
        self.filters.blockSignals(True)
        self.filters.clear()

        def add(parent, text, kind, value=None, selected=False):
            it = QTreeWidgetItem(parent, [text])
            it.setData(0, Qt.ItemDataRole.UserRole, (kind, value))
            if selected:
                self.filters.setCurrentItem(it)
            return it

        add(self.filters, "Tous", FILTER_ALL, selected=not (f.active_only or f.failed_only or f.project or f.tag))
        n_active = len([r for r in self.repo.list_recordings(limit=500) if r.status not in (RecordingStatus.DONE, RecordingStatus.FAILED)])
        n_failed = len(self.repo.list_recordings(limit=500, status=RecordingStatus.FAILED))
        add(self.filters, f"En cours ({n_active})" if n_active else "En cours", FILTER_ACTIVE, selected=f.active_only)
        add(self.filters, f"Échecs ({n_failed})" if n_failed else "Échecs", FILTER_FAILED, selected=f.failed_only)
        projects = self.repo.all_projects()
        if projects:
            p = QTreeWidgetItem(self.filters, ["Projets"])
            p.setFlags(p.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            for name in projects:
                add(p, name, FILTER_PROJECT, name, selected=f.project == name)
            p.setExpanded(True)
        tags = self.repo.all_tags()
        if tags:
            t = QTreeWidgetItem(self.filters, ["Tags"])
            t.setFlags(t.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            for name in tags:
                add(t, f"#{name}", FILTER_TAG, name, selected=f.tag == name)
            t.setExpanded(True)
        self.filters.blockSignals(False)

    def _on_filter(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, value = data
        f = self.list_model.filter
        f.active_only = kind == FILTER_ACTIVE
        f.failed_only = kind == FILTER_FAILED
        f.project = value if kind == FILTER_PROJECT else None
        f.tag = value if kind == FILTER_TAG else None
        self.search.clear()
        self.refresh()

    # ─── Sélection / détail ─────────────────────────────────────────

    def _on_select(self, current, _previous) -> None:
        rec: Recording | None = current.data(RecordingRole) if current.isValid() else None
        self.show_recording(rec.id if rec else None)

    def show_recording(self, recording_id: str | None, seek_to: float | None = None) -> None:
        if recording_id is None:
            self.detail_stack.setCurrentIndex(1)
            self.detail.load(None)
            return
        self.detail.load(recording_id, seek_to=seek_to)
        self.detail_stack.setCurrentIndex(0)

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
        hits = self.repo.search(q, limit=50)
        self.results.clear()
        if not hits:
            self.results.addItem(QListWidgetItem(f"Aucun résultat pour « {q} »"))
        for h in hits:
            self.results.addItem(_hit_item(h))
        self.stack.setCurrentWidget(self.results)

    def _on_result(self, item: QListWidgetItem) -> None:
        hit: SearchHit | None = item.data(Qt.ItemDataRole.UserRole)
        if hit:
            self.show_recording(hit.recording.id, seek_to=hit.start_s)

    # ─── Enregistrement ─────────────────────────────────────────────

    def _on_rec_started(self, rec: Recording) -> None:
        self.recbar.show()
        self.a_record.setEnabled(False)
        self.a_record_mic.setEnabled(False)
        self.a_stop.setEnabled(True)
        self.show_recording(rec.id)

    def _on_rec_stopped(self, rec: Recording) -> None:
        self.recbar.hide()
        self.a_record.setEnabled(True)
        self.a_record_mic.setEnabled(True)
        self.a_stop.setEnabled(False)
        self.show_recording(rec.id)

    def _on_job(self, job: Job) -> None:
        if job.status == JobStatus.FAILED and job.error:
            self.statusBar().showMessage(f"Échec {job.kind} : {job.error}", 10000)

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
            self.statusBar().showMessage("Réglages enregistrés — redémarre Noter pour les appliquer.", 6000)

    def closeEvent(self, e: QCloseEvent) -> None:  # noqa: N802
        # Fermer la fenêtre ne quitte pas : l'app vit dans la barre de menu.
        e.ignore()
        self.hide()


def _hit_item(h: SearchHit) -> QListWidgetItem:
    where = {"segment": "transcript", "summary": "résumé", "title": "titre"}[h.kind]
    ts = f" @ {format_timestamp(h.start_s)}" if h.start_s is not None else ""
    snippet = h.snippet.replace("[", "«").replace("]", "»")
    item = QListWidgetItem(f"{h.recording.display_title}  ·  {h.recording.started_at:%d/%m}  ·  {where}{ts}\n{snippet}")
    item.setData(Qt.ItemDataRole.UserRole, h)
    return item
