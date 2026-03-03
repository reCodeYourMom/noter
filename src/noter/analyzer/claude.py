"""Résumés structurés via Claude API."""
from __future__ import annotations

import json
import logging
import os

import anthropic
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from noter.storage.database import get_recording, get_segments, insert_summary
from noter.storage.files import save_summary_file, get_pdf_path
from noter.export.pdf import generate_pdf

logger = logging.getLogger(__name__)
console = Console()

SUMMARY_PROMPT = """Tu es un assistant expert en compte-rendus de réunion.
Analyse la transcription suivante et produis un compte-rendu structuré.

RÈGLES:
- Réponds dans la MÊME LANGUE que la transcription (français si FR, anglais si EN)
- Adapte la profondeur du résumé à la densité du contenu :
  - Call court ou peu dense → résumé bref, quelques points clés
  - Call long et dense → résumé exhaustif, tous les sujets couverts, points clés détaillés
- Ne perds AUCUNE information importante — mieux vaut un résumé long et complet qu'un résumé court qui oublie des choses
- Si des noms/prénoms sont mentionnés, associe-les aux actions
- Conserve les termes techniques, noms de produits, chiffres tels quels
- Si une section est vide (aucune décision, aucune action), mets une liste vide []
- Les "key_points" sont les faits saillants partageables : ce qu'on enverrait à quelqu'un qui n'était pas au call pour qu'il soit au courant rapidement

Produis EXACTEMENT ce format JSON:
{{
    "tldr": "Résumé en quelques phrases — adapte la longueur au contenu",
    "key_points": ["Point saillant 1", "Point saillant 2", ...],
    "decisions": ["Décision prise 1", "Décision prise 2", ...],
    "actions": ["Prénom: fait quoi (deadline si mentionnée)", ...]
}}

--- TRANSCRIPTION ({duration}) ---
{transcript}
"""

MODEL = "claude-sonnet-4-20250514"


def _get_client() -> anthropic.Anthropic:
    """Retourne un client Anthropic configuré."""
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("NOTER_ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY non configurée. "
            "Ajoute-la dans ton .env ou exporte-la: export ANTHROPIC_API_KEY=sk-ant-..."
        )
    return anthropic.Anthropic(api_key=api_key)


def _format_transcript(segments: list[dict]) -> str:
    """Formate les segments en texte lisible pour le prompt."""
    lines = []
    for seg in segments:
        time_str = f"{int(seg['start'] // 60):02d}:{int(seg['start'] % 60):02d}"
        speaker = seg.get("speaker") or "Speaker"
        lines.append(f"[{time_str}] {speaker}: {seg['text']}")
    return "\n".join(lines)


def summarize_recording(recording_id: str):
    """Génère un résumé IA d'un enregistrement."""
    rec = get_recording(recording_id)
    if not rec:
        console.print(f"[red]Enregistrement '{recording_id}' introuvable.[/red]")
        return

    segments = get_segments(rec["id"])
    if not segments:
        console.print(f"[yellow]Aucun segment de transcription trouvé. Lance d'abord: noter transcribe {recording_id}[/yellow]")
        return

    transcript_text = _format_transcript(segments)

    # Durée formatée pour le prompt
    dur_s = rec.get("duration_s") or 0
    dur_str = f"{int(dur_s // 60)}min {int(dur_s % 60):02d}s"

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"Analyse Claude ({MODEL})...", total=None)

        client = _get_client()
        response = client.messages.create(
            model=MODEL,
            max_tokens=8192,
            messages=[{
                "role": "user",
                "content": SUMMARY_PROMPT.format(transcript=transcript_text, duration=dur_str),
            }],
        )

        progress.update(task, description="Analyse terminée")

    raw_text = response.content[0].text

    # Parse JSON
    try:
        json_text = raw_text
        if "```json" in json_text:
            json_text = json_text.split("```json")[1].split("```")[0]
        elif "```" in json_text:
            json_text = json_text.split("```")[1].split("```")[0]
        data = json.loads(json_text.strip())
    except (json.JSONDecodeError, IndexError):
        logger.warning("Impossible de parser le JSON Claude, fallback texte brut")
        data = {
            "tldr": raw_text[:500],
            "key_points": [],
            "decisions": [],
            "actions": [],
        }

    # Extraire
    tldr = data.get("tldr", "")
    key_points = data.get("key_points", [])
    decisions = data.get("decisions", [])
    actions = data.get("actions", [])

    # Sauvegarder en DB (compat schéma existant : followups → key_points, full_summary → "")
    key_points_str = "\n".join(f"- {p}" for p in key_points)
    decisions_str = "\n".join(f"- {d}" for d in decisions)
    actions_str = "\n".join(f"- [ ] {a}" for a in actions)
    insert_summary(rec["id"], MODEL, tldr, decisions_str, actions_str, key_points_str, "")

    # --- Construire le Markdown ---
    date_str = rec["started_at"][:10] if rec["started_at"] else "unknown"
    raw_date = rec.get("started_at", "")
    nice_date = raw_date[:16].replace("T", " ") if raw_date else "?"
    duration_min = int((rec.get("duration_s") or 0) // 60)
    duration_sec = int((rec.get("duration_s") or 0) % 60)
    lang = (rec.get("language") or "?").upper()

    parts = []
    parts.append(f"# {rec.get('title') or 'Enregistrement'}")
    parts.append(f"> {nice_date} | {duration_min}min {duration_sec:02d}s | {lang}\n")

    parts.append(f"## TL;DR\n{tldr}\n")

    if key_points:
        parts.append("## Points clés")
        for p in key_points:
            parts.append(f"- {p}")
        parts.append("")

    if decisions:
        parts.append("## Décisions")
        for d in decisions:
            parts.append(f"- {d}")
        parts.append("")

    if actions:
        parts.append("## Actions")
        for a in actions:
            parts.append(f"- [ ] {a}")
        parts.append("")

    # Transcript complet en bas
    parts.append("---\n")
    parts.append("<details><summary>Transcript complet</summary>\n")
    parts.append(f"```")
    parts.append(transcript_text)
    parts.append(f"```")
    parts.append("</details>")

    summary_md = "\n".join(parts)
    started_at = rec.get("started_at", "")
    rec_title = rec.get("title")
    summary_path = save_summary_file(started_at, rec_title, summary_md)

    # --- Générer le PDF ---
    pdf_path = get_pdf_path(started_at, rec_title)
    try:
        generate_pdf(
            output_path=pdf_path,
            title=rec.get("title") or "Enregistrement",
            date_str=nice_date,
            duration_str=f"{duration_min}min {duration_sec:02d}s",
            language=lang,
            tldr=tldr,
            key_points=key_points,
            decisions=decisions,
            actions=actions,
            transcript=transcript_text,
        )
        logger.info(f"PDF généré: {pdf_path}")
    except Exception as e:
        logger.warning(f"Erreur génération PDF: {e}")
        pdf_path = None

    # Afficher dans la console (sans le transcript pour pas noyer)
    display_parts = parts[:parts.index("---\n")]
    console.print(Panel(Markdown("\n".join(display_parts)), title="Résumé", border_style="green"))
    console.print(f"\n[dim]Markdown : {summary_path}[/dim]")
    if pdf_path:
        console.print(f"[dim]PDF      : {pdf_path}[/dim]")
