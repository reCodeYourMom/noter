"""Organisation des fichiers sur disque : un dossier par enregistrement.

~/Noter/recordings/2026-03-03_14h30_Sprint-Planning/
    audio.wav        audio final
    transcript.md    transcript horodaté
    summary.md       compte-rendu
    rapport.pdf      export PDF
    meta.json        métadonnées (portable, lisible par n'importe quel script)
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from noter.models import Recording, Segment, Summary, format_timestamp

AUDIO_NAME = "audio.wav"
TRANSCRIPT_NAME = "transcript.md"
SUMMARY_NAME = "summary.md"
PDF_NAME = "rapport.pdf"
META_NAME = "meta.json"


def slugify(text: str, max_len: int = 50) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip()[:max_len]
    text = re.sub(r"[\s_]+", "-", text)
    return text.strip("-") or "recording"


def recording_dir(data_dir: Path, started_at: datetime, title: str | None = None, create: bool = True) -> Path:
    name = started_at.strftime("%Y-%m-%d_%Hh%M")
    if title:
        name += f"_{slugify(title)}"
    d = data_dir / name
    if d.exists() and create:
        # Collision (deux enregistrements à la même minute) : suffixe
        i = 2
        while (data_dir / f"{name}-{i}").exists():
            i += 1
        d = data_dir / f"{name}-{i}"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def transcript_markdown(rec: Recording, segments: list[Segment]) -> str:
    lines = [f"# Transcript — {rec.display_title}", "", f"> {rec.started_at:%Y-%m-%d %H:%M} · {rec.duration_text} · {(rec.language or '?').upper()}", ""]
    for s in segments:
        speaker = f"**{s.speaker}** : " if s.speaker else ""
        lines.append(f"`{format_timestamp(s.start)}` {speaker}{s.text}")
    return "\n".join(lines) + "\n"


def transcript_plain(segments: list[Segment]) -> str:
    """Format compact pour le prompt Claude."""
    out = []
    for s in segments:
        speaker = s.speaker or "Speaker"
        out.append(f"[{format_timestamp(s.start)}] {speaker}: {s.text}")
    return "\n".join(out)


def summary_markdown(rec: Recording, summary: Summary, segments: list[Segment] | None = None) -> str:
    parts = [f"# {rec.display_title}", f"> {rec.started_at:%Y-%m-%d %H:%M} · {rec.duration_text} · {(rec.language or '?').upper()}"]
    if rec.project or rec.tags:
        meta = []
        if rec.project:
            meta.append(f"Projet : {rec.project}")
        if rec.tags:
            meta.append("Tags : " + ", ".join(rec.tags))
        parts.append("> " + " · ".join(meta))
    parts += ["", "## TL;DR", summary.tldr, ""]
    if summary.key_points:
        parts.append("## Points clés")
        parts += [f"- {p}" for p in summary.key_points]
        parts.append("")
    if summary.decisions:
        parts.append("## Décisions")
        parts += [f"- {d}" for d in summary.decisions]
        parts.append("")
    if summary.actions:
        parts.append("## Actions")
        parts += [f"- [{'x' if a.done else ' '}] {a.display}" for a in summary.actions]
        parts.append("")
    if segments:
        parts += ["---", "", "<details><summary>Transcript complet</summary>", "", "```", transcript_plain(segments), "```", "", "</details>", ""]
    return "\n".join(parts)


def write_meta(rec: Recording, summary: Summary | None = None) -> Path:
    data = {
        "id": rec.id,
        "title": rec.title,
        "source": str(rec.source),
        "status": str(rec.status),
        "started_at": rec.started_at.isoformat(timespec="seconds"),
        "ended_at": rec.ended_at.isoformat(timespec="seconds") if rec.ended_at else None,
        "duration_s": rec.duration_s,
        "language": rec.language,
        "project": rec.project,
        "tags": rec.tags,
        "notes": rec.notes,
        "audio": str(rec.audio_path.name),
        "summary_model": summary.model if summary else None,
    }
    path = rec.dir_path / META_NAME
    rec.dir_path.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
