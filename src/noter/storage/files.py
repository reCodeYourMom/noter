"""Organisation des fichiers audio et transcriptions."""
from __future__ import annotations

import re
from pathlib import Path

from noter.config import settings


def _slugify(text: str) -> str:
    """Transforme un titre en nom de dossier propre."""
    text = text.strip()[:50]
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s]+', '-', text)
    return text.strip('-') or "recording"


def get_call_dir(started_at: str, title: str | None = None) -> Path:
    """Retourne le dossier d'un call : 2026-03-03_14h30_Sprint-Planning/"""
    # started_at format ISO: 2026-03-03T14:30:45
    date_part = started_at[:10]       # 2026-03-03
    time_part = started_at[11:16]     # 14:30
    time_clean = time_part.replace(":", "h")  # 14h30

    folder_name = f"{date_part}_{time_clean}"
    if title:
        folder_name += f"_{_slugify(title)}"

    d = settings.data_dir / folder_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_transcript_path(started_at: str, title: str | None = None) -> Path:
    """Chemin du fichier transcript (.txt)."""
    return get_call_dir(started_at, title) / "transcript.txt"


def get_summary_path(started_at: str, title: str | None = None) -> Path:
    """Chemin du fichier résumé (.md)."""
    return get_call_dir(started_at, title) / "summary.md"


def get_pdf_path(started_at: str, title: str | None = None) -> Path:
    """Chemin du fichier PDF (.pdf)."""
    return get_call_dir(started_at, title) / "rapport.pdf"


def get_audio_path(started_at: str, title: str | None = None, ext: str = "wav") -> Path:
    """Chemin du fichier audio."""
    return get_call_dir(started_at, title) / f"audio.{ext}"


def save_transcript_file(started_at: str, title: str | None, segments: list[dict]) -> Path:
    """Sauvegarde le transcript en fichier texte lisible."""
    path = get_transcript_path(started_at, title)
    lines = []
    for seg in segments:
        time_str = f"{int(seg['start'] // 60):02d}:{int(seg['start'] % 60):02d}"
        speaker = seg.get("speaker") or "Speaker"
        lines.append(f"[{time_str}] {speaker}: {seg['text']}")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def save_summary_file(started_at: str, title: str | None, summary_md: str) -> Path:
    """Sauvegarde le résumé en Markdown."""
    path = get_summary_path(started_at, title)
    path.write_text(summary_md, encoding="utf-8")
    return path
