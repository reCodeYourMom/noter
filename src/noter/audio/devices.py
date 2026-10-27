"""Détection des périphériques audio (micro, sortie, BlackHole). Import de sounddevice paresseux."""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Noms qu'on donne d'habitude au périphérique qui envoie le son à la fois aux écouteurs et à BlackHole
MULTI_OUTPUT_HINTS = ("multi", "sorties multiples", "agrégé", "agrege", "aggregate", "blackhole")


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


def refresh() -> None:
    """Relit la liste des périphériques.

    PortAudio la fige à son initialisation : sans ça, des écouteurs branchés après le lancement de Noter
    (qui vit des jours dans la barre de menu) restent invisibles, et un appareil débranché garde un
    index périmé. À n'appeler que lorsqu'aucun flux n'est ouvert : la réinitialisation les fermerait.
    """
    sd = _sd()
    try:
        if getattr(sd, "_initialized", 1) > 0:
            sd._terminate()
        sd._initialize()
    except Exception as e:  # noqa: BLE001
        logger.warning("Liste des périphériques audio non rafraîchie : %s", e)


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


def default_output_name() -> str | None:
    """Nom de la sortie audio actuelle du Mac (là où part le son des calls)."""
    sd = _sd()
    try:
        idx = sd.default.device[1]
        if idx is None or idx < 0:
            return None
        return str(sd.query_devices(idx)["name"])
    except Exception:  # noqa: BLE001
        return None


def looks_like_multi_output(name: str | None) -> bool:
    """La sortie ressemble-t-elle à un périphérique qui alimente aussi BlackHole ?

    Heuristique sur le nom : un périphérique à sorties multiples renommé passera pour suspect, d'où des
    messages au conditionnel côté UI, qui disparaissent dès que du son système arrive.
    """
    return bool(name) and any(h in name.lower() for h in MULTI_OUTPUT_HINTS)


@dataclass
class AudioRoute:
    """D'où vient le son d'un enregistrement, pour l'afficher et repérer un mauvais réglage."""

    mic: str
    output: str | None
    system: str | None  # BlackHole s'il est capté
    wanted_system: bool

    @property
    def system_missing(self) -> bool:
        """Audio système demandé mais BlackHole introuvable : seul le micro est enregistré."""
        return self.wanted_system and self.system is None

    @property
    def output_suspect(self) -> bool:
        """BlackHole est capté, mais la sortie du Mac ne semble pas l'alimenter (ex. sortie = AirPods)."""
        return self.system is not None and not looks_like_multi_output(self.output)

    def describe(self) -> str:
        parts = [f"Micro : {self.mic}"]
        if self.output:
            parts.append(f"Sortie : {self.output}")
        if self.system:
            parts.append(f"audio système via {self.system}")
        elif self.wanted_system:
            parts.append("micro seul (BlackHole absent)")
        return " · ".join(parts)
