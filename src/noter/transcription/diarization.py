"""Diarisation (qui parle quand) via pyannote-audio — optionnelle.

Nécessite `pip install 'noter[diarize]'` et un token Hugging Face (HF_TOKEN)
avec acceptation des conditions de pyannote/speaker-diarization-3.1.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from noter.models import Segment

logger = logging.getLogger(__name__)
_pipeline = None


def _get_pipeline():
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError("HF_TOKEN requis pour la diarisation (https://huggingface.co/settings/tokens)")
    from pyannote.audio import Pipeline

    logger.info("Chargement pyannote speaker-diarization-3.1…")
    _pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=token)
    if _pipeline is None:
        raise RuntimeError("Pipeline pyannote indisponible — conditions d'utilisation acceptées sur Hugging Face ?")
    return _pipeline


def diarize(audio_path: Path) -> list[dict]:
    pipeline = _get_pipeline()
    out = pipeline(str(audio_path))
    turns = [{"speaker": spk, "start": t.start, "end": t.end} for t, _, spk in out.itertracks(yield_label=True)]
    logger.info("Diarisation : %d tours, %d speakers", len(turns), len({t['speaker'] for t in turns}))
    return turns


def assign_speakers(segments: list[Segment], turns: list[dict]) -> list[Segment]:
    """Attribue à chaque segment le speaker qui le recouvre le plus."""
    for seg in segments:
        best, best_overlap = None, 0.0
        for t in turns:
            overlap = max(0.0, min(seg.end, t["end"]) - max(seg.start, t["start"]))
            if overlap > best_overlap:
                best, best_overlap = t["speaker"], overlap
        seg.speaker = best
    return segments
