"""Interface commune des moteurs de transcription."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from noter.models import Segment


@dataclass
class TranscriptionResult:
    segments: list[Segment]
    language: str


class TranscriptionEngine(Protocol):
    name: str

    def transcribe(self, audio_path: Path, language: str | None = None) -> TranscriptionResult: ...


class FakeEngine:
    """Moteur de test : renvoie des segments prédéfinis sans charger de modèle."""

    name = "fake"

    def __init__(self, segments: list[Segment] | None = None, language: str = "fr"):
        self._segments = segments or [Segment(start=0.0, end=2.0, text="Bonjour tout le monde.")]
        self._language = language
        self.calls: list[Path] = []

    def transcribe(self, audio_path: Path, language: str | None = None) -> TranscriptionResult:
        self.calls.append(Path(audio_path))
        return TranscriptionResult(segments=list(self._segments), language=self._language)
