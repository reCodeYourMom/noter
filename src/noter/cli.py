"""CLI principal Noter."""
from __future__ import annotations

from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console

# Charger le .env AVANT tout import de config
load_dotenv(Path(__file__).parent.parent.parent / ".env")

app = typer.Typer(
    name="noter",
    help="Plaud maison — enregistre, transcrit et résume tes calls.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def record(
    mic_only: bool = typer.Option(False, "--mic-only", "-m", help="Micro seul (réunion physique)"),
    title: str = typer.Option(None, "--title", "-t", help="Titre de l'enregistrement"),
):
    """Lance un enregistrement audio."""
    from noter.audio.recorder import start_recording

    mode = "mic_only" if mic_only else "system+mic"
    start_recording(mode=mode, title=title)


@app.command()
def devices():
    """Liste les devices audio disponibles."""
    from noter.audio.devices import list_devices

    list_devices()


@app.command()
def transcribe(
    recording_id: str = typer.Argument(help="ID de l'enregistrement à transcrire"),
):
    """Transcrit un enregistrement existant."""
    from noter.transcription.engine import transcribe_recording

    transcribe_recording(recording_id)


@app.command()
def summary(
    recording_id: str = typer.Argument(help="ID de l'enregistrement"),
):
    """Génère un résumé IA d'un enregistrement."""
    from noter.analyzer.claude import summarize_recording

    summarize_recording(recording_id)


@app.command(name="list")
def list_recordings(
    limit: int = typer.Option(20, "--limit", "-n", help="Nombre d'enregistrements"),
):
    """Liste les enregistrements."""
    from noter.storage.database import get_db
    from rich.table import Table

    db = get_db()
    rows = db.execute(
        "SELECT id, title, mode, started_at, duration_s, language FROM recordings ORDER BY started_at DESC LIMIT ?",
        (limit,),
    ).fetchall()

    if not rows:
        console.print("[dim]Aucun enregistrement.[/dim]")
        return

    table = Table(title="Enregistrements")
    table.add_column("ID", style="cyan", max_width=8)
    table.add_column("Titre")
    table.add_column("Mode")
    table.add_column("Date")
    table.add_column("Durée", justify="right")
    table.add_column("Langue")

    for row in rows:
        rid, title, mode, started, duration, lang = row
        dur_str = f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else "-"
        table.add_row(rid[:8], title or "-", mode, started or "-", dur_str, lang or "-")

    console.print(table)


@app.command()
def search(
    query: str = typer.Argument(help="Texte à rechercher"),
    limit: int = typer.Option(10, "--limit", "-n"),
):
    """Recherche dans les transcriptions (full-text)."""
    from noter.storage.database import get_db
    from rich.table import Table

    db = get_db()
    rows = db.execute(
        """
        SELECT s.recording_id, s.speaker, s.text, s.start_time,
               highlight(transcripts_fts, 2, '[bold red]', '[/bold red]') as highlighted
        FROM transcripts_fts
        JOIN segments s ON transcripts_fts.rowid = s.id
        WHERE transcripts_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()

    if not rows:
        console.print(f"[dim]Aucun résultat pour '{query}'.[/dim]")
        return

    table = Table(title=f"Résultats pour '{query}'")
    table.add_column("Recording", style="cyan", max_width=8)
    table.add_column("Speaker")
    table.add_column("Time", justify="right")
    table.add_column("Texte")

    for rec_id, speaker, text, start, highlighted in rows:
        time_str = f"{int(start // 60)}:{int(start % 60):02d}"
        table.add_row(rec_id[:8], speaker or "-", time_str, highlighted)

    console.print(table)


@app.command()
def show(
    recording_id: str = typer.Argument(help="ID de l'enregistrement"),
):
    """Affiche le transcript et le résumé d'un enregistrement."""
    from noter.storage.database import get_db
    from rich.markdown import Markdown
    from rich.panel import Panel

    db = get_db()

    # Recording info
    rec = db.execute("SELECT * FROM recordings WHERE id LIKE ?", (f"{recording_id}%",)).fetchone()
    if not rec:
        console.print(f"[red]Enregistrement '{recording_id}' introuvable.[/red]")
        raise typer.Exit(1)

    full_id = rec[0]
    console.print(Panel(f"[bold]{rec[1] or 'Sans titre'}[/bold]\n{rec[3]} | {rec[2]} | {rec[7] or '?'}", title="Recording"))

    # Segments
    segments = db.execute(
        "SELECT speaker, start_time, end_time, text FROM segments WHERE recording_id = ? ORDER BY start_time",
        (full_id,),
    ).fetchall()

    if segments:
        console.print("\n[bold]Transcript[/bold]")
        for speaker, start, end, text in segments:
            time_str = f"{int(start // 60)}:{int(start % 60):02d}"
            console.print(f"  [dim]{time_str}[/dim] [cyan]{speaker or '?'}[/cyan]: {text}")

    # Summary
    summary_row = db.execute(
        "SELECT tldr, decisions, action_items, followups, full_summary FROM summaries WHERE recording_id = ?",
        (full_id,),
    ).fetchone()

    if summary_row:
        console.print("\n")
        md = f"## TL;DR\n{summary_row[0]}\n\n## Décisions\n{summary_row[1]}\n\n## Action Items\n{summary_row[2]}\n\n## Follow-ups\n{summary_row[3]}\n\n## Résumé détaillé\n{summary_row[4]}"
        console.print(Panel(Markdown(md), title="Résumé IA"))


@app.command()
def serve():
    """Lance le serveur local pour recevoir les enregistrements iPhone."""
    import uvicorn
    from noter.config import settings

    console.print(f"[green]Serveur Noter démarré sur http://{settings.server_host}:{settings.server_port}[/green]")
    console.print("[dim]En attente d'enregistrements iPhone...[/dim]")
    uvicorn.run("noter.server.api:api", host=settings.server_host, port=settings.server_port)


if __name__ == "__main__":
    app()
