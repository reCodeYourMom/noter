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
