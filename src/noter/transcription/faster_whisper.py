"""Implémentation faster-whisper (Intel + fallback Apple Silicon)."""
from __future__ import annotations

import logging
from functools import lru_cache

from faster_whisper import WhisperModel

from noter.config import settings
from noter.transcription.engine import Segment

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_model() -> WhisperModel:
    """Charge le modèle Whisper une seule fois."""
    model_name = settings.whisper_model
    logger.info(f"Chargement faster-whisper '{model_name}'...")

    # Apple Silicon : float32 sur CPU, Intel : int8
    if settings.is_apple_silicon:
        compute_type = "float32"
    else:
        compute_type = "int8"

    model = WhisperModel(
        model_name,
        device="cpu",
        compute_type=compute_type,
    )
    logger.info("Modèle faster-whisper chargé")
    return model


class FasterWhisperEngine:
    """Transcription via faster-whisper."""

    def transcribe(self, audio_path: str) -> tuple[list[Segment], str]:
        """Transcrit un fichier audio. Retourne (segments, langue)."""
        model = _get_model()

        segments_gen, info = model.transcribe(
            audio_path,
            beam_size=5,
            language=None,  # Auto-detect FR/EN
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=200,
            ),
            word_timestamps=True,
        )

        segments = []
        for seg in segments_gen:
            segments.append(Segment(
                start=seg.start,
                end=seg.end,
                text=seg.text.strip(),
            ))

        logger.info(f"Transcription: {info.language}, {info.duration:.0f}s, {len(segments)} segments")
        return segments, info.language
