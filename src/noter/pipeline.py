"""Le pipeline de traitement, unique et partagé par toutes les entrées.

    transcribe(rec)  →  segments + transcript.md     (status: transcribed)
    summarize(rec)   →  résumé + summary.md + PDF    (status: done)
"""
from __future__ import annotations

import logging
from pathlib import Path

from noter import tasks
from noter.analyzer.claude import Summarizer, to_summary
from noter.audio.mixer import SILENT_PEAK, peak_level, to_dbfs
from noter.config import Settings
from noter.models import Recording, RecordingStatus, Source, format_duration
from noter.storage import files
from noter.storage.repo import Repository
from noter.transcription.base import TranscriptionEngine
from noter.transcription.cleanup import clean_segments

logger = logging.getLogger(__name__)


class UnusableAudioError(RuntimeError):
    """L'audio ne contient rien à transcrire. Réessayer ne changera rien : le job échoue tout de suite."""

    retryable = False


MIC_HELP = (
    "Sur Mac, c'est presque toujours l'accès au micro refusé à Noter : Réglages Système → "
    "Confidentialité et sécurité → Micro → active Noter, puis relance l'app. Si Noter n'apparaît pas "
    "dans la liste, exécute `xcode-select --install` puis `noter app install`, et lance Noter depuis "
    "Noter.app (pas depuis le terminal). `noter doctor --mic` fait le test."
)


def silent_audio_message(rec: Recording, peak: float) -> str:
    level = "silence numérique absolu" if peak == 0.0 else f"pic à {to_dbfs(peak):.0f} dBFS"
    if rec.source == Source.IMPORT:
        return f"Fichier audio silencieux ({level}) : rien à transcrire."
    return f"Enregistrement silencieux ({level}) : aucun son n'a été capté pendant {format_duration(rec.duration_s)}. {MIC_HELP}"


def no_speech_message(rec: Recording, dropped: int) -> str:
    what = (f"Whisper n'a produit que {dropped} phrase(s) fantômes (du type « ご視聴ありがとうございました »), "
            "ce qu'il invente sur un audio muet ou inaudible") if dropped else "Whisper n'a détecté aucune parole"
    if rec.source == Source.IMPORT:
        return f"Aucune parole dans le fichier : {what}."
    return (f"Aucune parole dans l'enregistrement : {what}. Vérifie que le micro capte bien ta voix et, pour la voix "
            f"des autres, que la sortie audio est le périphérique à sorties multiples (BlackHole + écouteurs). {MIC_HELP}")


class Pipeline:
    def __init__(self, repo: Repository, settings: Settings, engine: TranscriptionEngine | None = None,
                 summarizer: Summarizer | None = None):
        self.repo = repo
        self.settings = settings
        self._engine = engine
        self._summarizer = summarizer

    # Les moteurs sont chargés paresseusement : lourds, et inutiles en test.
    @property
    def engine(self) -> TranscriptionEngine:
        if self._engine is None:
            from noter.transcription.engine import get_engine

            self._engine = get_engine(self.settings)
        return self._engine

    @property
    def summarizer(self) -> Summarizer:
        if self._summarizer is None:
            from noter.analyzer.claude import ClaudeSummarizer

            self._summarizer = ClaudeSummarizer(
                self.settings.anthropic_api_key, self.settings.claude_model, self.settings.claude_effort
            )
        return self._summarizer

    # ─── Étapes ─────────────────────────────────────────────────────

    def transcribe(self, recording_id: str) -> None:
        rec = self.repo.get_recording(recording_id)
        if rec is None:
            raise ValueError(f"Enregistrement {recording_id} introuvable")
        if not Path(rec.audio_path).exists():
            raise FileNotFoundError(f"Audio manquant : {rec.audio_path}")

        self.repo.set_status(rec.id, RecordingStatus.TRANSCRIBING)
        try:
            # Avant de lancer Whisper (long) : un audio muet ne donnerait que des phrases inventées
            peak = peak_level(Path(rec.audio_path))
            if peak is not None and peak < SILENT_PEAK:
                raise UnusableAudioError(silent_audio_message(rec, peak))

            result = self.engine.transcribe(Path(rec.audio_path), language=self.settings.whisper_language)
            segments, dropped = clean_segments(result.segments)
            if dropped:
                logger.info("Transcription %s : %d segment(s) fantôme(s) retiré(s)", rec.short_id, dropped)
            if not segments:
                raise UnusableAudioError(no_speech_message(rec, dropped))
            if self.settings.diarize and segments:
                try:
                    from noter.transcription.diarization import assign_speakers, diarize

                    segments = assign_speakers(segments, diarize(Path(rec.audio_path)))
                except Exception as e:  # noqa: BLE001
                    logger.warning("Diarisation ignorée : %s", e)

            self.repo.replace_segments(rec.id, segments)
            self.repo.update_recording(rec.id, language=result.language, status=RecordingStatus.TRANSCRIBED)
            rec = self.repo.get_recording(rec.id)
            files.write_text(rec.dir_path / files.TRANSCRIPT_NAME, files.transcript_markdown(rec, segments))
            files.write_meta(rec)
            logger.info("Transcription OK %s : %d segments (%s)", rec.short_id, len(segments), result.language)
        except Exception:
            self.repo.set_status(rec.id, RecordingStatus.FAILED)
            raise

    def summarize(self, recording_id: str, template: str = "default") -> int:
        """Résume l'enregistrement. Retourne le nombre de cartes créées dans les tâches."""
        rec = self.repo.get_recording(recording_id)
        if rec is None:
            raise ValueError(f"Enregistrement {recording_id} introuvable")
        segments = self.repo.get_segments(rec.id)
        if not segments:
            raise ValueError("Aucun segment : transcris d'abord l'enregistrement")

        self.repo.set_status(rec.id, RecordingStatus.SUMMARIZING)
        try:
            out = self.summarizer.summarize(
                files.transcript_plain(segments), format_duration(rec.duration_s), rec.title, template
            )
            summary = to_summary(rec.id, self.summarizer.name, template, out)
            self.repo.upsert_summary(summary)
            self.repo.set_status(rec.id, RecordingStatus.DONE)
            rec = self.repo.get_recording(rec.id)
            self.render_outputs(rec.id)
            logger.info("Résumé OK %s", rec.short_id)
        except Exception:
            self.repo.set_status(rec.id, RecordingStatus.FAILED)
            raise
        return self._actions_to_tasks(rec.id)

    def _actions_to_tasks(self, recording_id: str) -> int:
        """Toutes les actions du compte-rendu → cartes. Un échec ici ne doit pas faire échouer le résumé."""
        if not self.settings.auto_tasks:
            return 0
        try:
            created = tasks.cards_from_summary(self.repo, recording_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("Actions non ajoutées aux tâches pour %s : %s", recording_id[:8], e)
            return 0
        if created:
            logger.info("%d action(s) ajoutée(s) aux tâches pour %s", len(created), recording_id[:8])
        return len(created)

    def render_outputs(self, recording_id: str) -> None:
        """(Ré)écrit summary.md, rapport.pdf et meta.json depuis la base."""
        rec = self.repo.get_recording(recording_id)
        if rec is None:
            return
        segments = self.repo.get_segments(rec.id)
        summary = self.repo.get_summary(rec.id)
        files.write_meta(rec, summary)
        if segments:
            files.write_text(rec.dir_path / files.TRANSCRIPT_NAME, files.transcript_markdown(rec, segments))
        if summary is None:
            return
        files.write_text(rec.dir_path / files.SUMMARY_NAME, files.summary_markdown(rec, summary, segments))
        try:
            from noter.export.pdf import generate_pdf

            generate_pdf(rec.dir_path / files.PDF_NAME, rec, summary, segments)
        except Exception as e:  # noqa: BLE001
            logger.warning("PDF non généré pour %s : %s", rec.short_id, e)
