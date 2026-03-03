"""Capture audio — mic + système via BlackHole."""
from __future__ import annotations

import logging
import signal
import threading
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd
from rich.console import Console
from scipy.io import wavfile

from noter.audio.devices import find_blackhole, find_default_mic
from noter.audio.monitor import RecordingMonitor
from noter.config import settings
from noter.storage.files import get_call_dir

logger = logging.getLogger(__name__)
console = Console()


class Recorder:
    """Enregistreur audio multi-device (micro + système)."""

    def __init__(self, mode: str = "system+mic", title: str | None = None):
        self.mode = mode
        self.title = title
        self.recording_id = str(uuid.uuid4())
        self.sample_rate = settings.sample_rate
        self.started_at: datetime | None = None
        self.ended_at: datetime | None = None
        self.audio_path: Path | None = None
        self._stop_event = threading.Event()
        self._monitor = RecordingMonitor()
        self._mic_chunks: list[np.ndarray] = []
        self._sys_chunks: list[np.ndarray] = []
        self._threads: list[threading.Thread] = []

    @property
    def is_recording(self) -> bool:
        return self.started_at is not None and self.ended_at is None

    @property
    def elapsed(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.ended_at or datetime.now()
        return (end - self.started_at).total_seconds()

    def _get_devices(self) -> tuple[int | None, int | None]:
        """Retourne (mic_device_index, system_device_index)."""
        mic = find_default_mic()
        mic_idx = mic.index if mic else None

        if self.mode == "mic_only":
            return mic_idx, None

        blackhole = find_blackhole()
        if not blackhole:
            logger.warning("BlackHole non détecté — enregistrement micro seul")
            return mic_idx, None

        return mic_idx, blackhole.index

    def _record_stream(self, device_index: int, label: str, chunks: list[np.ndarray]):
        """Enregistre un stream depuis un device donné."""

        def callback(indata, frames, time_info, status):
            if status and status.input_overflow:
                pass
            chunks.append(indata.copy())
            self._monitor.update(indata, label=label)

        stream = sd.InputStream(
            device=device_index,
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            callback=callback,
            blocksize=4096,
        )
        stream.start()
        self._stop_event.wait()
        stream.stop()
        stream.close()

    def start_async(self):
        """Lance l'enregistrement en background (non-bloquant). Appeler stop() pour arrêter."""
        mic_idx, sys_idx = self._get_devices()

        if mic_idx is None:
            raise RuntimeError("Aucun micro détecté")

        self.started_at = datetime.now()
        call_dir = get_call_dir(self.started_at.isoformat(), self.title)
        self.audio_path = call_dir / "audio.wav"

        self._mic_chunks = []
        self._sys_chunks = []
        self._stop_event.clear()

        # Lancer les threads d'enregistrement
        mic_thread = threading.Thread(
            target=self._record_stream,
            args=(mic_idx, "MIC", self._mic_chunks),
            daemon=True,
        )
        self._threads = [mic_thread]
        mic_thread.start()

        if sys_idx is not None:
            sys_thread = threading.Thread(
                target=self._record_stream,
                args=(sys_idx, "SYS", self._sys_chunks),
                daemon=True,
            )
            self._threads.append(sys_thread)
            sys_thread.start()

        logger.info(f"Enregistrement démarré: {self.recording_id[:8]} ({self.mode})")

    def stop(self) -> Path:
        """Arrête l'enregistrement, sauvegarde le WAV, retourne le chemin."""
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=3)

        self.ended_at = datetime.now()

        audio = self._mix_audio(self._mic_chunks, self._sys_chunks)
        wavfile.write(str(self.audio_path), self.sample_rate, audio)

        logger.info(f"Enregistrement sauvegardé: {self.audio_path} ({self.elapsed:.0f}s)")
        return self.audio_path

    def start(self) -> Path:
        """Lance l'enregistrement BLOQUANT (pour le CLI). Ctrl+C pour arrêter."""
        self.start_async()

        console.print(f"[green bold]Enregistrement démarré[/green bold] ({self.mode})")
        console.print(f"  ID: [cyan]{self.recording_id[:8]}[/cyan]")
        if self.title:
            console.print(f"  Titre: {self.title}")
        console.print("  [dim]Ctrl+C pour arrêter[/dim]\n")

        def handle_stop(sig, frame):
            self._stop_event.set()

        signal.signal(signal.SIGINT, handle_stop)

        self._monitor.start()
        self._stop_event.wait()
        self._monitor.stop()

        audio_path = self.stop()

        duration = self.elapsed
        console.print(f"\n[green bold]Enregistrement terminé[/green bold]")
        console.print(f"  Durée: {int(duration // 60)}:{int(duration % 60):02d}")
        console.print(f"  Fichier: {audio_path}")

        return audio_path

    def _mix_audio(self, mic_chunks: list[np.ndarray], sys_chunks: list[np.ndarray]) -> np.ndarray:
        """Mixe les streams micro et système."""
        if not mic_chunks:
            return np.array([], dtype="float32")

        mic_audio = np.concatenate(mic_chunks, axis=0).flatten()

        if not sys_chunks:
            return mic_audio

        sys_audio = np.concatenate(sys_chunks, axis=0).flatten()

        min_len = min(len(mic_audio), len(sys_audio))
        mic_audio = mic_audio[:min_len]
        sys_audio = sys_audio[:min_len]

        mixed = 0.5 * mic_audio + 0.5 * sys_audio

        peak = np.max(np.abs(mixed))
        if peak > 0:
            mixed = mixed / peak * 0.95

        return mixed.astype("float32")


def save_recording(recorder: Recorder):
    """Sauvegarde un enregistrement en base de données."""
    from noter.storage.database import get_db

    db = get_db()
    duration = recorder.elapsed

    db.execute(
        """INSERT INTO recordings (id, title, mode, started_at, ended_at, duration_s, audio_path)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            recorder.recording_id,
            recorder.title,
            recorder.mode,
            recorder.started_at.isoformat() if recorder.started_at else None,
            recorder.ended_at.isoformat() if recorder.ended_at else None,
            duration,
            str(recorder.audio_path),
        ),
    )
    db.commit()
    return recorder.recording_id


def run_pipeline(recording_id: str):
    """Lance transcription + résumé pour un enregistrement."""
    from noter.transcription.engine import transcribe_recording
    from noter.analyzer.claude import summarize_recording

    transcribe_recording(recording_id)
    summarize_recording(recording_id)


def start_recording(mode: str = "system+mic", title: str | None = None):
    """Point d'entrée CLI — enregistre puis lance le pipeline."""
    recorder = Recorder(mode=mode, title=title)
    recorder.start()

    recording_id = save_recording(recorder)
    console.print(f"\n[bold]Enregistrement sauvegardé.[/bold] ID: [cyan]{recording_id[:8]}[/cyan]")

    console.print("\n[bold]Transcription en cours...[/bold]")
    console.print("[bold]Résumé IA en cours...[/bold]")
    run_pipeline(recording_id)
