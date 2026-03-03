"""Feedback visuel pendant l'enregistrement."""
from __future__ import annotations

import threading
import time

import numpy as np
from rich.console import Console
from rich.live import Live
from rich.text import Text

console = Console()


class RecordingMonitor:
    """Affiche durée et niveaux audio en temps réel."""

    def __init__(self):
        self._start_time: float | None = None
        self._level: float = 0.0
        self._label: str = ""
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._levels: dict[str, float] = {}

    def update(self, audio_data: np.ndarray, label: str = "MIC"):
        """Met à jour le niveau audio (appelé depuis le callback)."""
        rms = float(np.sqrt(np.mean(audio_data ** 2)))
        with self._lock:
            self._levels[label] = rms

    def start(self):
        """Démarre l'affichage en temps réel."""
        self._start_time = time.time()
        self._running = True
        self._thread = threading.Thread(target=self._display_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Arrête l'affichage."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1)

    def _display_loop(self):
        """Boucle d'affichage des niveaux."""
        with Live(console=console, refresh_per_second=4) as live:
            while self._running:
                elapsed = time.time() - self._start_time if self._start_time else 0
                minutes = int(elapsed // 60)
                seconds = int(elapsed % 60)

                with self._lock:
                    levels = dict(self._levels)

                parts = [Text(f"  {minutes:02d}:{seconds:02d}  ", style="bold green")]

                for label, level in sorted(levels.items()):
                    bar_len = int(min(level * 200, 30))
                    bar = "█" * bar_len + "░" * (30 - bar_len)
                    color = "green" if level < 0.05 else "yellow" if level < 0.15 else "red"
                    parts.append(Text(f"  {label}: ", style="dim"))
                    parts.append(Text(bar, style=color))

                display = Text()
                for p in parts:
                    display.append_text(p)

                live.update(display)
                time.sleep(0.25)
