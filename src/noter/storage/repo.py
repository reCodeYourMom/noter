"""Accès aux données : toutes les requêtes SQL passent par ici."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from noter.models import (
    ActionItem,
    Job,
    JobKind,
    JobStatus,
    Recording,
    RecordingStatus,
    Segment,
    Source,
    Summary,
)
from noter.storage.db import Database


def _dt(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


def _iso(v: datetime | None) -> str | None:
    return v.isoformat(timespec="seconds") if v else None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class SearchHit:
    recording: Recording
    kind: str  # "segment" | "summary"
    snippet: str
    start_s: float | None = None


class Repository:
    def __init__(self, db: Database):
        self.db = db

    # ─── Recordings ─────────────────────────────────────────────────

    def _row_to_recording(self, r: sqlite3.Row, tags: list[str] | None = None) -> Recording:
        return Recording(
            id=r["id"],
            title=r["title"],
            source=Source(r["source"]),
            status=RecordingStatus(r["status"]),
            started_at=_dt(r["started_at"]) or datetime.now(),
            ended_at=_dt(r["ended_at"]),
            duration_s=r["duration_s"],
            audio_path=Path(r["audio_path"]),
            dir_path=Path(r["dir_path"]),
            language=r["language"],
            project=r["project"],
            notes=r["notes"],
            tags=tags if tags is not None else self._tags_for(r["id"]),
            created_at=_dt(r["created_at"]),
            updated_at=_dt(r["updated_at"]),
        )

    def create_recording(self, rec: Recording) -> Recording:
        with self.db.tx() as conn:
            conn.execute(
                """INSERT INTO recordings
                   (id, title, source, status, started_at, ended_at, duration_s, audio_path, dir_path,
                    language, project, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    rec.id, rec.title, str(rec.source), str(rec.status), _iso(rec.started_at), _iso(rec.ended_at),
                    rec.duration_s, str(rec.audio_path), str(rec.dir_path), rec.language, rec.project, rec.notes,
                ),
            )
        if rec.tags:
            self.set_tags(rec.id, rec.tags)
        return self.get_recording(rec.id)  # type: ignore[return-value]

    def get_recording(self, recording_id: str) -> Recording | None:
        """Récupère par ID complet, ou par préfixe s'il est unique."""
        conn = self.db.connect()
        row = conn.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)).fetchone()
        if row is None:
            rows = conn.execute("SELECT * FROM recordings WHERE id LIKE ?", (f"{recording_id}%",)).fetchall()
            if len(rows) != 1:
                return None
            row = rows[0]
        return self._row_to_recording(row)

    def list_recordings(
        self,
        limit: int = 50,
        offset: int = 0,
        status: RecordingStatus | None = None,
        project: str | None = None,
        tag: str | None = None,
    ) -> list[Recording]:
        conn = self.db.connect()
        sql = "SELECT r.* FROM recordings r"
        where, params = [], []
        if tag:
            sql += " JOIN recording_tags rt ON rt.recording_id = r.id JOIN tags t ON t.id = rt.tag_id"
            where.append("t.name = ?")
            params.append(tag)
        if status:
            where.append("r.status = ?")
            params.append(str(status))
        if project:
            where.append("r.project = ?")
            params.append(project)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY r.started_at DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        rows = conn.execute(sql, params).fetchall()
        return [self._row_to_recording(r) for r in rows]

    def update_recording(self, recording_id: str, **fields) -> None:
        allowed = {"title", "status", "ended_at", "duration_s", "language", "project", "notes", "audio_path"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"Champs non modifiables : {bad}")
        if not fields:
            return
        sets, params = [], []
        for k, v in fields.items():
            if isinstance(v, datetime):
                v = _iso(v)
            elif isinstance(v, Path):
                v = str(v)
            elif isinstance(v, RecordingStatus):
                v = str(v)
            sets.append(f"{k} = ?")
            params.append(v)
        sets.append("updated_at = ?")
        params.append(_now())
        params.append(recording_id)
        with self.db.tx() as conn:
            conn.execute(f"UPDATE recordings SET {', '.join(sets)} WHERE id = ?", params)

    def set_status(self, recording_id: str, status: RecordingStatus) -> None:
        self.update_recording(recording_id, status=status)

    def delete_recording(self, recording_id: str) -> None:
        with self.db.tx() as conn:
            conn.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))

    def count_recordings(self) -> int:
        return int(self.db.connect().execute("SELECT COUNT(*) FROM recordings").fetchone()[0])

    # ─── Tags / projets ─────────────────────────────────────────────

    def _tags_for(self, recording_id: str) -> list[str]:
        rows = self.db.connect().execute(
            "SELECT t.name FROM tags t JOIN recording_tags rt ON rt.tag_id = t.id "
            "WHERE rt.recording_id = ? ORDER BY t.name",
            (recording_id,),
        ).fetchall()
        return [r[0] for r in rows]

    def set_tags(self, recording_id: str, tags: list[str]) -> None:
        clean = sorted({t.strip() for t in tags if t and t.strip()})
        with self.db.tx() as conn:
            conn.execute("DELETE FROM recording_tags WHERE recording_id = ?", (recording_id,))
            for name in clean:
                conn.execute("INSERT OR IGNORE INTO tags(name) VALUES (?)", (name,))
                tag_id = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()[0]
                conn.execute(
                    "INSERT OR IGNORE INTO recording_tags(recording_id, tag_id) VALUES (?, ?)",
                    (recording_id, tag_id),
                )
            conn.execute("DELETE FROM tags WHERE id NOT IN (SELECT tag_id FROM recording_tags)")

    def all_tags(self) -> list[str]:
        return [r[0] for r in self.db.connect().execute("SELECT name FROM tags ORDER BY name")]

    def all_projects(self) -> list[str]:
        return [
            r[0]
            for r in self.db.connect().execute(
                "SELECT DISTINCT project FROM recordings WHERE project IS NOT NULL AND project != '' ORDER BY project"
            )
        ]

    # ─── Segments ───────────────────────────────────────────────────

    def replace_segments(self, recording_id: str, segments: list[Segment]) -> None:
        with self.db.tx() as conn:
            conn.execute("DELETE FROM segments WHERE recording_id = ?", (recording_id,))
            conn.executemany(
                "INSERT INTO segments(recording_id, idx, speaker, start_s, end_s, text) VALUES (?,?,?,?,?,?)",
                [(recording_id, i, s.speaker, s.start, s.end, s.text) for i, s in enumerate(segments)],
            )

    def get_segments(self, recording_id: str) -> list[Segment]:
        rows = self.db.connect().execute(
            "SELECT speaker, start_s, end_s, text FROM segments WHERE recording_id = ? ORDER BY idx",
            (recording_id,),
        ).fetchall()
        return [Segment(start=r["start_s"], end=r["end_s"], text=r["text"], speaker=r["speaker"]) for r in rows]

    def rename_speaker(self, recording_id: str, old: str | None, new: str) -> int:
        with self.db.tx() as conn:
            if old is None:
                cur = conn.execute(
                    "UPDATE segments SET speaker = ? WHERE recording_id = ? AND speaker IS NULL", (new, recording_id)
                )
            else:
                cur = conn.execute(
                    "UPDATE segments SET speaker = ? WHERE recording_id = ? AND speaker = ?", (new, recording_id, old)
                )
            return cur.rowcount

    # ─── Summaries ──────────────────────────────────────────────────

    def upsert_summary(self, s: Summary) -> None:
        with self.db.tx() as conn:
            conn.execute("DELETE FROM summaries WHERE recording_id = ?", (s.recording_id,))
            conn.execute(
                """INSERT INTO summaries(recording_id, model, template, tldr, key_points, decisions, actions, raw_json)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    s.recording_id, s.model, s.template, s.tldr,
                    json.dumps(s.key_points, ensure_ascii=False),
                    json.dumps(s.decisions, ensure_ascii=False),
                    json.dumps([a.to_dict() for a in s.actions], ensure_ascii=False),
                    s.raw_json,
                ),
            )

    def get_summary(self, recording_id: str) -> Summary | None:
        r = self.db.connect().execute("SELECT * FROM summaries WHERE recording_id = ?", (recording_id,)).fetchone()
        if r is None:
            return None
        return Summary(
            recording_id=r["recording_id"],
            model=r["model"],
            template=r["template"],
            tldr=r["tldr"],
            key_points=json.loads(r["key_points"] or "[]"),
            decisions=json.loads(r["decisions"] or "[]"),
            actions=[ActionItem.from_dict(a) for a in json.loads(r["actions"] or "[]")],
            raw_json=r["raw_json"],
            created_at=_dt(r["created_at"]),
        )

    def set_action_done(self, recording_id: str, index: int, done: bool) -> None:
        s = self.get_summary(recording_id)
        if s is None or index < 0 or index >= len(s.actions):
            raise IndexError("action introuvable")
        s.actions[index].done = done
        self.upsert_summary(s)

    # ─── Recherche plein texte ──────────────────────────────────────

    def search(self, query: str, limit: int = 30) -> list[SearchHit]:
        conn = self.db.connect()
        q = _fts_query(query)
        hits: list[SearchHit] = []
        rec_cache: dict[str, Recording] = {}

        def rec(rid: str) -> Recording:
            if rid not in rec_cache:
                rec_cache[rid] = self.get_recording(rid)  # type: ignore[assignment]
            return rec_cache[rid]

        rows = conn.execute(
            """SELECT s.recording_id, s.start_s, snippet(segments_fts, 0, '[', ']', '…', 12) AS snip, rank
               FROM segments_fts JOIN segments s ON s.id = segments_fts.rowid
               WHERE segments_fts MATCH ? ORDER BY rank LIMIT ?""",
            (q, limit),
        ).fetchall()
        for r in rows:
            hits.append(SearchHit(recording=rec(r["recording_id"]), kind="segment", snippet=r["snip"], start_s=r["start_s"]))

        rows = conn.execute(
            """SELECT su.recording_id, snippet(summaries_fts, -1, '[', ']', '…', 12) AS snip, rank
               FROM summaries_fts JOIN summaries su ON su.id = summaries_fts.rowid
               WHERE summaries_fts MATCH ? ORDER BY rank LIMIT ?""",
            (q, limit),
        ).fetchall()
        for r in rows:
            hits.append(SearchHit(recording=rec(r["recording_id"]), kind="summary", snippet=r["snip"]))

        # Titres (LIKE simple)
        rows = conn.execute(
            "SELECT id, title FROM recordings WHERE title LIKE ? ORDER BY started_at DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
        for r in rows:
            hits.append(SearchHit(recording=rec(r["id"]), kind="title", snippet=r["title"]))
        return hits

    # ─── Jobs ───────────────────────────────────────────────────────

    def _row_to_job(self, r: sqlite3.Row) -> Job:
        return Job(
            id=r["id"], recording_id=r["recording_id"], kind=JobKind(r["kind"]), status=JobStatus(r["status"]),
            attempts=r["attempts"], max_attempts=r["max_attempts"], error=r["error"],
            created_at=_dt(r["created_at"]), started_at=_dt(r["started_at"]), finished_at=_dt(r["finished_at"]),
        )

    def enqueue_job(self, recording_id: str, kind: JobKind, max_attempts: int = 3) -> Job:
        with self.db.tx() as conn:
            existing = conn.execute(
                "SELECT * FROM jobs WHERE recording_id = ? AND kind = ? AND status IN ('queued','running')",
                (recording_id, str(kind)),
            ).fetchone()
            if existing:
                return self._row_to_job(existing)
            cur = conn.execute(
                "INSERT INTO jobs(recording_id, kind, max_attempts, created_at) VALUES (?,?,?,?)",
                (recording_id, str(kind), max_attempts, _now()),
            )
            job_id = cur.lastrowid
        return self.get_job(job_id)  # type: ignore[return-value]

    def get_job(self, job_id: int) -> Job | None:
        r = self.db.connect().execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_job(r) if r else None

    def claim_next_job(self) -> Job | None:
        """Passe le plus ancien job 'queued' en 'running' de façon atomique."""
        with self.db.tx() as conn:
            r = conn.execute("SELECT * FROM jobs WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
            if r is None:
                return None
            conn.execute(
                "UPDATE jobs SET status='running', attempts = attempts + 1, started_at = ?, error = NULL WHERE id = ?",
                (_now(), r["id"]),
            )
        return self.get_job(r["id"])

    def finish_job(self, job_id: int, ok: bool, error: str | None = None) -> Job | None:
        """Clôt un job. Retourne None s'il n'existe plus (enregistrement supprimé entre-temps)."""
        job = self.get_job(job_id)
        if job is None:
            return None
        if ok:
            status = JobStatus.DONE
        elif job.attempts < job.max_attempts:
            status = JobStatus.QUEUED
        else:
            status = JobStatus.FAILED
        with self.db.tx() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, error = ?, finished_at = ? WHERE id = ?",
                (str(status), error, _now() if status != JobStatus.QUEUED else None, job_id),
            )
        return self.get_job(job_id)  # type: ignore[return-value]

    def requeue_running_jobs(self) -> int:
        """Au démarrage : les jobs restés 'running' (crash) repassent en file."""
        with self.db.tx() as conn:
            cur = conn.execute("UPDATE jobs SET status='queued', started_at=NULL WHERE status='running'")
            return cur.rowcount

    def retry_failed_jobs(self, recording_id: str) -> int:
        with self.db.tx() as conn:
            cur = conn.execute(
                "UPDATE jobs SET status='queued', attempts=0, error=NULL, finished_at=NULL "
                "WHERE recording_id = ? AND status='failed'",
                (recording_id,),
            )
            return cur.rowcount

    def list_jobs(self, limit: int = 50, recording_id: str | None = None, active_only: bool = False) -> list[Job]:
        sql, params = "SELECT * FROM jobs", []
        where = []
        if recording_id:
            where.append("recording_id = ?")
            params.append(recording_id)
        if active_only:
            where.append("status IN ('queued','running')")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [self._row_to_job(r) for r in self.db.connect().execute(sql, params)]

    def pending_job_count(self) -> int:
        return int(
            self.db.connect().execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
        )


def _fts_query(query: str) -> str:
    """Transforme une recherche libre en requête FTS5 sûre : chaque mot entre guillemets, préfixe."""
    words = [w.replace('"', '""') for w in query.split() if w.strip()]
    if not words:
        return '""'
    return " ".join(f'"{w}"*' for w in words)
