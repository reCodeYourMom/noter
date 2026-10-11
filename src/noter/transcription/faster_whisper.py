"""faster-whisper (CPU, Intel ou fallback Apple Silicon)."""
from __future__ import annotations

import logging
from pathlib import Path

from noter.models import Segment
from noter.transcription.base import TranscriptionResult

logger = logging.getLogger(__name__)


class FasterWhisperEngine:
    name = "faster-whisper"

    def __init__(self, model_name: str, apple_silicon: bool = False):
        self.model_name = model_name
        self.compute_type = "float32" if apple_silicon else "int8"
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            logger.info("Chargement faster-whisper '%s' (%s)…", self.model_name, self.compute_type)
            self._model = WhisperModel(self.model_name, device="cpu", compute_type=self.compute_type)
        return self._model

    def transcribe(self, audio_path: Path, language: str | None = None) -> TranscriptionResult:
        model = self._load()
        segments_gen, info = model.transcribe(
            str(audio_path),
            beam_size=5,
            language=language,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 200},
        )
        segments = [Segment(start=s.start, end=s.end, text=s.text.strip()) for s in segments_gen if s.text.strip()]
        logger.info("faster-whisper : %s, %d segments", info.language, len(segments))
        return TranscriptionResult(segments=segments, language=info.language)
