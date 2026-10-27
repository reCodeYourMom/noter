"""Tests de l'UI Qt en mode offscreen (sans écran, sans micro, sans backend audio)."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox  # noqa: E402

from noter.models import RecordingStatus  # noqa: E402
from noter.ui import theme  # noqa: E402
from noter.ui.bridge import ServiceBridge  # noqa: E402
from noter.ui.main_window import MainWindow  # noqa: E402
from noter.ui.settings_dialog import read_env, write_env  # noqa: E402
from noter.ui.widgets.rail import NavKey  # noqa: E402
from noter.ui.widgets.recording_list import HeaderRole, RecordingRole  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    theme.load_fonts()
    theme.apply(app, dark=False)
    yield app


@pytest.fixture
def window(qapp, service, wav):
    rec = service.import_file(wav, title="Call ACME", project="ACME", tags=["client"])
    service.jobs.run_pending()
    bridge = ServiceBridge(service)
    w = MainWindow(bridge)
    w.show()
    qapp.processEvents()
    yield w, rec
    w.detail.player.stop()
    w.deleteLater()
    qapp.processEvents()


def _process(qapp, ms: int = 50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _rows(model):
    return [model.index(i).data(RecordingRole) for i in range(model.rowCount()) if model.index(i).data(HeaderRole) is None]


def test_window_lists_and_shows_detail(qapp, window):
    w, rec = window
    recs = _rows(w.list_model)
    assert [r.id for r in recs] == [rec.id]
    assert w.list_model.index(0).data(HeaderRole) == "Aujourd’hui"
    assert w.stack.currentWidget() is w.list_view
    # Premier enregistrement sélectionné automatiquement → fiche affichée
    assert w.main_stack.currentWidget() is w.detail
    assert w.detail.rec.id == rec.id
    assert w.detail.title_edit.text() == "Call ACME"
    assert w.detail.transcript.model_.rowCount() == 1
    assert w.detail.timeline.peaks  # onde calculée à l'import
    checkboxes = w.detail.summary_box.findChildren(QCheckBox)
    assert len(checkboxes) == 1
    # Rail : projet et tag présents avec compteurs
    labels = [it.lab.text() for it in w.rail._items]
    assert "ACME" in labels and "#client" in labels and "Tous" in labels


def test_edit_metadata_from_detail(qapp, window, service):
    w, rec = window
    w.detail.title_edit.setText("Renommé")
    w.detail.title_edit.editingFinished.emit()
    w.detail.tags.setText("a, b")
    w.detail.tags.editingFinished.emit()
    _process(qapp, 200)
    got = service.repo.get_recording(rec.id)
    assert got.title == "Renommé" and got.tags == ["a", "b"]
    assert (got.dir_path / "summary.md").read_text().startswith("# Renommé")


def test_action_checkbox_persists(qapp, window, service):
    w, rec = window
    cb = w.detail.summary_box.findChildren(QCheckBox)[0]
    cb.setChecked(True)
    assert service.repo.get_summary(rec.id).actions[0].done is True
    assert "- [x]" in (rec.dir_path / "summary.md").read_text()


def test_search_shows_results_and_opens_recording(qapp, window):
    w, rec = window
    w.search.setText("devis")
    w._run_search()
    assert w.stack.currentWidget() is w.results
    assert w.results.count() >= 1
    w._on_result(w.results.item(0))
    assert w.detail.rec.id == rec.id and w.main_stack.currentWidget() is w.detail
    w.search.clear()
    qapp.processEvents()
    assert w.stack.currentWidget() is w.list_view


def test_nav_filters(qapp, window, service):
    w, rec = window
    service.repo.set_status(rec.id, RecordingStatus.FAILED)
    w.refresh()
    w._on_nav(NavKey("failed"))
    assert len(_rows(w.list_model)) == 1 and w.list_model.filter.kind == "failed"
    w._on_nav(NavKey("active"))
    assert len(_rows(w.list_model)) == 0 and w.stack.currentWidget() is w.list_empty
    w._on_nav(NavKey("project", "ACME"))
    assert len(_rows(w.list_model)) == 1


def test_job_signal_refreshes_list(qapp, window, service, wav):
    w, _ = window
    from tests.conftest import make_wav

    second = make_wav(wav.parent / "second.wav", seconds=1.0)
    w.bridge.import_files([str(second)])
    _process(qapp, 300)
    assert len(_rows(w.list_model)) == 2
    service.jobs.run_pending()
    _process(qapp, 300)
    assert all(r.status == RecordingStatus.DONE for r in service.repo.list_recordings())


def test_empty_state_when_no_recordings(qapp, service):
    bridge = ServiceBridge(service)
    w = MainWindow(bridge)
    w.show()
    qapp.processEvents()
    assert w.main_stack.currentWidget() is w.empty
    w.deleteLater()


def test_close_hides_instead_of_quitting(qapp, window):
    w, _ = window
    w.close()
    assert not w.isVisible()


def test_dark_theme_applies(qapp):
    t = theme.apply(qapp, dark=True)
    assert t.is_dark and "IBM Plex" in qapp.styleSheet()
    theme.apply(qapp, dark=False)


def test_env_roundtrip(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# commentaire\nANTHROPIC_API_KEY=sk-old\n# NOTER_WHISPER_MODEL=large-v3\nAUTRE=1\n")
    write_env(p, {"ANTHROPIC_API_KEY": "sk-new", "NOTER_WHISPER_MODEL": "small", "NOTER_CLAUDE_EFFORT": "high"})
    env = read_env(p)
    assert env["ANTHROPIC_API_KEY"] == "sk-new" and env["NOTER_WHISPER_MODEL"] == "small"
    assert env["NOTER_CLAUDE_EFFORT"] == "high" and env["AUTRE"] == "1"
    assert p.read_text().startswith("# commentaire\n")
    write_env(p, {"NOTER_WHISPER_LANGUAGE": ""})
    assert "NOTER_WHISPER_LANGUAGE" not in read_env(p) and "# NOTER_WHISPER_LANGUAGE=" in p.read_text()


def test_single_instance_lock(qapp):
    from noter.ui.single_instance import SingleInstance

    first = SingleInstance("noter-test-lock")
    assert first.acquire()
    received = []
    first.message_received.connect(received.append)
    second = SingleInstance("noter-test-lock")
    assert not second.acquire()
    assert second.notify_existing("show")
    _process(qapp, 200)
    assert received == ["show"]


def test_console_warns_on_digital_silence(qapp):
    from datetime import datetime
    from pathlib import Path

    from noter.models import Recording, Source
    from noter.ui.widgets.console import RecordingConsole

    c = RecordingConsole()
    rec = Recording(id="x", source=Source.MAC_MIC, status=RecordingStatus.RECORDING,
                    started_at=datetime.now(), audio_path=Path("/x"), dir_path=Path("/x"))
    c.begin(rec, "Micro seul", with_system=False)
    c.tick(1.0, {"MIC": 0.0})
    assert c.silence.isHidden()  # trop tôt pour conclure
    c.tick(3.5, {"MIC": 0.0})
    assert not c.silence.isHidden()  # silence absolu → avertissement
    c.tick(4.0, {"MIC": 0.002})
    assert c.silence.isHidden()  # du son arrive → l'avertissement disparaît
    c.begin(rec, "Micro seul", with_system=False)
    c.tick(3.5, {"MIC": 0.0})
    assert not c.silence.isHidden()


# ─── Tâches (boards) ────────────────────────────────────────────────


def _drop_event(col, card_id: int, y_in_host: int, mime_format: str = "application/x-noter-card"):
    """Un QDropEvent comme en produirait Qt : la carte lâchée à la hauteur `y_in_host` de la liste."""
    from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
    from PySide6.QtGui import QDropEvent

    mime = QMimeData()
    mime.setData(mime_format, str(card_id).encode())
    pos = col.host.mapTo(col, QPoint(20, y_in_host))
    event = QDropEvent(QPointF(pos), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    event.keepalive = mime  # l'événement ne possède pas le QMimeData (c'est Qt, pendant un vrai glisser, qui le garde)
    return event


@pytest.fixture
def board_window(qapp, window, service):
    from noter.ui.widgets.rail import NavKey

    w, rec = window
    w.create_board("Sprint")
    board = service.repo.list_boards()[0]
    lists = service.repo.get_lists(board.id)
    cards = [service.repo.create_card(lists[0].id, t) for t in ("alpha", "bravo", "charlie")]
    w.board_view.refresh()
    _process(qapp, 50)
    assert w.rail.current == NavKey("board", str(board.id))
    return w, board, lists, cards


def test_board_in_rail_and_view(qapp, board_window, service):
    w, board, lists, cards = board_window
    assert w.workspace.currentWidget() is w.board_view
    assert w.board_view.title_edit.text() == "Sprint"
    labels = [it.lab.text() for it in w.rail._items]
    assert "Sprint" in labels and "Tous" in labels
    assert [c.list.name for c in w.board_view.strip.columns] == ["À faire", "En cours", "Terminé"]
    assert [t.card.title for t in w.board_view.strip.columns[0].tiles()] == ["alpha", "bravo", "charlie"]
    # De retour dans la bibliothèque : la liste d'enregistrements revient
    from noter.ui.widgets.rail import NavKey

    w.rail.select(NavKey("all"))
    assert w.workspace.currentWidget() is not w.board_view


def test_add_card_with_composer_keeps_it_open(qapp, board_window, service):
    w, board, lists, cards = board_window
    col = w.board_view.strip.columns[1]
    col.open_composer()
    assert col.composing
    col.adder.field.submitted.emit("Écrire les tests")
    _process(qapp, 50)
    assert [c.title for c in service.repo.cards_in_list(lists[1].id)] == ["Écrire les tests"]
    assert w.board_view.strip.columns[1] is col and col.composing  # même widget, composeur toujours ouvert
    assert col.count.text() == "1"
    col.adder.close_form()
    assert not col.composing


def test_drop_card_between_and_across_lists(qapp, board_window, service):
    w, board, lists, cards = board_window
    todo, doing = w.board_view.strip.columns[0], w.board_view.strip.columns[1]
    alpha, bravo, charlie = cards

    def titles(list_id):
        return [c.title for c in service.repo.cards_in_list(list_id)]

    def settle():
        """Ce que fait l'app après chaque glisser : la source demande le rafraîchissement du board."""
        w.board_view._after_drag()
        _process(qapp, 50)

    # « charlie » lâché tout en haut de sa propre liste
    todo.dropEvent(_drop_event(todo, charlie.id, 0))
    settle()
    assert titles(lists[0].id) == ["charlie", "alpha", "bravo"]

    # « charlie » relâché juste sous « alpha » : il passe entre alpha et bravo
    alpha_y = next(t for t in todo.tiles() if t.card.id == alpha.id).geometry().center().y()
    todo.dropEvent(_drop_event(todo, charlie.id, alpha_y + 2))
    settle()
    assert titles(lists[0].id) == ["alpha", "charlie", "bravo"]

    # « alpha » dans la liste vide « En cours »
    doing.dropEvent(_drop_event(doing, alpha.id, 5))
    settle()
    assert titles(lists[1].id) == ["alpha"] and titles(lists[0].id) == ["charlie", "bravo"]
    assert [t.card.title for t in doing.tiles()] == ["alpha"] and doing.count.text() == "1"

    # « bravo » lâché loin sous la dernière carte de « En cours » : il se range en fin de liste
    doing.dropEvent(_drop_event(doing, bravo.id, 900))
    settle()
    assert titles(lists[1].id) == ["alpha", "bravo"]
    assert [t.card.title for t in doing.tiles()] == ["alpha", "bravo"] and todo.count.text() == "1"

    # Un lâcher qui n'est pas une carte ne touche à rien
    before = service.repo.cards_for_board(board.id)
    doing.dropEvent(_drop_event(doing, 1, 0, mime_format="text/plain"))
    assert service.repo.cards_for_board(board.id) == before


def test_drop_position_is_computed_from_the_pointer(qapp, board_window, service):
    from PySide6.QtCore import QPoint

    w, board, lists, cards = board_window
    col = w.board_view.strip.columns[0]
    alpha, bravo, charlie = cards
    ys = [t.geometry().center().y() for t in col.tiles()]

    def slot(y: int, dragged: int) -> int:
        return col._drop_slot(col.host.mapTo(col, QPoint(0, y)), dragged)[1]

    assert slot(0, alpha.id) == 0 and slot(0, charlie.id) == 0  # au-dessus de tout
    assert slot(ys[0] + 2, bravo.id) == 1  # sous « alpha », en glissant « bravo »
    assert slot(ys[1] + 2, alpha.id) == 1  # sous « bravo » : « alpha » glissée ne compte pas
    assert slot(ys[2] + 100, alpha.id) == 2  # sous tout, il reste « bravo » et « charlie » devant
    assert slot(ys[2] + 100, charlie.id) == 2


def test_card_dialog_edits_are_saved(qapp, board_window, service, monkeypatch):
    from datetime import date

    from PySide6.QtCore import QDate
    from PySide6.QtWidgets import QCheckBox, QMessageBox

    from noter.ui.card_dialog import CardDialog

    w, board, lists, cards = board_window
    card = cards[0]
    dlg = CardDialog(service.repo, card.id)
    changes = []
    dlg.changed.connect(lambda: changes.append(1))

    dlg.title_edit.setText("Alpha v2")
    dlg.title_edit.editingFinished.emit()
    dlg.label_buttons["red"].setChecked(True)
    dlg.label_buttons["blue"].setChecked(True)
    dlg.has_due.setChecked(True)
    dlg.due_edit.setDate(QDate(2026, 6, 15))
    dlg.due_done.setChecked(True)
    dlg.desc.setPlainText("Une description")
    dlg.new_item.setText("Premier pas")
    dlg.new_item.returnPressed.emit()
    dlg.new_item.setText("Deuxième pas")
    dlg.new_item.returnPressed.emit()
    dlg.items_host.findChildren(QCheckBox)[0].setChecked(True)
    dlg.list_combo.setCurrentIndex(2)
    dlg.list_combo.activated.emit(2)
    dlg.accept()  # flush de la description (debounce)

    got = service.repo.get_card(card.id)
    assert got.title == "Alpha v2" and got.labels == ["red", "blue"]
    assert got.due == date(2026, 6, 15) and got.done
    assert got.description == "Une description"
    assert [(i.text, i.done) for i in got.checklist] == [("Premier pas", True), ("Deuxième pas", False)]
    assert got.list_id == lists[2].id and changes
    assert dlg.progress_text.text() == "1/2" and dlg.progress.value() == 50

    # Retirer l'échéance remet « terminée » à zéro ; un titre vidé est rétabli
    dlg2 = CardDialog(service.repo, card.id)
    dlg2.has_due.setChecked(False)
    dlg2.title_edit.setText("   ")
    dlg2.title_edit.editingFinished.emit()
    assert dlg2.title_edit.text() == "Alpha v2"
    got = service.repo.get_card(card.id)
    assert got.due is None and not got.done

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    dlg2._delete()
    assert service.repo.get_card(card.id) is None


def test_filter_hides_non_matching_cards(qapp, board_window, service):
    w, board, lists, cards = board_window
    service.repo.update_card(cards[1].id, labels=["purple"])
    w.board_view.refresh()
    col = w.board_view.strip.columns[0]
    w.board_view.filter.setText("char")
    assert [not t.isHidden() for t in col.tiles()] == [False, False, True]
    w.board_view.filter.setText("violet")  # le filtre comprend aussi le nom des étiquettes
    assert [not t.isHidden() for t in col.tiles()] == [False, True, False]
    w.board_view.filter.setText("")
    assert all(not t.isHidden() for t in col.tiles())


def test_list_and_board_management(qapp, board_window, service, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    w, board, lists, cards = board_window
    bv = w.board_view
    bv._add_list("Backlog")
    assert [c.list.name for c in bv.strip.columns] == ["À faire", "En cours", "Terminé", "Backlog"]

    bv._move_list(lists[0].id, +1)
    assert [c.list.name for c in bv.strip.columns][:2] == ["En cours", "À faire"]
    bv._move_list(lists[0].id, +10)  # borné
    assert [c.list.name for c in bv.strip.columns][-1] == "À faire"

    # Renommer une liste depuis son titre
    col = next(c for c in bv.strip.columns if c.list.id == lists[0].id)
    col._begin_rename()
    col.title_edit.setText("Backlog produit")
    col._end_rename()
    assert service.repo.get_list(lists[0].id).name == "Backlog produit"

    # Une liste en glissant : « À faire » revient en tête
    bv.strip.list_dropped.emit(lists[0].id, 0)
    bv._after_drag()
    assert bv.strip.columns[0].list.id == lists[0].id

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    bv._delete_list(lists[0].id)  # emporte ses 3 cartes
    assert service.repo.get_list(lists[0].id) is None and all(service.repo.get_card(c.id) is None for c in cards)
    assert len(bv.strip.columns) == 3

    # Renommer puis supprimer le board
    bv.title_edit.setText("Sprint 13")
    bv.title_edit.editingFinished.emit()
    assert service.repo.get_board(board.id).name == "Sprint 13"
    assert "Sprint 13" in [it.lab.text() for it in w.rail._items]
    bv._delete_board()
    _process(qapp, 50)
    assert service.repo.list_boards() == []
    assert w.rail.current.kind == "all" and w.workspace.currentWidget() is not bv


def test_action_to_board_and_back(qapp, window, service, monkeypatch):
    """Une action du résumé devient une carte ; le bouton devient « déjà dans un board » et ouvre la carte."""
    from PySide6.QtWidgets import QToolButton

    from noter.ui.card_dialog import CardDialog

    opened = []
    monkeypatch.setattr(CardDialog, "exec", lambda self: opened.append(self.card_id) or 0)  # pas de boucle modale en test
    w, rec = window
    assert service.repo.list_boards() == []
    w.detail._create_card(0, None)  # un seul board possible → créé à la volée
    _process(qapp, 200)
    board = service.repo.list_boards()[0]
    cards = service.repo.cards_for_recording(rec.id)
    assert len(cards) == 1 and cards[0].title == "Envoyer le devis"
    assert ("Mes tâches", 1) == (board.name, service.repo.card_counts()[board.id])
    assert "Mes tâches" in [it.lab.text() for it in w.rail._items]

    requested = []
    w.detail.card_requested.connect(requested.append)
    buttons = [b for b in w.detail.summary_box.findChildren(QToolButton) if b.toolTip().startswith("Déjà dans un board")]
    assert len(buttons) == 1
    buttons[0].click()
    assert requested == [cards[0].id]
    assert opened == [cards[0].id]  # la carte s'ouvre, sur son board
    assert w.workspace.currentWidget() is w.board_view and w.board_view.board_id == board.id

    # Depuis la carte, on retrouve l'enregistrement
    w.open_recording(rec.id)
    assert w.workspace.currentIndex() == 0 and w.detail.rec.id == rec.id


def test_tile_click_opens_and_drag_starts_a_card_drag(qapp, board_window, monkeypatch):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from noter.ui.card_dialog import CardDialog
    from noter.ui.widgets import board as board_mod

    monkeypatch.setattr(CardDialog, "exec", lambda self: 0)  # le clic ouvre la carte : pas de boucle modale en test
    w, board, lists, cards = board_window
    tile = w.board_view.strip.columns[0].tiles()[0]
    opened = []
    tile.clicked.connect(opened.append)
    QTest.mouseClick(tile, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    assert opened == [cards[0].id]
    tile = w.board_view.strip.columns[0].tiles()[0]  # le board s'est rafraîchi à la fermeture de la carte
    tile.clicked.connect(opened.append)

    drags = []

    class FakeDrag:
        def __init__(self, source):
            self.source = source

        def setMimeData(self, mime):
            self.mime = mime

        def setPixmap(self, _pm):
            pass

        def setHotSpot(self, _p):
            pass

        def exec(self, _action):
            drags.append((bytes(self.mime.data(board_mod.CARD_MIME)).decode(), tile.isHidden()))
            return Qt.DropAction.IgnoreAction  # glisser annulé

    monkeypatch.setattr(board_mod, "QDrag", FakeDrag)
    events = []
    tile.drag_started.connect(lambda: events.append("start"))
    tile.drag_finished.connect(lambda: events.append("end"))
    QTest.mousePress(tile, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    QTest.mouseMove(tile, QPoint(120, 90))
    assert drags == [(str(cards[0].id), True)]  # la carte est masquée pendant le glisser, l'id voyage dans le mime
    assert events == ["start", "end"]
    QTest.mouseRelease(tile, Qt.MouseButton.LeftButton, pos=QPoint(120, 90))
    assert opened == [cards[0].id]  # un glisser n'est pas un clic

    # Pendant un glisser, le board ne se reconstruit pas (la source est encore sur la pile Qt) ; ensuite si
    w.board_view._drag_started()
    service_card = w.board_view.repo.create_card(lists[2].id, "pendant")
    w.board_view.refresh()
    assert "pendant" not in [t.card.title for c in w.board_view.strip.columns for t in c.tiles()]
    w.board_view._after_drag()
    assert "pendant" in [t.card.title for t in w.board_view.strip.columns[2].tiles()] and service_card


def test_list_drag_and_drop_reorders(qapp, board_window, service, monkeypatch):
    from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
    from PySide6.QtGui import QDropEvent

    from noter.ui.widgets import board as board_mod

    w, board, lists, cards = board_window
    strip = w.board_view.strip
    first, second, third = strip.columns
    got = []
    strip.list_dropped.connect(lambda lid, idx: got.append((lid, idx)))

    def list_drop(target, x_in_strip: int, list_id: int):
        mime = QMimeData()
        mime.setData(board_mod.LIST_MIME, str(list_id).encode())
        pos = target.mapFrom(strip, QPoint(x_in_strip, 30))
        ev = QDropEvent(QPointF(pos), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        ev.keepalive = mime
        target.dropEvent(ev)

    def order():
        return [lst.name for lst in service.repo.get_lists(board.id)]

    # « À faire » lâchée à droite de « En cours » (déposée sur la colonne « Terminé », qui relaie au conteneur)
    list_drop(third, third.geometry().left() + 20, first.list.id)
    assert got == [(first.list.id, 1)]
    assert order() == ["En cours", "À faire", "Terminé"]  # le dépôt est écrit en base
    # « Terminé » lâchée tout à gauche, sur le conteneur lui-même
    list_drop(strip, 0, third.list.id)
    assert got[-1] == (third.list.id, 0)
    assert order() == ["Terminé", "En cours", "À faire"]
    # « En cours » lâchée tout à droite, après la dernière colonne
    list_drop(strip, strip.width() - 5, second.list.id)
    assert got[-1] == (second.list.id, 2)
    assert order() == ["Terminé", "À faire", "En cours"]


def test_autoscroll_while_dragging(qapp, board_window, service):
    from PySide6.QtCore import QPoint

    w, board, lists, cards = board_window
    bv = w.board_view
    for i in range(6):  # assez de listes pour dépasser la largeur de la fenêtre
        bv._add_list(f"Liste {i}")
    _process(qapp, 50)
    bar = bv.scroll.horizontalScrollBar()
    assert bar.maximum() > 0 and bar.value() == bar.maximum()  # l'ajout d'une liste défile jusqu'à elle
    bar.setValue(0)
    view = bv.scroll.viewport()

    bv.autoscroll_step(view.mapToGlobal(QPoint(view.width() // 2, 200)))  # au centre : rien
    assert bar.value() == 0
    bv.autoscroll_step(view.mapToGlobal(QPoint(view.width() - 4, 200)))  # bord droit : avance
    assert bar.value() > 0
    far = bar.value()
    bv.autoscroll_step(view.mapToGlobal(QPoint(3, 200)))  # bord gauche : recule
    assert bar.value() < far

    # Le défilement ne tourne que pendant un glisser
    assert not bv._autoscroll.isActive()
    bv._drag_started()
    assert bv._autoscroll.isActive()
    bv._after_drag()
    assert not bv._autoscroll.isActive()


def test_board_mode_shortcuts_are_safe(qapp, board_window, service):
    w, board, lists, cards = board_window
    rec = w.detail.rec
    assert rec is not None and w.in_board
    w._delete_current()  # ⌘⌫ dans un board ne supprime jamais l'enregistrement caché derrière
    assert service.repo.get_recording(rec.id) is not None
    w._focus_search()
    assert w.board_view.filter.hasFocus() or w.board_view.filter.isEnabled()

    w._on_rec_started(rec)  # un enregistrement qui démarre ramène à la bibliothèque (console visible)
    assert not w.in_board and w.main_stack.currentWidget() is w.console


def test_cards_and_list_titles_are_hit_by_the_mouse(qapp, board_window):
    """Régression : une carte rendue transparente à la souris n'était ni cliquable ni déplaçable.

    Les tests qui envoient les événements directement au widget ne le voient pas ; il faut passer par le
    « hit-testing » de Qt, comme le fait un vrai clic.
    """
    from noter.ui.widgets.board import CardTile

    w, board, lists, cards = board_window
    col = w.board_view.strip.columns[0]
    for tile in col.tiles():
        hit = qapp.widgetAt(tile.mapToGlobal(tile.rect().center()))
        assert hit is tile and isinstance(hit, CardTile)
    title = col.title
    assert qapp.widgetAt(title.mapToGlobal(title.rect().center())) is title
