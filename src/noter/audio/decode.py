"""Décodage audio → signal mono float32 à 16 kHz, le format attendu par Whisper.

Noter décode lui-même plutôt que de laisser faster-whisper le faire : son décodeur interne
appelle PyAV avec des options qui varient selon les versions (PyAV 19 a retiré `metadata_errors`).
"""
from __future__ import annotations

from math import gcd
from pathlib import Path

import numpy as np

WHISPER_RATE = 16000


def load_audio_16k(path: Path) -> np.ndarray:
    """WAV/FLAC/OGG via soundfile ; tout le reste (m4a, mp3…) via PyAV."""
    try:
        return _decode_soundfile(Path(path))
    except Exception:  # noqa: BLE001
        return _decode_av(Path(path))


def _resample(x: np.ndarray, rate: int) -> np.ndarray:
    if rate == WHISPER_RATE:
        return x.astype("float32", copy=False)
    from scipy.signal import resample_poly

    g = gcd(rate, WHISPER_RATE)
    return resample_poly(x, WHISPER_RATE // g, rate // g).astype("float32")


def _decode_soundfile(path: Path) -> np.ndarray:
    import soundfile as sf

    data, rate = sf.read(str(path), dtype="float32", always_2d=True)
    return _resample(data.mean(axis=1), int(rate))


def _decode_av(path: Path) -> np.ndarray:
    import av

    chunks: list[np.ndarray] = []
    resampler = av.AudioResampler(format="flt", layout="mono", rate=WHISPER_RATE)
    with av.open(str(path)) as container:
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        raise ValueError(f"Aucun audio décodable dans {path.name}")
    return np.concatenate(chunks).astype("float32", copy=False)
