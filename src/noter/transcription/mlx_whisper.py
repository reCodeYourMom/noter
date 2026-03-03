"""Implémentation mlx-whisper (Apple Silicon natif — GPU Metal)."""
from __future__ import annotations

import logging

from noter.config import settings
from noter.transcription.engine import Segment

logger = logging.getLogger(__name__)

# Mapping des noms de modèles vers les repos HuggingFace pour mlx
MODEL_MAP = {
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "tiny": "mlx-community/whisper-tiny-mlx",
}


class MlxWhisperEngine:
    """Transcription via mlx-whisper (Apple Silicon GPU)."""

    def __init__(self):
        try:
            import mlx_whisper  # noqa: F401
        except ImportError:
            raise ImportError(
                "mlx-whisper non installé. Installe avec: pip install 'noter[mlx]'"
            )

    def transcribe(self, audio_path: str) -> tuple[list[Segment], str]:
        """Transcrit un fichier audio via mlx-whisper."""
        import mlx_whisper

        model_name = settings.whisper_model
        mlx_model = MODEL_MAP.get(model_name, MODEL_MAP["large-v3"])

        logger.info(f"Transcription mlx-whisper avec {mlx_model}...")

        result = mlx_whisper.transcribe(
            audio_path,
            path_or_hf_repo=mlx_model,
            word_timestamps=True,
        )

        language = result.get("language", "unknown")
        segments = []

        for seg in result.get("segments", []):
            segments.append(Segment(
                start=seg["start"],
                end=seg["end"],
                text=seg["text"].strip(),
            ))

        logger.info(f"Transcription mlx: {language}, {len(segments)} segments")
        return segments, language
