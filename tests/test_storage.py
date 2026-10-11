from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime

from noter.models import JobKind, JobStatus, Recording, RecordingStatus, Segment, Source, Summary
from noter.storage.db import Database
from noter.storage.migrations import CURRENT_VERSION, current_version
from noter.storage.repo import Repository


def _rec(home, title="Test", **kw) -> Recording:
    d = home / "recordings" / "x"
    return Recording(
        id=str(uuid.uuid4()), title=title, source=Source.MAC_MIC, status=RecordingStatus.RECORDED,
        started_at=datetime(2026, 3, 3, 14, 30), audio_path=d / "audio.wav", dir_path=d, **kw,
    )


def test_fresh_db_gets_latest_schema(home):
    db = Database(home / "noter.db")
    conn = db.connect()
    assert current_version(conn) == CURRENT_VERSION
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"recordings", "segments", "summaries", "jobs", "tags", "recording_tags"} <= tables


def test_recording_crud_and_tags(home):
    repo = Repository(Database(home / "noter.db"))
    rec = repo.create_recording(_rec(home, project="ACME", tags=["client", "devis"]))
    assert rec.tags == ["client", "devis"]
    assert repo.get_recording(rec.id[:8]).id == rec.id

    repo.update_recording(rec.id, title="Nouveau", status=RecordingStatus.DONE)
    got = repo.get_recording(rec.id)
    assert got.title == "Nouveau" and got.status == RecordingStatus.DONE

    repo.set_tags(rec.id, ["devis"])
    assert repo.get_recording(rec.id).tags == ["devis"]
    assert repo.all_tags() == ["devis"]
    assert repo.all_projects() == ["ACME"]
    assert [r.id for r in repo.list_recordings(tag="devis")] == [rec.id]
    assert repo.list_recordings(tag="client") == []

    repo.delete_recording(rec.id)
    assert repo.get_recording(rec.id) is None


def test_segments_summary_and_search(home):
    repo = Repository(Database(home / "noter.db"))
    rec = repo.create_recording(_rec(home, title="Point budget"))
    repo.replace_segments(rec.id, [
        Segment(0, 2, "On valide le budget marketing de 50k", speaker="A"),
        Segment(2, 5, "Et on décale la prévisualisation", speaker="B"),
    ])
    repo.upsert_summary(Summary(recording_id=rec.id, model="fake", tldr="Budget validé à 50k", decisions=["Budget 50k"]))

    assert len(repo.get_segments(rec.id)) == 2
    assert repo.get_summary(rec.id).decisions == ["Budget 50k"]

    kinds = {h.kind for h in repo.search("budget")}
    assert kinds == {"segment", "summary", "title"}
    # accent-insensible + préfixe
    assert any(h.kind == "segment" for h in repo.search("previsu"))
    assert repo.search("zzzz") == []

    assert repo.rename_speaker(rec.id, "A", "Nassim") == 1
    assert repo.get_segments(rec.id)[0].speaker == "Nassim"

    repo.set_action_done(rec.id, 0, True) if repo.get_summary(rec.id).actions else None


def test_jobs_lifecycle(home):
    repo = Repository(Database(home / "noter.db"))
    rec = repo.create_recording(_rec(home))
    j = repo.enqueue_job(rec.id, JobKind.TRANSCRIBE, max_attempts=2)
    # idempotent tant que le job est actif
    assert repo.enqueue_job(rec.id, JobKind.TRANSCRIBE).id == j.id

    claimed = repo.claim_next_job()
    assert claimed.id == j.id and claimed.status == JobStatus.RUNNING and claimed.attempts == 1
    assert repo.claim_next_job() is None

    failed_once = repo.finish_job(j.id, ok=False, error="boom")
    assert failed_once.status == JobStatus.QUEUED  # retry
    repo.claim_next_job()
    failed = repo.finish_job(j.id, ok=False, error="boom")
    assert failed.status == JobStatus.FAILED and failed.error == "boom"

    assert repo.retry_failed_jobs(rec.id) == 1
    assert repo.get_job(j.id).status == JobStatus.QUEUED

    repo.claim_next_job()
    assert repo.requeue_running_jobs() == 1


def test_legacy_v01_database_is_migrated(home):
    path = home / "noter.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE recordings (id TEXT PRIMARY KEY, title TEXT, mode TEXT NOT NULL, started_at TEXT NOT NULL,
            ended_at TEXT, duration_s REAL, audio_path TEXT NOT NULL, language TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE segments (id INTEGER PRIMARY KEY AUTOINCREMENT, recording_id TEXT, speaker TEXT,
            start_time REAL NOT NULL, end_time REAL NOT NULL, text TEXT NOT NULL);
        CREATE TABLE summaries (id INTEGER PRIMARY KEY AUTOINCREMENT, recording_id TEXT UNIQUE, model TEXT NOT NULL,
            tldr TEXT, decisions TEXT, action_items TEXT, followups TEXT, full_summary TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE VIRTUAL TABLE transcripts_fts USING fts5(recording_id, speaker, text, content=segments, content_rowid=id);
        CREATE TRIGGER segments_ai AFTER INSERT ON segments BEGIN
            INSERT INTO transcripts_fts(rowid, recording_id, speaker, text) VALUES (new.id, new.recording_id, new.speaker, new.text);
        END;
        INSERT INTO recordings VALUES ('aaa', 'Vieux call', 'system+mic', '2026-01-01T10:00:00', '2026-01-01T10:30:00', 1800,
            '/tmp/old/2026-01-01_10h00_Vieux-call/audio.wav', 'fr', '2026-01-01T10:31:00');
        INSERT INTO recordings VALUES ('bbb', NULL, 'iphone', '2026-01-02T10:00:00', NULL, 60, '/tmp/old/x/audio.m4a', NULL, NULL);
        INSERT INTO segments(recording_id, speaker, start_time, end_time, text) VALUES ('aaa', NULL, 0, 2, 'Bonjour'), ('aaa', NULL, 2, 4, 'Salut');
        INSERT INTO summaries(recording_id, model, tldr, decisions, action_items, followups, full_summary)
            VALUES ('aaa', 'claude-x', 'Un résumé', '- D1\n- D2', '- [ ] A1', '- K1', '');
        """
    )
    conn.commit()
    conn.close()

    repo = Repository(Database(path))
    assert current_version(repo.db.connect()) == CURRENT_VERSION
    old = repo.get_recording("aaa")
    assert old.source == Source.MAC_SYSTEM_MIC and old.status == RecordingStatus.DONE
    assert str(old.dir_path).endswith("2026-01-01_10h00_Vieux-call")
    assert repo.get_recording("bbb").source == Source.IMPORT
    assert repo.get_recording("bbb").status == RecordingStatus.RECORDED
    assert [s.text for s in repo.get_segments("aaa")] == ["Bonjour", "Salut"]
    s = repo.get_summary("aaa")
    assert s.decisions == ["D1", "D2"] and s.key_points == ["K1"] and s.actions[0].text == "A1"
    assert any(h.kind == "segment" for h in repo.search("bonjour"))
    # les tables legacy ont disparu
    names = {r[0] for r in repo.db.connect().execute("SELECT name FROM sqlite_master")}
    assert not any(n.startswith("legacy_") for n in names) and "transcripts_fts" not in names
