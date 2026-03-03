"""Interface transcription + factory avec détection plateforme."""
from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from noter.config import settings
from noter.storage.database import get_db, get_recording, insert_segments
from noter.storage.files import save_transcript_file

console = Console()


@dataclass
class Segment:
    start: float
    end: float
    text: str
    speaker: str | None = None


def get_whisper_engine():
    """Factory — retourne le bon moteur Whisper selon la plateforme."""
    if settings.is_apple_silicon:
        try:
            from noter.transcription.mlx_whisper import MlxWhisperEngine
            return MlxWhisperEngine()
        except ImportError:
            console.print("[dim]mlx-whisper non installé, fallback sur faster-whisper[/dim]")

    from noter.transcription.faster_whisper import FasterWhisperEngine
    return FasterWhisperEngine()


def transcribe_recording(recording_id: str):
    """Pipeline complet : transcription + diarisation + sauvegarde."""
    rec = get_recording(recording_id)
    if not rec:
        console.print(f"[red]Enregistrement '{recording_id}' introuvable.[/red]")
        return

    audio_path = rec["audio_path"]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        # 1. Transcription Whisper
        task = progress.add_task("Transcription Whisper...", total=None)
        engine = get_whisper_engine()
        raw_segments, language = engine.transcribe(audio_path)
        progress.update(task, description=f"Transcription terminée ({language}, {len(raw_segments)} segments)")

        # 2. Diarisation (speaker identification) — désactivable via NOTER_DIARIZE=true
        if settings.diarize:
            task2 = progress.add_task("Diarisation...", total=None)
            try:
                from noter.transcription.diarization import diarize

                speaker_map = diarize(audio_path)
                segments = _merge_speakers(raw_segments, speaker_map)
                progress.update(task2, description=f"Diarisation terminée ({len(set(s.speaker for s in segments if s.speaker))} speakers)")
            except Exception as e:
                console.print(f"[yellow]Diarisation ignorée: {e}[/yellow]")
                segments = raw_segments
                progress.update(task2, description="Diarisation ignorée")
        else:
            segments = raw_segments

    # 3. Sauvegarder en base
    seg_dicts = [{"speaker": s.speaker, "start": s.start, "end": s.end, "text": s.text} for s in segments]
    insert_segments(rec["id"], seg_dicts)

    # Mettre à jour la langue détectée
    db = get_db()
    db.execute("UPDATE recordings SET language = ? WHERE id = ?", (language, rec["id"]))
    db.commit()

    # 4. Sauvegarder fichier transcript
    transcript_path = save_transcript_file(rec["started_at"], rec.get("title"), seg_dicts)

    console.print(f"[green]Transcription sauvegardée[/green] ({len(segments)} segments)")
    console.print(f"  Fichier: {transcript_path}")
    console.print(f"  Langue: {language}")


def _merge_speakers(whisper_segments: list[Segment], speaker_map: list[dict]) -> list[Segment]:
    """Associe chaque segment Whisper au speaker détecté par diarisation."""
    for seg in whisper_segments:
        mid_time = (seg.start + seg.end) / 2
        best_speaker = None
        best_overlap = 0

        for sp in speaker_map:
            overlap_start = max(seg.start, sp["start"])
            overlap_end = min(seg.end, sp["end"])
            overlap = max(0, overlap_end - overlap_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = sp["speaker"]

        seg.speaker = best_speaker or "Speaker ?"

    return whisper_segments
