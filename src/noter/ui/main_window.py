"""Fenêtre principale : rail · liste · fiche / console / état vide."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from noter.models import Job, JobStatus, Recording, RecordingStatus, format_date_fr, format_timestamp
from noter.service import AUDIO_EXTENSIONS
from noter.storage.repo import SearchHit
from noter.ui import icons, theme
from noter.ui.board_view import BoardView
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
        self.rail.board_add_requested.connect(self._new_board)
        self.rail.record_requested.connect(lambda: self.bridge.start_recording(True))
        self.rail.import_requested.connect(self._import_dialog)
        self.btn_record = self.rail.record_btn
        root.addWidget(self.rail)

        # Deux pages : bibliothèque d'enregistrements (liste + fiche) ou board de tâches
        self.workspace = QStackedWidget()
        root.addWidget(self.workspace, 1)
        library = QWidget()
        lib = QHBoxLayout(library)
        lib.setContentsMargins(0, 0, 0, 0)
        lib.setSpacing(0)
        self.workspace.addWidget(library)
        self.board_view = BoardView(self.service)
        self.board_view.changed.connect(self._schedule_refresh)
        self.board_view.board_changed.connect(self._on_boards_changed)
        self.board_view.recording_requested.connect(self.open_recording)
        self.workspace.addWidget(self.board_view)

        # Colonne liste
        listcol = QWidget()
        listcol.setObjectName("listcol")
        listcol.setFixedWidth(340)
        ll = QVBoxLayout(listcol)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        # En-tête : nom de la vue courante, compteur, recherche
        top = QVBoxLayout()
        top.setContentsMargins(18, 34, 18, 12)
        top.setSpacing(2)
        self.page_title = QLabel("Tous les calls")
        self.page_title.setObjectName("pageTitle")
        self.page_sub = QLabel("")
        self.page_sub.setObjectName("meta")
        top.addWidget(self.page_title)
        top.addWidget(self.page_sub)
        top.addSpacing(12)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher dans les calls    ⌘F")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.icon("search", t.ink_3, 14), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._on_search_text)
        self.search.returnPressed.connect(self._run_search)
        top.addWidget(self.search)
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
        lib.addWidget(listcol)

        # Zone principale
        self.main_stack = QStackedWidget()
        self.detail = RecordingDetail(self.service)
        self.detail.changed.connect(self._schedule_refresh)
        self.detail.card_requested.connect(self.open_card)
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
        lib.addWidget(self.main_stack, 1)
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
        act("Ctrl+F", self._focus_search)
        act("Ctrl+Backspace", self._delete_current)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._run_search)

    @property
    def in_board(self) -> bool:
        return self.workspace.currentWidget() is self.board_view

    def _focus_search(self) -> None:
        field = self.board_view.filter if self.in_board else self.search
        field.setFocus()
        field.selectAll()

    def _delete_current(self) -> None:
        # Jamais depuis un board : la fiche d'enregistrement est alors cachée derrière.
        if not self.in_board and self.detail.rec and self.main_stack.currentWidget() is self.detail:
            self.detail._delete()

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
        card_counts = self.repo.card_counts()
        boards = [(b.id, b.name, card_counts.get(b.id, 0)) for b in self.repo.list_boards()]
        self.rail.populate(counts, sorted(proj.items()), sorted(tags.items()), boards)

        self.list_model.refresh()
        self._update_page_title()
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

    def _update_page_title(self) -> None:
        f = self.list_model.filter
        title = {"all": "Tous les calls", "active": "En cours", "failed": "Échecs"}.get(f.kind)
        if title is None:
            title = f"#{f.value}" if f.kind == "tag" else (f.value or "")
        self.page_title.setText(title)
        n = self.list_model.recording_count()
        self.page_sub.setText("Aucun enregistrement" if n == 0 else f"{n} enregistrement{'s' if n > 1 else ''}")

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
        if key.kind == "board":
            self.board_view.set_board(int(key.value))  # type: ignore[arg-type]
            self.workspace.setCurrentWidget(self.board_view)
            return
        self.workspace.setCurrentIndex(0)
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

    # ─── Tâches ─────────────────────────────────────────────────────

    def _new_board(self) -> None:
        name, ok = QInputDialog.getText(self, "Nouveau board", "Nom du board", text="")
        if ok and name.strip():
            self.create_board(name)

    def create_board(self, name: str) -> None:
        board = self.service.create_board(name)
        self.refresh()
        self.rail.select(NavKey("board", str(board.id)))

    def _on_boards_changed(self) -> None:
        """Un board a été renommé ou supprimé : on remet le rail d'aplomb."""
        self.refresh()
        key = self.rail.current
        if key.kind == "board" and self.repo.get_board(int(key.value)) is None:  # type: ignore[arg-type]
            self.rail.select(NavKey("all"))

    def open_card(self, card_id: int) -> None:
        board = self.repo.board_of_card(card_id)
        if board is None:
            return
        self.rail.select(NavKey("board", str(board.id)))
        self.board_view.open_card(card_id)

    def open_recording(self, recording_id: str) -> None:
        self.rail.select(NavKey("all"))
        row = self.list_model.row_of(recording_id)
        if row >= 0:
            self.list_view.selectionModel().blockSignals(True)
            self.list_view.setCurrentIndex(self.list_model.index(row))
            self.list_view.selectionModel().blockSignals(False)
        self.show_recording(recording_id)

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
        if self.in_board:  # la console d'enregistrement vit dans la bibliothèque
            self.rail.select(NavKey("all"))
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


def _hit_item(h: SearchHit) -> QListWidgetItem:
    where = {"segment": "transcript", "summary": "résumé", "title": "titre"}[h.kind]
    ts = f" @ {format_timestamp(h.start_s)}" if h.start_s is not None else ""
    snippet = h.snippet.replace("[", "«").replace("]", "»")
    item = QListWidgetItem(f"{h.recording.display_title}  ·  {format_date_fr(h.recording.started_at, with_time=False)}  ·  {where}{ts}\n{snippet}")
    item.setData(Qt.ItemDataRole.UserRole, h)
    return item
