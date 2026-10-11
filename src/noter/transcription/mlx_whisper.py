"""mlx-whisper (Apple Silicon, GPU Metal)."""
from __future__ import annotations

import logging
from pathlib import Path

from noter.models import Segment
from noter.transcription.base import TranscriptionResult

logger = logging.getLogger(__name__)

MODEL_MAP = {
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "medium": "mlx-community/whisper-medium-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "tiny": "mlx-community/whisper-tiny-mlx",
}


class MlxWhisperEngine:
    name = "mlx-whisper"

    def __init__(self, model_name: str):
        import mlx_whisper  # noqa: F401  (ImportError → fallback dans la factory)

        self.repo = MODEL_MAP.get(model_name, model_name)

    def transcribe(self, audio_path: Path, language: str | None = None) -> TranscriptionResult:
        import mlx_whisper

        logger.info("Transcription mlx-whisper (%s)…", self.repo)
        result = mlx_whisper.transcribe(str(audio_path), path_or_hf_repo=self.repo, language=language)
        segments = [
            Segment(start=float(s["start"]), end=float(s["end"]), text=s["text"].strip())
            for s in result.get("segments", [])
            if s["text"].strip()
        ]
        lang = result.get("language", "unknown")
        logger.info("mlx-whisper : %s, %d segments", lang, len(segments))
        return TranscriptionResult(segments=segments, language=lang)
