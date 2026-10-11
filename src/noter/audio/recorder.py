"""Enregistreur : micro (+ audio système via BlackHole), écrit sur disque en continu.

Chaque flux va dans son propre WAV temporaire via une queue + un thread d'écriture :
la mémoire reste constante quelle que soit la durée, et un crash laisse des fichiers
exploitables (voir Service.recover()).
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from noter.audio.devices import AudioDevice, default_mic, find_blackhole, supported_samplerate

logger = logging.getLogger(__name__)

MIC_TMP = "_mic.wav"
SYS_TMP = "_sys.wav"


@dataclass
class _Stream:
    label: str
    device: AudioDevice
    samplerate: int
    path: Path
    q: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=512))
    level: float = 0.0
    frames: int = 0
    overflows: int = 0


class Recorder:
    def __init__(self, target_dir: Path, with_system_audio: bool, sample_rate: int = 48000):
        self.target_dir = Path(target_dir)
        self.with_system_audio = with_system_audio
        self.sample_rate = sample_rate
        self._streams: list[_Stream] = []
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._started_at: float | None = None
        self.system_audio_captured = False

    # ─── Infos ──────────────────────────────────────────────────────

    @property
    def is_recording(self) -> bool:
        return self._started_at is not None and not self._stop.is_set()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._started_at if self._started_at else 0.0

    @property
    def levels(self) -> dict[str, float]:
        return {s.label: s.level for s in self._streams}

    @property
    def mic_path(self) -> Path:
        return self.target_dir / MIC_TMP

    @property
    def sys_path(self) -> Path | None:
        return self.target_dir / SYS_TMP if self.system_audio_captured else None

    # ─── Cycle de vie ───────────────────────────────────────────────

    def start(self) -> None:
        mic = default_mic()
        if mic is None:
            raise RuntimeError("Aucun micro détecté (vérifie les permissions Micro dans Réglages Système)")
        self.target_dir.mkdir(parents=True, exist_ok=True)
        mic_rate = supported_samplerate(mic, self.sample_rate)
        self._streams = [_Stream("MIC", mic, mic_rate, self.mic_path)]

        if self.with_system_audio:
            bh = find_blackhole()
            if bh is None:
                logger.warning("BlackHole non détecté — micro seul")
            else:
                self._streams.append(_Stream("SYS", bh, supported_samplerate(bh, self.sample_rate), self.target_dir / SYS_TMP))
                self.system_audio_captured = True

        self._stop.clear()
        self._started_at = time.monotonic()
        for s in self._streams:
            t = threading.Thread(target=self._run_stream, args=(s,), name=f"rec-{s.label}", daemon=True)
            self._threads.append(t)
            t.start()
        logger.info("Enregistrement démarré (%s)", ", ".join(f"{s.label}@{s.samplerate}" for s in self._streams))

    def stop(self) -> float:
        """Arrête les flux, ferme les fichiers. Retourne la durée (s)."""
        self._stop.set()
        for t in self._threads:
            t.join(timeout=5)
        self._threads = []
        dur = self.elapsed
        self._started_at = None
        logger.info("Enregistrement arrêté (%.0fs)", dur)
        return dur

    # ─── Interne ────────────────────────────────────────────────────

    def _run_stream(self, s: _Stream) -> None:
        import sounddevice as sd
        import soundfile as sf

        def callback(indata, frames, time_info, status):
            if status and status.input_overflow:
                s.overflows += 1
            mono = indata.mean(axis=1) if indata.ndim > 1 else indata
            s.level = float(np.sqrt(np.mean(mono**2)))
            try:
                s.q.put_nowait(mono.copy())
            except queue.Full:
                s.overflows += 1

        try:
            with sf.SoundFile(str(s.path), "w", samplerate=s.samplerate, channels=1, subtype="PCM_16") as f:
                with sd.InputStream(device=s.device.index, samplerate=s.samplerate, channels=1,
                                    dtype="float32", blocksize=2048, callback=callback):
                    while not self._stop.is_set():
                        try:
                            chunk = s.q.get(timeout=0.25)
                        except queue.Empty:
                            continue
                        f.write(chunk)
                        s.frames += len(chunk)
                # Vider ce qui reste
                while True:
                    try:
                        chunk = s.q.get_nowait()
                    except queue.Empty:
                        break
                    f.write(chunk)
                    s.frames += len(chunk)
        except Exception:  # noqa: BLE001
            logger.exception("Flux %s en erreur", s.label)
            self._stop.set()
        if s.overflows:
            logger.warning("Flux %s : %d overflow(s)", s.label, s.overflows)
