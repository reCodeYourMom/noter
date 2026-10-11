"""Migrations de schéma, versionnées et idempotentes.

- Une base vierge reçoit directement la dernière version.
- Une base v0.1 (sans table schema_version) est importée dans le nouveau schéma.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS recordings (
    id          TEXT PRIMARY KEY,
    title       TEXT,
    source      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'recorded',
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    duration_s  REAL,
    audio_path  TEXT NOT NULL,
    dir_path    TEXT NOT NULL,
    language    TEXT,
    project     TEXT,
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_recordings_started ON recordings(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_recordings_status ON recordings(status);

CREATE TABLE IF NOT EXISTS segments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id  TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    idx           INTEGER NOT NULL,
    speaker       TEXT,
    start_s       REAL NOT NULL,
    end_s         REAL NOT NULL,
    text          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_segments_recording ON segments(recording_id, idx);

CREATE TABLE IF NOT EXISTS summaries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id  TEXT NOT NULL UNIQUE REFERENCES recordings(id) ON DELETE CASCADE,
    model         TEXT NOT NULL,
    template      TEXT NOT NULL DEFAULT 'default',
    tldr          TEXT NOT NULL DEFAULT '',
    key_points    TEXT NOT NULL DEFAULT '[]',
    decisions     TEXT NOT NULL DEFAULT '[]',
    actions       TEXT NOT NULL DEFAULT '[]',
    raw_json      TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tags (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS recording_tags (
    recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    tag_id       INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (recording_id, tag_id)
);

CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id  TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'queued',
    attempts      INTEGER NOT NULL DEFAULT 0,
    max_attempts  INTEGER NOT NULL DEFAULT 3,
    error         TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    started_at    TEXT,
    finished_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, id);

CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
    text, content='segments', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS segments_ai AFTER INSERT ON segments BEGIN
    INSERT INTO segments_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS segments_ad AFTER DELETE ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS segments_au AFTER UPDATE ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO segments_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE VIRTUAL TABLE IF NOT EXISTS summaries_fts USING fts5(
    tldr, key_points, decisions, actions,
    content='summaries', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS summaries_ai AFTER INSERT ON summaries BEGIN
    INSERT INTO summaries_fts(rowid, tldr, key_points, decisions, actions)
    VALUES (new.id, new.tldr, new.key_points, new.decisions, new.actions);
END;
CREATE TRIGGER IF NOT EXISTS summaries_ad AFTER DELETE ON summaries BEGIN
    INSERT INTO summaries_fts(summaries_fts, rowid, tldr, key_points, decisions, actions)
    VALUES ('delete', old.id, old.tldr, old.key_points, old.decisions, old.actions);
END;
CREATE TRIGGER IF NOT EXISTS summaries_au AFTER UPDATE ON summaries BEGIN
    INSERT INTO summaries_fts(summaries_fts, rowid, tldr, key_points, decisions, actions)
    VALUES ('delete', old.id, old.tldr, old.key_points, old.decisions, old.actions);
    INSERT INTO summaries_fts(rowid, tldr, key_points, decisions, actions)
    VALUES (new.id, new.tldr, new.key_points, new.decisions, new.actions);
END;
"""

MIGRATIONS: list[tuple[int, str]] = [
    (1, SCHEMA_V1),
]

CURRENT_VERSION = MIGRATIONS[-1][0]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def current_version(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "schema_version"):
        return 0
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return int(row[0] or 0)


def is_legacy_db(conn: sqlite3.Connection) -> bool:
    """Base v0.1 : table recordings avec colonne `mode`, pas de schema_version."""
    return (
        not _table_exists(conn, "schema_version")
        and _table_exists(conn, "recordings")
        and "mode" in _columns(conn, "recordings")
    )


def run_script(conn: sqlite3.Connection, sql: str) -> None:
    """Exécute un script SQL instruction par instruction (sans le COMMIT implicite d'executescript)."""
    buf = ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            stmt = buf.strip()
            if stmt:
                conn.execute(stmt)
            buf = ""
    if buf.strip():
        conn.execute(buf)


def apply_all(conn: sqlite3.Connection) -> None:
    if is_legacy_db(conn):
        logger.info("Base v0.1 détectée — migration vers le schéma v1")
        _migrate_legacy(conn)

    version = current_version(conn)
    for target, sql in MIGRATIONS:
        if target <= version:
            continue
        logger.info("Migration schéma → v%d", target)
        conn.execute("BEGIN")
        try:
            run_script(conn, sql)
            conn.execute("INSERT INTO schema_version(version) VALUES (?)", (target,))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise


# ─── Import de la base v0.1 ─────────────────────────────────────────────

_LEGACY_SOURCE = {"system+mic": "mac_system_mic", "mic_only": "mac_mic", "iphone": "import"}


def _lines_to_list(text: str | None) -> list[str]:
    """'- a\\n- [ ] b' → ['a', 'b']"""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        for prefix in ("- [ ] ", "- [x] ", "- ", "* "):
            if line.startswith(prefix):
                line = line[len(prefix):]
                break
        out.append(line)
    return out


def _migrate_legacy(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN")
    try:
        # 1. Mettre l'ancien schéma de côté
        run_script(
            conn,
            """
            DROP TRIGGER IF EXISTS segments_ai;
            DROP TRIGGER IF EXISTS segments_ad;
            DROP TRIGGER IF EXISTS segments_au;
            DROP TABLE IF EXISTS transcripts_fts;
            ALTER TABLE recordings RENAME TO legacy_recordings;
            ALTER TABLE segments RENAME TO legacy_segments;
            ALTER TABLE summaries RENAME TO legacy_summaries;
            """
        )
        # 2. Nouveau schéma
        run_script(conn, SCHEMA_V1)
        conn.execute("INSERT INTO schema_version(version) VALUES (1)")

        # 3. Copier les données
        recs = conn.execute("SELECT * FROM legacy_recordings").fetchall()
        for r in recs:
            rid = r["id"]
            has_summary = conn.execute(
                "SELECT 1 FROM legacy_summaries WHERE recording_id=?", (rid,)
            ).fetchone()
            has_segments = conn.execute(
                "SELECT 1 FROM legacy_segments WHERE recording_id=? LIMIT 1", (rid,)
            ).fetchone()
            status = "done" if has_summary else ("transcribed" if has_segments else "recorded")
            audio_path = r["audio_path"] or ""
            conn.execute(
                """INSERT INTO recordings
                   (id, title, source, status, started_at, ended_at, duration_s, audio_path, dir_path,
                    language, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,COALESCE(?, datetime('now')))""",
                (
                    rid,
                    r["title"],
                    _LEGACY_SOURCE.get(r["mode"], "import"),
                    status,
                    r["started_at"],
                    r["ended_at"],
                    r["duration_s"],
                    audio_path,
                    str(Path(audio_path).parent) if audio_path else "",
                    r["language"],
                    r["created_at"],
                ),
            )

        segs = conn.execute(
            "SELECT recording_id, speaker, start_time, end_time, text FROM legacy_segments "
            "ORDER BY recording_id, start_time, id"
        ).fetchall()
        idx_by_rec: dict[str, int] = {}
        for s in segs:
            i = idx_by_rec.get(s["recording_id"], 0)
            idx_by_rec[s["recording_id"]] = i + 1
            conn.execute(
                "INSERT INTO segments(recording_id, idx, speaker, start_s, end_s, text) VALUES (?,?,?,?,?,?)",
                (s["recording_id"], i, s["speaker"], s["start_time"], s["end_time"], s["text"]),
            )

        sums = conn.execute("SELECT * FROM legacy_summaries").fetchall()
        for s in sums:
            actions = [{"text": a, "owner": None, "due": None, "done": False} for a in _lines_to_list(s["action_items"])]
            conn.execute(
                """INSERT INTO summaries(recording_id, model, template, tldr, key_points, decisions, actions, created_at)
                   VALUES (?,?,?,?,?,?,?,COALESCE(?, datetime('now')))""",
                (
                    s["recording_id"],
                    s["model"] or "unknown",
                    "legacy",
                    s["tldr"] or "",
                    json.dumps(_lines_to_list(s["followups"]), ensure_ascii=False),
                    json.dumps(_lines_to_list(s["decisions"]), ensure_ascii=False),
                    json.dumps(actions, ensure_ascii=False),
                    s["created_at"],
                ),
            )

        for t in ("legacy_summaries", "legacy_segments", "legacy_recordings"):
            conn.execute(f"DROP TABLE {t}")
        conn.execute("COMMIT")
        logger.info("Migration v0.1 terminée : %d enregistrements, %d segments, %d résumés", len(recs), len(segs), len(sums))
    except BaseException:
        conn.execute("ROLLBACK")
        raise
