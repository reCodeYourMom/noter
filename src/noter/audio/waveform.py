"""Enveloppe d'un fichier audio (pics par tranche) pour la timeline, sans tout charger en mémoire."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

WAVEFORM_NAME = "waveform.json"
DEFAULT_BINS = 600


def compute_peaks(audio_path: Path, bins: int = DEFAULT_BINS) -> list[float]:
    """Retourne `bins` valeurs 0..1 (RMS normalisé par tranche)."""
    import soundfile as sf

    try:
        with sf.SoundFile(str(audio_path)) as f:
            total = f.frames
            if total <= 0:
                return []
            per_bin = max(1, total // bins)
            peaks: list[float] = []
            while len(peaks) < bins:
                block = f.read(per_bin, dtype="float32", always_2d=True)
                if len(block) == 0:
                    break
                mono = block.mean(axis=1)
                peaks.append(float(np.sqrt(np.mean(mono * mono))))
    except Exception:  # noqa: BLE001
        # Formats non-WAV (m4a, mp3…) : via PyAV, décodage complet par paquets
        peaks = _peaks_via_av(audio_path, bins)
    if not peaks:
        return []
    arr = np.array(peaks, dtype="float32")
    top = float(np.percentile(arr, 98)) or float(arr.max()) or 1.0
    arr = np.clip(arr / top, 0.0, 1.0)
    return [round(float(v), 3) for v in arr]


def _peaks_via_av(audio_path: Path, bins: int) -> list[float]:
    try:
        import av
    except ImportError:
        return []
    samples: list[np.ndarray] = []
    try:
        with av.open(str(audio_path)) as c:
            stream = c.streams.audio[0]
            for frame in c.decode(stream):
                arr = frame.to_ndarray()
                mono = arr.mean(axis=0) if arr.ndim > 1 else arr
                samples.append(mono.astype("float32"))
    except Exception:  # noqa: BLE001
        return []
    if not samples:
        return []
    data = np.concatenate(samples)
    if data.dtype.kind in "iu":
        data = data / np.iinfo(data.dtype).max
    per_bin = max(1, len(data) // bins)
    out = []
    for i in range(0, per_bin * bins, per_bin):
        chunk = data[i : i + per_bin]
        if len(chunk):
            out.append(float(np.sqrt(np.mean(chunk * chunk))))
    return out


def write_waveform(audio_path: Path, out_dir: Path, bins: int = DEFAULT_BINS) -> Path | None:
    peaks = compute_peaks(audio_path, bins)
    if not peaks:
        return None
    path = out_dir / WAVEFORM_NAME
    path.write_text(json.dumps(peaks), encoding="utf-8")
    return path


def read_waveform(dir_path: Path) -> list[float] | None:
    path = dir_path / WAVEFORM_NAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [float(v) for v in data]
    except Exception:  # noqa: BLE001
        return None
