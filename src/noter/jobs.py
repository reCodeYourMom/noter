"""File de jobs persistée (table `jobs`) + worker unique en thread.

- Un seul worker : Whisper sature déjà le CPU/GPU, inutile de paralléliser.
- Chaque job est rejoué jusqu'à max_attempts en cas d'erreur.
- Au démarrage, les jobs restés 'running' (crash) sont remis en file.
- Les abonnés (UI) sont prévenus à chaque changement d'état.
"""
from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable

from noter.models import Job, JobKind, JobStatus, RecordingStatus
from noter.pipeline import Pipeline
from noter.storage.repo import Repository

logger = logging.getLogger(__name__)

Listener = Callable[[Job], None]


class JobQueue:
    def __init__(self, repo: Repository, pipeline: Pipeline, auto_summarize: bool = True, max_attempts: int = 3,
                 notifier: Callable[[str, str], None] | None = None):
        self.repo = repo
        self.pipeline = pipeline
        self.auto_summarize = auto_summarize
        self.max_attempts = max_attempts
        self.notify = notifier or (lambda t, m: None)
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._listeners: list[Listener] = []
        self._current: Job | None = None
        self._lock = threading.Lock()

    # ─── API ────────────────────────────────────────────────────────

    def subscribe(self, fn: Listener) -> None:
        self._listeners.append(fn)

    def unsubscribe(self, fn: Listener) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    @property
    def current(self) -> Job | None:
        with self._lock:
            return self._current

    def enqueue(self, recording_id: str, kind: JobKind) -> Job:
        job = self.repo.enqueue_job(recording_id, kind, self.max_attempts)
        self._emit(job)
        self._wake.set()
        return job

    def process_recording(self, recording_id: str) -> Job:
        """Lance la chaîne complète (transcription puis résumé)."""
        return self.enqueue(recording_id, JobKind.TRANSCRIBE)

    def retry(self, recording_id: str) -> int:
        n = self.repo.retry_failed_jobs(recording_id)
        if n == 0:
            # Rien d'échoué : on relance depuis l'état actuel
            rec = self.repo.get_recording(recording_id)
            if rec is None:
                return 0
            if rec.status in (RecordingStatus.TRANSCRIBED, RecordingStatus.SUMMARIZING) or (
                rec.status == RecordingStatus.FAILED and self.repo.get_segments(rec.id)
            ):
                self.enqueue(rec.id, JobKind.SUMMARIZE)
            else:
                self.enqueue(rec.id, JobKind.TRANSCRIBE)
            return 1
        self._wake.set()
        return n

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        n = self.repo.requeue_running_jobs()
        if n:
            logger.info("%d job(s) interrompu(s) remis en file", n)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="noter-jobs", daemon=True)
        self._thread.start()
        self._wake.set()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def run_pending(self) -> int:
        """Exécute tous les jobs en attente de façon synchrone (CLI, tests)."""
        n = 0
        while not self._stop.is_set():
            job = self.repo.claim_next_job()
            if job is None:
                break
            self._run(job)
            n += 1
        return n

    # ─── Worker ─────────────────────────────────────────────────────

    def _loop(self) -> None:
        logger.info("Worker jobs démarré")
        while not self._stop.is_set():
            self._wake.wait(timeout=5.0)
            self._wake.clear()
            try:
                self.run_pending()
            except Exception:  # noqa: BLE001
                logger.exception("Erreur inattendue dans le worker")
        logger.info("Worker jobs arrêté")

    def _run(self, job: Job) -> None:
        with self._lock:
            self._current = job
        self._emit(job)
        logger.info("Job #%d %s %s (tentative %d/%d)", job.id, job.kind, job.recording_id[:8], job.attempts, job.max_attempts)
        try:
            if job.kind == JobKind.TRANSCRIBE:
                self.pipeline.transcribe(job.recording_id)
            elif job.kind == JobKind.SUMMARIZE:
                self.pipeline.summarize(job.recording_id)
            else:
                raise ValueError(f"Job inconnu : {job.kind}")
            done = self.repo.finish_job(job.id, ok=True)
            self._emit(done)
            self._after_success(done)
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
            logger.error("Job #%d en erreur : %s\n%s", job.id, err, traceback.format_exc())
            failed = self.repo.finish_job(job.id, ok=False, error=err)
            self._emit(failed)
            if failed.status == JobStatus.FAILED:
                self.notify("Noter — échec", f"{job.kind} : {err[:120]}")
        finally:
            with self._lock:
                self._current = None

    def _after_success(self, job: Job) -> None:
        if job.kind == JobKind.TRANSCRIBE:
            if self.auto_summarize:
                self.enqueue(job.recording_id, JobKind.SUMMARIZE)
            else:
                self.notify("Noter", "Transcription terminée")
        elif job.kind == JobKind.SUMMARIZE:
            rec = self.repo.get_recording(job.recording_id)
            self.notify("Noter — résumé prêt", rec.display_title if rec else job.recording_id[:8])

    def _emit(self, job: Job) -> None:
        for fn in list(self._listeners):
            try:
                fn(job)
            except Exception:  # noqa: BLE001
                logger.exception("listener jobs en erreur")
