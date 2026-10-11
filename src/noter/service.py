"""Le service Noter : point d'entrée unique pour la CLI et l'UI.

Il assemble base, pipeline, file de jobs et enregistreur, et gère :
- start/stop d'un enregistrement (mixage à l'arrêt, puis mise en file),
- import d'un fichier audio existant,
- récupération après crash (enregistrement interrompu, jobs bloqués).
"""
from __future__ import annotations

import logging
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

from noter import notify
from noter.audio.mixer import mix_wavs, wav_duration
from noter.audio.recorder import MIC_TMP, SYS_TMP, Recorder
from noter.audio.waveform import write_waveform
from noter.config import Settings, load_settings
from noter.jobs import JobQueue
from noter.models import Recording, RecordingStatus, Source
from noter.pipeline import Pipeline
from noter.storage import files
from noter.storage.db import Database
from noter.storage.repo import Repository

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".wav", ".m4a", ".mp3", ".mp4", ".aac", ".flac", ".ogg", ".caf", ".webm", ".opus"}


class Service:
    def __init__(self, settings: Settings | None = None, pipeline: Pipeline | None = None):
        self.settings = settings or load_settings()
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(self.settings.db_path)
        self.repo = Repository(self.db)
        self.pipeline = pipeline or Pipeline(self.repo, self.settings)
        self.jobs = JobQueue(
            self.repo, self.pipeline,
            auto_summarize=self.settings.auto_summarize,
            max_attempts=self.settings.job_max_attempts,
            notifier=notify.notify,
        )
        self._recorder: Recorder | None = None
        self._current: Recording | None = None
        self._lock = threading.Lock()

    # ─── Cycle de vie ───────────────────────────────────────────────

    def start(self) -> None:
        """À appeler une fois au démarrage : récupération + worker."""
        self.recover()
        self.jobs.start()

    def stop(self) -> None:
        if self.is_recording:
            self.stop_recording()
        self.jobs.stop()
        self.db.close()

    # ─── Enregistrement ─────────────────────────────────────────────

    @property
    def is_recording(self) -> bool:
        return self._recorder is not None and self._recorder.is_recording

    @property
    def current_recording(self) -> Recording | None:
        return self._current

    @property
    def recorder(self) -> Recorder | None:
        return self._recorder

    def start_recording(self, with_system_audio: bool = True, title: str | None = None,
                        project: str | None = None, tags: list[str] | None = None) -> Recording:
        with self._lock:
            if self.is_recording:
                raise RuntimeError("Un enregistrement est déjà en cours")
            started = datetime.now()
            rec_dir = files.recording_dir(self.settings.data_dir, started, title)
            recorder = Recorder(rec_dir, with_system_audio, self.settings.sample_rate)
            recorder.start()
            source = Source.MAC_SYSTEM_MIC if recorder.system_audio_captured else Source.MAC_MIC
            rec = Recording(
                id=str(uuid.uuid4()), title=title, source=source, status=RecordingStatus.RECORDING,
                started_at=started, audio_path=rec_dir / files.AUDIO_NAME, dir_path=rec_dir,
                project=project, tags=tags or [],
            )
            self.repo.create_recording(rec)
            files.write_meta(rec)
            self._recorder, self._current = recorder, rec
            logger.info("Enregistrement %s démarré dans %s", rec.short_id, rec_dir)
            return rec

    def stop_recording(self, enqueue: bool = True) -> Recording:
        with self._lock:
            if self._recorder is None or self._current is None:
                raise RuntimeError("Aucun enregistrement en cours")
            recorder, rec = self._recorder, self._current
            self._recorder, self._current = None, None
        recorder.stop()
        rec = self._finalize(rec, recorder.mic_path, recorder.sys_path)
        if enqueue:
            self.jobs.process_recording(rec.id)
        return rec

    def _finalize(self, rec: Recording, mic_path: Path, sys_path: Path | None) -> Recording:
        """Mixe les fichiers temporaires en audio.wav et passe en 'recorded'."""
        audio_path = rec.dir_path / files.AUDIO_NAME
        duration = 0.0
        if mic_path.exists():
            try:
                duration = mix_wavs(mic_path, sys_path, audio_path)
            finally:
                for p in (mic_path, sys_path):
                    if p and p.exists() and audio_path.exists():
                        p.unlink()
        status = RecordingStatus.RECORDED if audio_path.exists() and duration > 0 else RecordingStatus.FAILED
        self.repo.update_recording(
            rec.id, status=status, ended_at=datetime.now(), duration_s=duration, audio_path=audio_path,
        )
        rec = self.repo.get_recording(rec.id)  # type: ignore[assignment]
        files.write_meta(rec)
        self._waveform(rec)
        return rec

    def _waveform(self, rec: Recording) -> None:
        try:
            write_waveform(rec.audio_path, rec.dir_path)
        except Exception as e:  # noqa: BLE001
            logger.warning("Onde non calculée pour %s : %s", rec.short_id, e)

    # ─── Import ─────────────────────────────────────────────────────

    def import_file(self, path: Path, title: str | None = None, project: str | None = None,
                    tags: list[str] | None = None, enqueue: bool = True, move: bool = False) -> Recording:
        path = Path(path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        if path.suffix.lower() not in AUDIO_EXTENSIONS:
            raise ValueError(f"Format non supporté : {path.suffix}")
        started = datetime.fromtimestamp(path.stat().st_mtime)
        title = title or path.stem
        rec_dir = files.recording_dir(self.settings.data_dir, started, title)
        audio_path = rec_dir / f"audio{path.suffix.lower()}"
        (shutil.move if move else shutil.copy2)(str(path), str(audio_path))
        duration = wav_duration(audio_path) or _probe_duration(audio_path)
        rec = Recording(
            id=str(uuid.uuid4()), title=title, source=Source.IMPORT, status=RecordingStatus.RECORDED,
            started_at=started, ended_at=None, duration_s=duration, audio_path=audio_path, dir_path=rec_dir,
            project=project, tags=tags or [],
        )
        self.repo.create_recording(rec)
        files.write_meta(rec)
        self._waveform(rec)
        if enqueue:
            self.jobs.process_recording(rec.id)
        logger.info("Import %s : %s (%.0fs)", rec.short_id, path.name, duration)
        return rec

    # ─── Récupération ───────────────────────────────────────────────

    def recover(self) -> list[str]:
        """Répare l'état après un crash. Retourne les IDs touchés."""
        touched = []
        for rec in self.repo.list_recordings(limit=1000, status=RecordingStatus.RECORDING):
            mic = rec.dir_path / MIC_TMP
            sysp = rec.dir_path / SYS_TMP
            logger.warning("Enregistrement %s interrompu — récupération", rec.short_id)
            rec = self._finalize(rec, mic, sysp if sysp.exists() else None)
            if rec.status == RecordingStatus.RECORDED:
                self.jobs.process_recording(rec.id)
            touched.append(rec.id)
        # Enregistrements bloqués en cours de traitement sans job actif
        for status in (RecordingStatus.TRANSCRIBING, RecordingStatus.SUMMARIZING):
            for rec in self.repo.list_recordings(limit=1000, status=status):
                if not self.repo.list_jobs(recording_id=rec.id, active_only=True):
                    self.jobs.retry(rec.id)
                    touched.append(rec.id)
        return touched

    # ─── Divers ─────────────────────────────────────────────────────

    def delete_recording(self, recording_id: str, delete_files: bool = True) -> None:
        rec = self.repo.get_recording(recording_id)
        if rec is None:
            return
        self.repo.delete_recording(rec.id)
        if delete_files and rec.dir_path.exists() and rec.dir_path.is_relative_to(self.settings.data_dir):
            shutil.rmtree(rec.dir_path, ignore_errors=True)

    def update_metadata(self, recording_id: str, **fields) -> Recording:
        tags = fields.pop("tags", None)
        if fields:
            self.repo.update_recording(recording_id, **fields)
        if tags is not None:
            self.repo.set_tags(recording_id, tags)
        rec = self.repo.get_recording(recording_id)
        assert rec is not None
        self.pipeline.render_outputs(rec.id)
        return rec


def _probe_duration(path: Path) -> float:
    """Durée d'un fichier non-WAV via PyAV (dépendance de faster-whisper)."""
    try:
        import av

        with av.open(str(path)) as c:
            if c.duration:
                return float(c.duration) / av.time_base
            s = c.streams.audio[0]
            return float(s.duration * s.time_base) if s.duration else 0.0
    except Exception:  # noqa: BLE001
        return 0.0
