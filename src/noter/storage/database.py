"""SQLite + FTS5 — stockage recordings, segments, summaries."""
from __future__ import annotations

import sqlite3
from functools import lru_cache

from noter.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
    id          TEXT PRIMARY KEY,
    title       TEXT,
    mode        TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    duration_s  REAL,
    audio_path  TEXT NOT NULL,
    language    TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS segments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id  TEXT REFERENCES recordings(id),
    speaker       TEXT,
    start_time    REAL NOT NULL,
    end_time      REAL NOT NULL,
    text          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS summaries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id  TEXT REFERENCES recordings(id) UNIQUE,
    model         TEXT NOT NULL,
    tldr          TEXT,
    decisions     TEXT,
    action_items  TEXT,
    followups     TEXT,
    full_summary  TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts USING fts5(
    recording_id, speaker, text,
    content=segments, content_rowid=id
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS segments_ai AFTER INSERT ON segments BEGIN
    INSERT INTO transcripts_fts(rowid, recording_id, speaker, text)
    VALUES (new.id, new.recording_id, new.speaker, new.text);
END;

CREATE TRIGGER IF NOT EXISTS segments_ad AFTER DELETE ON segments BEGIN
    INSERT INTO transcripts_fts(transcripts_fts, rowid, recording_id, speaker, text)
    VALUES ('delete', old.id, old.recording_id, old.speaker, old.text);
END;

CREATE TRIGGER IF NOT EXISTS segments_au AFTER UPDATE ON segments BEGIN
    INSERT INTO transcripts_fts(transcripts_fts, rowid, recording_id, speaker, text)
    VALUES ('delete', old.id, old.recording_id, old.speaker, old.text);
    INSERT INTO transcripts_fts(rowid, recording_id, speaker, text)
    VALUES (new.id, new.recording_id, new.speaker, new.text);
END;
"""


_schema_initialized = False


def get_db() -> sqlite3.Connection:
    """Retourne une connexion SQLite thread-safe (une par thread via threading.local)."""
    global _schema_initialized
    import threading

    if not hasattr(get_db, "_local"):
        get_db._local = threading.local()

    local = get_db._local
    if not hasattr(local, "conn") or local.conn is None:
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        local.conn = sqlite3.connect(str(settings.db_path))
        if not _schema_initialized:
            local.conn.executescript(SCHEMA)
            _schema_initialized = True
        local.conn.execute("PRAGMA journal_mode=WAL")
        local.conn.execute("PRAGMA foreign_keys=ON")

    return local.conn


def insert_segments(recording_id: str, segments: list[dict]):
    """Insère des segments de transcription."""
    db = get_db()
    for seg in segments:
        db.execute(
            "INSERT INTO segments (recording_id, speaker, start_time, end_time, text) VALUES (?, ?, ?, ?, ?)",
            (recording_id, seg.get("speaker"), seg["start"], seg["end"], seg["text"]),
        )
    db.commit()


def insert_summary(recording_id: str, model: str, tldr: str, decisions: str, action_items: str, followups: str, full_summary: str):
    """Insère ou met à jour le résumé d'un enregistrement."""
    db = get_db()
    db.execute(
        """INSERT OR REPLACE INTO summaries (recording_id, model, tldr, decisions, action_items, followups, full_summary)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (recording_id, model, tldr, decisions, action_items, followups, full_summary),
    )
    db.commit()


def get_recording(recording_id: str) -> dict | None:
    """Récupère un enregistrement par ID (préfixe accepté)."""
    db = get_db()
    row = db.execute(
        "SELECT id, title, mode, started_at, ended_at, duration_s, audio_path, language FROM recordings WHERE id LIKE ?",
        (f"{recording_id}%",),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row[0], "title": row[1], "mode": row[2], "started_at": row[3],
        "ended_at": row[4], "duration_s": row[5], "audio_path": row[6], "language": row[7],
    }


def get_segments(recording_id: str) -> list[dict]:
    """Récupère les segments d'un enregistrement."""
    db = get_db()
    rows = db.execute(
        "SELECT speaker, start_time, end_time, text FROM segments WHERE recording_id = ? ORDER BY start_time",
        (recording_id,),
    ).fetchall()
    return [{"speaker": r[0], "start": r[1], "end": r[2], "text": r[3]} for r in rows]
