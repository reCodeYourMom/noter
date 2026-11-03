"""Aucune action ne doit créer de fenêtre de premier niveau inattendue.

Sur macOS, une fenêtre qui s'affiche alors que Noter est en plein écran sort l'app de son Space :
l'écran devient noir et l'utilisateur se retrouve sur le bureau, l'action ayant pourtant eu lieu.
Au niveau de Qt, la faute est toujours la même : un widget encore sans parent quand on l'affiche.
"""
from __future__ import annotations

import os
import traceback

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QObject, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from noter.ui.card_dialog import CardDialog  # noqa: E402
from noter.ui.widgets.rail import NavKey  # noqa: E402
from test_ui import board_window, qapp, window  # noqa: E402, F401  (fixtures)

# Types de fenêtres légitimes : un dialogue, un menu, une infobulle s'affichent exprès.
ALLOWED_TYPES = (
    Qt.WindowType.Dialog,
    Qt.WindowType.Popup,
    Qt.WindowType.ToolTip,
    Qt.WindowType.SplashScreen,
    Qt.WindowType.Sheet,
    Qt.WindowType.Drawer,
)


class WindowSpy(QObject):
    """Note toute fenêtre de premier niveau affichée, avec la ligne de Noter qui l'a provoquée."""

    def __init__(self, app: QApplication):
        super().__init__(app)
        self.seen: list[str] = []
        self._app = app

    def __enter__(self) -> WindowSpy:
        self._app.installEventFilter(self)
        return self

    def __exit__(self, *_exc) -> None:
        self._app.removeEventFilter(self)

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        if ev.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            kind = obj.windowFlags() & Qt.WindowType.WindowType_Mask
            if kind not in ALLOWED_TYPES and obj.windowTitle() != "Noter":
                where = " ← ".join(
                    f"{os.path.basename(f.filename)}:{f.lineno} {f.name}"
                    for f in reversed(traceback.extract_stack()[:-1][-8:])
                    if "/noter/" in f.filename
                )
                self.seen.append(f"{type(obj).__name__}(objectName={obj.objectName()!r}) depuis {where}")
        return False


@pytest.fixture
def spy(qapp):  # noqa: F811
    with WindowSpy(qapp) as s:
        yield s


def test_opening_a_board_creates_no_window(qapp, board_window, spy):  # noqa: F811
    w, board, lists, cards = board_window
    w._on_nav(NavKey("library", "all"))
    qapp.processEvents()
    w._on_nav(NavKey("board", str(board.id)))
    qapp.processEvents()
    assert spy.seen == []


def test_card_actions_create_no_window(qapp, board_window, service, spy):  # noqa: F811
    w, board, lists, cards = board_window
    # Une carte terminée, une carte avec échéance : leurs badges sont reconstruits à chaque rafraîchissement.
    service.repo.update_card(cards[0].id, done=True)
    service.repo.update_card(cards[1].id, due="2030-01-01", labels=["green"])
    w.board_view.refresh()
    qapp.processEvents()

    col = w.board_view.strip.columns[0]
    tile = next(t for t in col.tiles() if t.card.id == cards[2].id)
    tile.done_toggle.setChecked(True)  # cocher « Terminer » sur une carte
    qapp.processEvents()
    w.board_view.refresh()
    qapp.processEvents()
    assert spy.seen == []


def test_card_dialog_edits_create_no_window(qapp, board_window, service, spy):  # noqa: F811
    w, board, lists, cards = board_window
    dlg = CardDialog(service.repo, cards[0].id, w)
    dlg.changed.connect(w.board_view._on_changed)
    dlg.show()
    qapp.processEvents()
    spy.seen.clear()  # le dialogue lui-même est une fenêtre légitime

    dlg.label_buttons["green"].setChecked(True)  # étiquette
    qapp.processEvents()
    dlg.has_due.setChecked(True)                 # date limite
    qapp.processEvents()
    dlg.done_toggle.setChecked(True)             # terminée
    qapp.processEvents()
    dlg.new_item.setText("un élément")           # checklist
    dlg.new_item.returnPressed.emit()
    qapp.processEvents()

    dlg.close()
    dlg.deleteLater()
    qapp.processEvents()
    assert spy.seen == []


def test_whole_app_sweep_creates_no_window(qapp, board_window, service, spy):  # noqa: F811
    """Balayage large : navigation, liste, fiche d'un call, composeur, renommage, filtre."""
    w, board, lists, cards = board_window
    service.repo.update_card(cards[0].id, done=True, due="2030-01-01", labels=["green", "red"])

    for key in (NavKey("board", str(board.id)), NavKey("library", "all"), NavKey("library", "running"),
                NavKey("library", "failed"), NavKey("board", str(board.id))):
        w._on_nav(key)
        qapp.processEvents()

    col = w.board_view.strip.columns[0]
    col.open_composer()                      # composeur de carte
    qapp.processEvents()
    col.adder.field.setPlainText("delta")
    col.adder._confirm()
    qapp.processEvents()
    col._begin_rename()                      # renommer la liste
    col.title_edit.setText("À faire (bis)")
    col._end_rename()
    qapp.processEvents()
    w.board_view.filter.setText("delta")     # filtrer
    qapp.processEvents()
    w.board_view.filter.clear()
    qapp.processEvents()
    w.board_view._sort_list(lists[0].id)     # trier par échéance
    qapp.processEvents()

    w._on_nav(NavKey("library", "all"))      # fiche d'un enregistrement
    qapp.processEvents()
    w.list_view.setCurrentIndex(w.list_model.index(w.list_model.first_recording_row()))
    qapp.processEvents()
    w.refresh()
    qapp.processEvents()

    assert spy.seen == []
