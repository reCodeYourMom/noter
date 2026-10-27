from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import make_wav

from noter.analyzer.claude import FakeSummarizer
from noter.models import JobKind, JobStatus, RecordingStatus
from noter.pipeline import Pipeline
from noter.storage import files


def test_import_then_full_pipeline(service, wav, engine, summarizer):
    rec = service.import_file(wav, title="Call client", project="ACME", tags=["client"])
    assert rec.status == RecordingStatus.RECORDED
    assert rec.duration_s and abs(rec.duration_s - 2.0) < 0.01
    assert rec.audio_path.exists() and wav.exists()  # copie, pas déplacement

    assert service.jobs.run_pending() == 2  # transcribe + summarize
    rec = service.repo.get_recording(rec.id)
    assert rec.status == RecordingStatus.DONE and rec.language == "fr"
    assert engine.calls == [rec.audio_path] and summarizer.calls == 1

    assert (rec.dir_path / files.TRANSCRIPT_NAME).exists()
    assert (rec.dir_path / files.SUMMARY_NAME).exists()
    assert (rec.dir_path / files.PDF_NAME).exists()
    meta = json.loads((rec.dir_path / files.META_NAME).read_text())
    assert meta["project"] == "ACME" and meta["tags"] == ["client"] and meta["status"] == "done"

    md = (rec.dir_path / files.SUMMARY_NAME).read_text()
    assert "Résumé de test." in md and "- [ ] Nassim : Envoyer le devis (avant le vendredi)" in md

    summary = service.repo.get_summary(rec.id)
    assert summary.actions[0].owner == "Nassim"
    assert [j.status for j in service.repo.list_jobs(recording_id=rec.id)] == [JobStatus.DONE, JobStatus.DONE]


def test_summarize_failure_is_retried_then_fails(service, wav, settings, engine):
    flaky = FakeSummarizer(fail_times=10)
    service.pipeline = Pipeline(service.repo, settings, engine=engine, summarizer=flaky)
    service.jobs.pipeline = service.pipeline
    service.jobs.max_attempts = 2

    rec = service.import_file(wav)
    service.jobs.run_pending()
    rec = service.repo.get_recording(rec.id)
    assert rec.status == RecordingStatus.FAILED
    job = [j for j in service.repo.list_jobs(recording_id=rec.id) if j.kind == JobKind.SUMMARIZE][0]
    assert job.status == JobStatus.FAILED and job.attempts == 2 and "échec simulé" in job.error
    # le transcript, lui, est bien là
    assert len(service.repo.get_segments(rec.id)) == 1

    # retry : on repart du résumé seulement
    flaky.fail_times = 0
    assert service.jobs.retry(rec.id) == 1
    service.jobs.run_pending()
    assert service.repo.get_recording(rec.id).status == RecordingStatus.DONE
    assert len(engine.calls) == 1  # pas re-transcrit


def test_auto_summarize_off(service, wav):
    service.jobs.auto_summarize = False
    rec = service.import_file(wav)
    assert service.jobs.run_pending() == 1
    assert service.repo.get_recording(rec.id).status == RecordingStatus.TRANSCRIBED
    assert service.repo.get_summary(rec.id) is None


def test_recover_interrupted_recording(service, settings):
    """Un crash pendant l'enregistrement laisse _mic.wav : au démarrage on finalise et on traite."""
    from datetime import datetime
    from uuid import uuid4

    from noter.audio.recorder import MIC_TMP, SYS_TMP
    from noter.models import Recording, Source

    d = files.recording_dir(settings.data_dir, datetime(2026, 5, 1, 9, 0), "Crash")
    make_wav(d / MIC_TMP, seconds=3.0, rate=48000)
    make_wav(d / SYS_TMP, seconds=3.0, rate=44100, freq=220)
    rec = Recording(id=str(uuid4()), source=Source.MAC_SYSTEM_MIC, status=RecordingStatus.RECORDING,
                    started_at=datetime(2026, 5, 1, 9, 0), audio_path=d / "audio.wav", dir_path=d, title="Crash")
    service.repo.create_recording(rec)

    touched = service.recover()
    assert touched == [rec.id]
    rec = service.repo.get_recording(rec.id)
    assert rec.status == RecordingStatus.RECORDED and abs(rec.duration_s - 3.0) < 0.01
    assert rec.audio_path.exists() and not (d / MIC_TMP).exists() and not (d / SYS_TMP).exists()
    assert service.repo.list_jobs(recording_id=rec.id, active_only=True)

    service.jobs.run_pending()
    assert service.repo.get_recording(rec.id).status == RecordingStatus.DONE


def test_recover_requeues_stuck_processing(service, wav):
    rec = service.import_file(wav, enqueue=False)
    service.repo.set_status(rec.id, RecordingStatus.TRANSCRIBING)  # crash pendant la transcription, job perdu
    service.repo.db.connect().execute("DELETE FROM jobs")
    assert service.recover() == [rec.id]
    service.jobs.run_pending()
    assert service.repo.get_recording(rec.id).status == RecordingStatus.DONE


def test_update_metadata_rerenders_outputs(service, wav):
    rec = service.import_file(wav)
    service.jobs.run_pending()
    rec = service.update_metadata(rec.id, title="Renommé", tags=["x", "y"], project="P")
    assert rec.title == "Renommé" and rec.tags == ["x", "y"]
    md = (rec.dir_path / files.SUMMARY_NAME).read_text()
    assert md.startswith("# Renommé") and "Tags : x, y" in md


def test_delete_recording_removes_files(service, wav):
    rec = service.import_file(wav, enqueue=False)
    d = rec.dir_path
    service.delete_recording(rec.id)
    assert service.repo.get_recording(rec.id) is None and not d.exists()


def test_import_rejects_unknown_format(service, tmp_path):
    bad = tmp_path / "x.txt"
    bad.write_text("nope")
    import pytest

    with pytest.raises(ValueError):
        service.import_file(bad)
    with pytest.raises(FileNotFoundError):
        service.import_file(Path("/nope/none.wav"))


def test_recording_deleted_during_processing(service, wav, settings, summarizer):
    """Supprimer un enregistrement pendant sa transcription ne doit pas faire planter le worker."""
    from noter.models import Segment
    from noter.transcription.base import FakeEngine, TranscriptionResult

    class DeletingEngine(FakeEngine):
        def transcribe(self, audio_path, language=None):
            service.delete_recording(rec.id)  # l'utilisateur supprime pendant le traitement
            return TranscriptionResult(segments=[Segment(0, 1, "x")], language="fr")

    service.pipeline = Pipeline(service.repo, settings, engine=DeletingEngine(), summarizer=summarizer)
    service.jobs.pipeline = service.pipeline
    rec = service.import_file(wav)
    assert service.jobs.run_pending() == 1  # pas d'exception
    assert service.repo.get_recording(rec.id) is None
    assert service.repo.list_jobs(recording_id=rec.id) == []
    assert service.jobs.current is None


def test_card_from_action_creates_once_in_first_list(service, wav):
    rec = service.import_file(wav, title="Call ACME")
    service.jobs.run_pending()

    card = service.card_from_action(rec.id, 0)
    board = service.repo.list_boards()[0]
    first = service.repo.get_lists(board.id)[0]
    assert board.name == "Mes tâches" and first.name == "À faire"
    assert [lst.name for lst in service.repo.get_lists(board.id)] == ["À faire", "En cours", "Terminé"]
    assert card.list_id == first.id and card.recording_id == rec.id
    assert card.title == "Envoyer le devis"
    assert "Responsable : Nassim" in card.description and "Call ACME" in card.description
    assert "Échéance annoncée : vendredi" in card.description and card.due is None  # texte libre, pas une date

    again = service.card_from_action(rec.id, 0)  # idempotent
    assert again.id == card.id and len(service.repo.cards_in_list(first.id)) == 1

    other = service.create_board("Perso")
    assert service.default_board().id == board.id  # le premier board reste la cible par défaut
    try:
        service.card_from_action(rec.id, 7, other.id)
    except IndexError:
        pass
    else:
        raise AssertionError("une action inexistante doit lever IndexError")


def test_card_from_action_parses_iso_due_date(service, wav):
    from datetime import date

    from noter.models import ActionItem

    rec = service.import_file(wav)
    service.jobs.run_pending()
    summary = service.repo.get_summary(rec.id)
    summary.actions = [ActionItem("Livrer", owner=None, due="2026-04-02")]
    service.repo.upsert_summary(summary)
    card = service.card_from_action(rec.id, 0)
    assert card.due == date(2026, 4, 2) and "Échéance annoncée" not in card.description
