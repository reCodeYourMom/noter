"""Tests de l'UI Qt en mode offscreen (sans écran, sans micro, sans backend audio)."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox  # noqa: E402

from noter.models import RecordingStatus  # noqa: E402
from noter.ui.bridge import ServiceBridge  # noqa: E402
from noter.ui.main_window import MainWindow  # noqa: E402
from noter.ui.models import RecordingRole  # noqa: E402
from noter.ui.settings_dialog import read_env, write_env  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
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
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_window_lists_and_shows_detail(qapp, window):
    w, rec = window
    assert w.list_model.rowCount() == 1
    assert w.list_model.index(0).data(RecordingRole).id == rec.id
    assert w.stack.currentWidget() is w.list_view

    w.list_view.setCurrentIndex(w.list_model.index(0))
    qapp.processEvents()
    assert w.detail_stack.currentIndex() == 0
    assert w.detail.rec.id == rec.id
    assert w.detail.title_edit.text() == "Call ACME"
    assert "Prêt" in w.detail.status_lab.text()
    assert w.detail.seg_list.count() == 1
    checkboxes = w.detail.summary_box.findChildren(QCheckBox)
    assert len(checkboxes) == 1 and "Envoyer le devis" in checkboxes[0].text()

    # Filtres : projet et tag présents
    labels = []
    it = w.filters.topLevelItem(0)
    for i in range(w.filters.topLevelItemCount()):
        top = w.filters.topLevelItem(i)
        labels.append(top.text(0))
        labels += [top.child(j).text(0) for j in range(top.childCount())]
    assert "ACME" in labels and "#client" in labels
    assert it is not None


def test_edit_metadata_from_detail(qapp, window, service):
    w, rec = window
    w.list_view.setCurrentIndex(w.list_model.index(0))
    qapp.processEvents()
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
    w.list_view.setCurrentIndex(w.list_model.index(0))
    qapp.processEvents()
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
    assert w.detail.rec.id == rec.id
    w.search.clear()
    qapp.processEvents()
    assert w.stack.currentWidget() is w.list_view


def test_filters_failed_only(qapp, window, service):
    w, rec = window
    service.repo.set_status(rec.id, RecordingStatus.FAILED)
    w.refresh()
    # cliquer sur "Échecs"
    item = w.filters.topLevelItem(2)
    assert item.text(0).startswith("Échecs (1)")
    w._on_filter(item, 0)
    assert w.list_model.rowCount() == 1 and w.list_model.filter.failed_only
    w._on_filter(w.filters.topLevelItem(1), 0)  # En cours → vide
    assert w.list_model.rowCount() == 0


def test_job_signal_refreshes_list(qapp, window, service, wav):
    w, _ = window
    from tests.conftest import make_wav

    second = make_wav(wav.parent / "second.wav", seconds=1.0)
    w.bridge.import_files([str(second)])
    _process(qapp, 300)
    assert w.list_model.rowCount() == 2
    service.jobs.run_pending()  # émet job_changed depuis ce thread
    _process(qapp, 300)
    assert all(r.status == RecordingStatus.DONE for r in service.repo.list_recordings())


def test_close_hides_instead_of_quitting(qapp, window):
    w, _ = window
    w.close()
    assert not w.isVisible()


def test_env_roundtrip(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# commentaire\nANTHROPIC_API_KEY=sk-old\n# NOTER_WHISPER_MODEL=large-v3\nAUTRE=1\n")
    write_env(p, {"ANTHROPIC_API_KEY": "sk-new", "NOTER_WHISPER_MODEL": "small", "NOTER_CLAUDE_EFFORT": "high"})
    env = read_env(p)
    assert env["ANTHROPIC_API_KEY"] == "sk-new" and env["NOTER_WHISPER_MODEL"] == "small"
    assert env["NOTER_CLAUDE_EFFORT"] == "high" and env["AUTRE"] == "1"
    assert p.read_text().startswith("# commentaire\n")
    assert Qt is not None
