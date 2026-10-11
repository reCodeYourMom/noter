"""Factory : choisit le moteur Whisper selon la plateforme et la config."""
from __future__ import annotations

import logging

from noter.config import Settings
from noter.transcription.base import TranscriptionEngine

logger = logging.getLogger(__name__)


def get_engine(settings: Settings) -> TranscriptionEngine:
    if settings.is_apple_silicon:
        try:
            from noter.transcription.mlx_whisper import MlxWhisperEngine

            return MlxWhisperEngine(settings.whisper_model)
        except ImportError:
            logger.info("mlx-whisper non installé — fallback faster-whisper")

    from noter.transcription.faster_whisper import FasterWhisperEngine

    return FasterWhisperEngine(settings.whisper_model, apple_silicon=settings.is_apple_silicon)
