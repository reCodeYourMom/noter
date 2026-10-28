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


# ─── Boards ─────────────────────────────────────────────────────────


def _board(repo, lists=("À faire", "En cours", "Terminé")):
    board = repo.create_board("Projet", lists=list(lists))
    return board, repo.get_lists(board.id)


def _titles(repo, list_id) -> list[str]:
    return [c.title for c in repo.cards_in_list(list_id)]


def test_v1_database_is_upgraded_to_boards(home):
    from noter.storage import migrations

    conn = sqlite3.connect(str(home / "old.db"), isolation_level=None)
    conn.row_factory = sqlite3.Row
    migrations.run_script(conn, migrations.SCHEMA_V1)
    conn.execute("INSERT INTO schema_version(version) VALUES (1)")
    conn.execute("INSERT INTO recordings(id, source, started_at, audio_path, dir_path) VALUES ('r1','import','2026-01-01T10:00:00','/a','/d')")
    conn.close()

    db = Database(home / "old.db")
    assert current_version(db.connect()) == CURRENT_VERSION >= 2
    repo = Repository(db)
    assert repo.get_recording("r1") is not None  # les données existantes sont intactes
    board, lists = _board(repo)
    assert len(lists) == 3 and repo.list_boards() == [board]


def test_board_and_list_crud(home):
    repo = Repository(Database(home / "noter.db"))
    board, lists = _board(repo)
    assert [lst.name for lst in lists] == ["À faire", "En cours", "Terminé"]
    assert [lst.position for lst in lists] == [0, 1, 2]

    extra = repo.create_list(board.id, "Backlog")
    assert extra.position == 3
    repo.rename_list(extra.id, "Idées")
    repo.rename_board(board.id, "  Sprint 12 ")
    assert repo.get_list(extra.id).name == "Idées" and repo.get_board(board.id).name == "Sprint 12"

    repo.move_list(extra.id, 0)
    assert [lst.name for lst in repo.get_lists(board.id)] == ["Idées", "À faire", "En cours", "Terminé"]
    repo.move_list(extra.id, 99)  # borné
    assert [lst.name for lst in repo.get_lists(board.id)][-1] == "Idées"

    repo.delete_list(lists[0].id)
    assert [lst.position for lst in repo.get_lists(board.id)] == [0, 1, 2]  # renumérotées sans trou

    for bad in ("", "   "):
        for call in (lambda b=bad: repo.create_board(b), lambda b=bad: repo.create_list(board.id, b), lambda b=bad: repo.rename_list(extra.id, b)):
            try:
                call()
            except ValueError:
                continue
            raise AssertionError("un nom vide doit être refusé")


def test_card_ordering_and_moves(home):
    repo = Repository(Database(home / "noter.db"))
    board, (todo, doing, done) = _board(repo)
    a, b, c = (repo.create_card(todo.id, t) for t in "abc")
    top = repo.create_card(todo.id, "top", at_top=True)
    assert _titles(repo, todo.id) == ["top", "a", "b", "c"]

    repo.move_card(c.id, todo.id, 0)  # même liste, vers le haut
    assert _titles(repo, todo.id) == ["c", "top", "a", "b"]
    repo.move_card(c.id, todo.id, 3)  # même liste, vers le bas
    assert _titles(repo, todo.id) == ["top", "a", "b", "c"]

    repo.move_card(a.id, doing.id, 0)  # autre liste, liste vide
    repo.move_card(b.id, doing.id, 1)
    repo.move_card(top.id, doing.id, 1)  # au milieu
    assert _titles(repo, doing.id) == ["a", "top", "b"]
    assert _titles(repo, todo.id) == ["c"]
    assert [x.position for x in repo.cards_in_list(doing.id)] == [0, 1, 2]
    assert [x.position for x in repo.cards_in_list(todo.id)] == [0]  # liste d'origine renumérotée

    repo.move_card(c.id, done.id, 50)  # index hors bornes → en fin
    assert _titles(repo, done.id) == ["c"]
    repo.move_card(c.id, 9999, 0)  # liste inexistante : rien ne bouge
    assert repo.get_card(c.id).list_id == done.id

    grouped = repo.cards_for_board(board.id)
    assert {k: [x.title for x in v] for k, v in grouped.items()} == {todo.id: [], doing.id: ["a", "top", "b"], done.id: ["c"]}
    assert repo.card_counts() == {board.id: 4}


def test_card_fields_roundtrip_and_validation(home):
    from datetime import date

    from noter.models import ChecklistItem

    repo = Repository(Database(home / "noter.db"))
    board, (todo, *_rest) = _board(repo)
    card = repo.create_card(
        todo.id, "  Envoyer le devis ", description="À faire avant lundi", due=date(2026, 3, 9),
        labels=["red", "green", "inconnue"], checklist=[ChecklistItem("Relire"), ChecklistItem("Envoyer", True)],
    )
    assert card.title == "Envoyer le devis"
    assert card.due == date(2026, 3, 9) and card.labels == ["green", "red"]  # ordre stable, clés inconnues ignorées
    assert card.checklist_progress == (1, 2)
    assert card.is_overdue(date(2026, 3, 10)) and not card.is_overdue(date(2026, 3, 9))

    repo.update_card(card.id, done=True, due=None, labels=[], checklist=[])
    got = repo.get_card(card.id)
    assert got.done and got.due is None and got.labels == [] and got.checklist == []
    assert not got.is_overdue(date(2030, 1, 1))  # sans échéance, jamais en retard

    for call in (
        lambda: repo.create_card(todo.id, "  "),
        lambda: repo.update_card(card.id, title=""),
        lambda: repo.update_card(card.id, position=3),
        lambda: repo.create_card(todo.id, "x", nope=1),
    ):
        try:
            call()
        except ValueError:
            continue
        raise AssertionError("valeur invalide acceptée")


def test_board_deletions_cascade_but_keep_recordings(home):
    repo = Repository(Database(home / "noter.db"))
    rec = repo.create_recording(_rec(home))
    board, (todo, doing, _done) = _board(repo)
    linked = repo.create_card(todo.id, "Lié", recording_id=rec.id)
    other = repo.create_card(doing.id, "Autre")
    assert [c.id for c in repo.cards_for_recording(rec.id)] == [linked.id]
    assert repo.board_of_card(linked.id).id == board.id

    repo.delete_recording(rec.id)  # la carte survit, sans lien
    assert repo.get_card(linked.id).recording_id is None

    repo.delete_list(todo.id)  # supprime ses cartes
    assert repo.get_card(linked.id) is None and repo.get_card(other.id) is not None
    repo.delete_card(other.id)
    assert repo.cards_in_list(doing.id) == []
    repo.delete_board(board.id)
    assert repo.list_boards() == [] and repo.get_lists(board.id) == []


def test_sort_list_by_due_puts_undated_last_and_is_stable(home):
    from datetime import date

    repo = Repository(Database(home / "noter.db"))
    board = repo.create_board("B")
    lst = repo.create_list(board.id, "L")
    other = repo.create_list(board.id, "Autre")
    a, b, c, d, e = (repo.create_card(lst.id, t) for t in "abcde")
    x = repo.create_card(other.id, "x")
    repo.update_card(a.id, due=date(2026, 5, 3))
    repo.update_card(c.id, due=date(2026, 5, 1))
    repo.update_card(e.id, due=date(2026, 5, 3))  # même jour que « a » : l'ordre existant est gardé
    repo.sort_list_by_due(lst.id)
    assert [k.title for k in repo.cards_in_list(lst.id)] == ["c", "a", "e", "b", "d"]
    assert [k.title for k in repo.cards_in_list(other.id)] == ["x"] and x.id
