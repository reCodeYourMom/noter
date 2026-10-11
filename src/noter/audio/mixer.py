"""Mixage de fichiers WAV sans tout charger en mémoire (pur numpy/soundfile, testable sans micro)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

CHUNK = 48000 * 10  # 10 s


def mix_wavs(mic_path: Path, sys_path: Path | None, out_path: Path, gain_mic: float = 1.0, gain_sys: float = 1.0) -> float:
    """Mixe mic (+ système) dans out_path (PCM16 mono). Retourne la durée en secondes."""
    if sys_path is None or not Path(sys_path).exists():
        return _copy_mono(mic_path, out_path)

    with sf.SoundFile(str(mic_path)) as mic, sf.SoundFile(str(sys_path)) as sysf:
        rate = mic.samplerate
        ratio_ok = sysf.samplerate == rate
        with sf.SoundFile(str(out_path), "w", samplerate=rate, channels=1, subtype="PCM_16") as out:
            frames = 0
            while True:
                a = mic.read(CHUNK, dtype="float32", always_2d=True).mean(axis=1)
                if len(a) == 0:
                    break
                n_sys = len(a) if ratio_ok else int(round(len(a) * sysf.samplerate / rate))
                b = sysf.read(n_sys, dtype="float32", always_2d=True).mean(axis=1)
                if not ratio_ok and len(b):
                    b = resample_poly(b, rate, sysf.samplerate).astype("float32")
                if len(b) < len(a):
                    b = np.pad(b, (0, len(a) - len(b)))
                b = b[: len(a)]
                mixed = np.clip(0.5 * (gain_mic * a + gain_sys * b), -1.0, 1.0)
                out.write(mixed)
                frames += len(a)
    return frames / rate


def _copy_mono(src: Path, dst: Path) -> float:
    with sf.SoundFile(str(src)) as f:
        rate = f.samplerate
        with sf.SoundFile(str(dst), "w", samplerate=rate, channels=1, subtype="PCM_16") as out:
            frames = 0
            while True:
                a = f.read(CHUNK, dtype="float32", always_2d=True)
                if len(a) == 0:
                    break
                out.write(a.mean(axis=1))
                frames += len(a)
    return frames / rate


def wav_duration(path: Path) -> float:
    try:
        info = sf.info(str(path))
        return float(info.frames) / float(info.samplerate)
    except Exception:  # noqa: BLE001
        return 0.0
