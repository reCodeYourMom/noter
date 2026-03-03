"""Détection et listing des devices audio (BlackHole, micro)."""
from __future__ import annotations

from dataclasses import dataclass

import sounddevice as sd
from rich.console import Console
from rich.table import Table

console = Console()


@dataclass
class AudioDevice:
    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: float
    is_blackhole: bool


def get_all_devices() -> list[AudioDevice]:
    """Retourne tous les devices audio d'entrée disponibles."""
    devices = sd.query_devices()
    result = []
    for i, d in enumerate(devices):
        if d["max_input_channels"] > 0:
            result.append(AudioDevice(
                index=i,
                name=d["name"],
                max_input_channels=d["max_input_channels"],
                max_output_channels=d["max_output_channels"],
                default_samplerate=d["default_samplerate"],
                is_blackhole="blackhole" in d["name"].lower(),
            ))
    return result


def find_blackhole() -> AudioDevice | None:
    """Trouve le device BlackHole (loopback audio système)."""
    for d in get_all_devices():
        if d.is_blackhole:
            return d
    return None


def find_default_mic() -> AudioDevice | None:
    """Trouve le micro par défaut."""
    default_input = sd.query_devices(kind="input")
    if default_input:
        idx = sd.default.device[0]
        d = sd.query_devices(idx)
        return AudioDevice(
            index=idx,
            name=d["name"],
            max_input_channels=d["max_input_channels"],
            max_output_channels=d["max_output_channels"],
            default_samplerate=d["default_samplerate"],
            is_blackhole="blackhole" in d["name"].lower(),
        )
    return None


def list_devices():
    """Affiche les devices audio dans un tableau Rich."""
    devices = get_all_devices()
    blackhole = find_blackhole()
    default_mic = find_default_mic()

    table = Table(title="Devices audio (entrée)")
    table.add_column("Index", justify="right", style="cyan")
    table.add_column("Nom")
    table.add_column("Channels", justify="right")
    table.add_column("Sample Rate", justify="right")
    table.add_column("Rôle")

    for d in devices:
        role = ""
        if d.is_blackhole:
            role = "[green]BlackHole (système)[/green]"
        elif default_mic and d.index == default_mic.index:
            role = "[blue]Micro par défaut[/blue]"

        table.add_row(
            str(d.index),
            d.name,
            str(d.max_input_channels),
            f"{d.default_samplerate:.0f}",
            role,
        )

    console.print(table)

    if not blackhole:
        console.print(
            "\n[yellow]BlackHole non détecté.[/yellow] "
            "Installe-le avec : [bold]brew install blackhole-2ch[/bold]\n"
            "Puis crée un 'Multi-Output Device' dans Audio MIDI Setup "
            "pour capturer l'audio système."
        )
