"""Speaker diarization via pyannote-audio."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Cache le pipeline pyannote (lourd à charger)
_pipeline = None


def _patch_hf_hub_compat():
    """Patch use_auth_token -> token pour compat huggingface_hub >= 1.0."""
    import huggingface_hub
    _orig = huggingface_hub.hf_hub_download

    def _compat(*args, **kwargs):
        if "use_auth_token" in kwargs:
            kwargs["token"] = kwargs.pop("use_auth_token")
        return _orig(*args, **kwargs)

    huggingface_hub.hf_hub_download = _compat

    # Patch aussi dans le namespace de pyannote (importé via 'from ... import')
    try:
        import pyannote.audio.core.pipeline
        pyannote.audio.core.pipeline.hf_hub_download = _compat
    except (ImportError, AttributeError):
        pass


def _get_pipeline():
    """Charge le pipeline de diarisation pyannote."""
    global _pipeline
    if _pipeline is not None:
        return _pipeline

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        raise RuntimeError(
            "HF_TOKEN requis pour pyannote-audio. "
            "Crée un token sur https://huggingface.co/settings/tokens "
            "et accepte les conditions sur https://huggingface.co/pyannote/speaker-diarization-3.1"
        )

    _patch_hf_hub_compat()

    from pyannote.audio import Pipeline

    logger.info("Chargement du pipeline pyannote-audio...")
    _pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=hf_token,
    )

    if _pipeline is None:
        raise RuntimeError(
            "Impossible de charger le pipeline pyannote. "
            "Vérifie que tu as accepté les conditions sur "
            "https://huggingface.co/pyannote/speaker-diarization-3.1"
        )

    logger.info("Pipeline pyannote chargé")
    return _pipeline


def diarize(audio_path: str) -> list[dict]:
    """
    Identifie les speakers dans un fichier audio.

    Retourne une liste de dict:
    [{"speaker": "SPEAKER_00", "start": 0.5, "end": 3.2}, ...]
    """
    pipeline = _get_pipeline()
    diarization = pipeline(audio_path)

    segments = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append({
            "speaker": speaker,
            "start": turn.start,
            "end": turn.end,
        })

    logger.info(f"Diarisation: {len(segments)} segments, {len(set(s['speaker'] for s in segments))} speakers")
    return segments
