"""Détection des périphériques audio (micro, BlackHole). Import de sounddevice paresseux."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AudioDevice:
    index: int
    name: str
    input_channels: int
    default_samplerate: float

    @property
    def is_blackhole(self) -> bool:
        return "blackhole" in self.name.lower()


def _sd():
    import sounddevice as sd

    return sd


def input_devices() -> list[AudioDevice]:
    sd = _sd()
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            out.append(AudioDevice(i, d["name"], d["max_input_channels"], d["default_samplerate"]))
    return out


def find_blackhole() -> AudioDevice | None:
    return next((d for d in input_devices() if d.is_blackhole), None)


def default_mic() -> AudioDevice | None:
    sd = _sd()
    try:
        idx = sd.default.device[0]
        if idx is None or idx < 0:
            return None
        d = sd.query_devices(idx)
    except Exception:  # noqa: BLE001
        return None
    if d["max_input_channels"] <= 0:
        return None
    return AudioDevice(idx, d["name"], d["max_input_channels"], d["default_samplerate"])


def supported_samplerate(device: AudioDevice, wanted: int) -> int:
    """Retourne `wanted` si le device l'accepte, sinon son taux par défaut."""
    sd = _sd()
    try:
        sd.check_input_settings(device=device.index, samplerate=wanted, channels=1)
        return wanted
    except Exception:  # noqa: BLE001
        return int(device.default_samplerate)
