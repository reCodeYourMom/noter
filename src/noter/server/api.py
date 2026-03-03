"""Serveur local FastAPI pour recevoir les enregistrements iPhone."""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime

import av
import rumps
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse

from noter.config import settings
from noter.storage.database import get_db

logger = logging.getLogger(__name__)

api = FastAPI(title="Noter", description="Serveur local pour enregistrements iPhone")


def _get_audio_duration(path: str) -> float:
    """Retourne la durée d'un fichier audio en secondes via PyAV."""
    try:
        container = av.open(path)
        stream = container.streams.audio[0]
        duration = float(stream.duration * stream.time_base)
        container.close()
        return duration
    except Exception:
        return 0.0


@api.post("/upload")
async def upload_recording(
    audio: UploadFile = File(...),
    title: str = Form(None),
):
    """
    Reçoit un enregistrement audio depuis l'iPhone (Shortcut iOS).

    Accepte : m4a, mp3, wav, caf, ogg — faster-whisper les lit via PyAV.
    """
    from noter.storage.files import get_call_dir, get_audio_path

    recording_id = str(uuid.uuid4())
    now = datetime.now()
    started_at = now.isoformat()

    # Déterminer l'extension
    ext = audio.filename.rsplit(".", 1)[-1] if audio.filename and "." in audio.filename else "m4a"
    audio_path = get_audio_path(started_at, title, ext=ext)

    # Sauvegarder le fichier
    content = await audio.read()
    audio_path.write_bytes(content)
    file_size_mb = len(content) / (1024 * 1024)

    # Calculer la durée
    duration = _get_audio_duration(str(audio_path))

    logger.info(f"Upload reçu: {audio.filename} ({file_size_mb:.1f} MB, {duration:.0f}s) → {audio_path}")

    # Enregistrer en base
    db = get_db()
    db.execute(
        """INSERT INTO recordings (id, title, mode, started_at, duration_s, audio_path)
           VALUES (?, ?, 'iphone', ?, ?, ?)""",
        (recording_id, title, started_at, duration, str(audio_path)),
    )
    db.commit()

    # Notification macOS
    dur_str = f"{int(duration // 60)}min {int(duration % 60):02d}s" if duration else "?"
    try:
        rumps.notification("Noter", f"iPhone — {title or 'Enregistrement'}", f"Reçu ({dur_str}). Transcription en cours...")
    except Exception:
        pass

    # Pipeline en background
    threading.Thread(
        target=_process_pipeline,
        args=(recording_id,),
        daemon=True,
    ).start()

    return JSONResponse({
        "status": "ok",
        "recording_id": recording_id,
        "duration_s": duration,
        "message": f"Enregistrement reçu ({file_size_mb:.1f} MB, {dur_str}). Transcription en cours...",
    })


@api.get("/recordings")
async def list_recordings(limit: int = 20):
    """Liste les derniers enregistrements."""
    db = get_db()
    rows = db.execute(
        "SELECT id, title, mode, started_at, duration_s, language FROM recordings ORDER BY started_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [{
        "id": r[0], "title": r[1], "mode": r[2],
        "started_at": r[3], "duration_s": r[4], "language": r[5],
    } for r in rows]


@api.get("/recordings/{recording_id}")
async def get_recording_detail(recording_id: str):
    """Détail d'un enregistrement avec transcript et résumé."""
    from noter.storage.database import get_recording, get_segments

    rec = get_recording(recording_id)
    if not rec:
        return JSONResponse({"error": "Not found"}, status_code=404)

    segments = get_segments(rec["id"])

    db = get_db()
    summary = db.execute(
        "SELECT tldr, decisions, action_items, followups FROM summaries WHERE recording_id = ?",
        (rec["id"],),
    ).fetchone()

    return {
        "recording": rec,
        "segments": segments,
        "summary": {
            "tldr": summary[0],
            "decisions": summary[1],
            "actions": summary[2],
            "key_points": summary[3],
        } if summary else None,
    }


@api.get("/health")
async def health():
    return {"status": "ok", "service": "noter"}


def _process_pipeline(recording_id: str):
    """Pipeline de traitement en background (transcription + résumé)."""
    try:
        from noter.transcription.engine import transcribe_recording
        logger.info(f"Pipeline démarré pour {recording_id[:8]}")
        transcribe_recording(recording_id)

        from noter.analyzer.claude import summarize_recording
        summarize_recording(recording_id)

        logger.info(f"Pipeline terminé pour {recording_id[:8]}")

        # Notification macOS quand c'est prêt
        try:
            rumps.notification("Noter", "Résumé prêt", f"Enregistrement iPhone {recording_id[:8]} traité")
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Erreur pipeline {recording_id[:8]}: {e}")
        try:
            rumps.notification("Noter", "Erreur pipeline", str(e)[:100])
        except Exception:
            pass
