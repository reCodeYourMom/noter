"""CLI Noter."""
from __future__ import annotations

import signal
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from noter.models import RecordingStatus, format_timestamp

app = typer.Typer(name="noter", help="Enregistre, transcrit et résume tes calls — 100 % local.", no_args_is_help=True)
console = Console()

STATUS_STYLE = {
    "recording": "red", "recorded": "yellow", "transcribing": "cyan", "transcribed": "cyan",
    "summarizing": "cyan", "done": "green", "failed": "red bold",
}


def _service():
    from noter.config import load_settings
    from noter.logging_setup import setup_logging
    from noter.service import Service

    s = load_settings()
    setup_logging(s.log_path)
    return Service(s)


def _status(s: RecordingStatus) -> str:
    return f"[{STATUS_STYLE.get(str(s), '')}]{s}[/]"


# ─── Enregistrement ─────────────────────────────────────────────────


@app.command()
def record(
    mic_only: bool = typer.Option(False, "--mic-only", "-m", help="Micro seul (réunion physique)"),
    title: str = typer.Option(None, "--title", "-t"),
    project: str = typer.Option(None, "--project", "-p"),
    tag: list[str] = typer.Option(None, "--tag"),
    no_process: bool = typer.Option(False, "--no-process", help="N'enchaîne pas transcription + résumé"),
):
    """Enregistre jusqu'à Ctrl+C, puis transcrit et résume."""
    svc = _service()
    rec = svc.start_recording(with_system_audio=not mic_only, title=title, project=project, tags=tag or [])
    console.print(f"[green bold]● REC[/] {rec.display_title}  [dim]{rec.short_id} · {rec.source}[/]")
    console.print("[dim]Ctrl+C pour arrêter[/]")

    stop = {"flag": False}
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__("flag", True))
    try:
        while not stop["flag"] and svc.is_recording:
            lv = svc.recorder.levels if svc.recorder else {}
            bars = "  ".join(f"{k} {'█' * min(20, int(v * 120))}" for k, v in lv.items())
            console.print(f"\r  {format_timestamp(svc.recorder.elapsed if svc.recorder else 0)}  {bars:<60}", end="")
            time.sleep(0.25)
    finally:
        console.print()
        rec = svc.stop_recording(enqueue=not no_process)
    console.print(f"[green]Enregistré[/] {rec.duration_text} → {rec.dir_path}")
    if not no_process:
        console.print("[bold]Transcription + résumé…[/]")
        svc.jobs.run_pending()
        _print_summary(svc, rec.id)
    svc.stop()


@app.command("import")
def import_cmd(
    path: Path = typer.Argument(..., exists=True, help="Fichier audio (wav, m4a, mp3, …)"),
    title: str = typer.Option(None, "--title", "-t"),
    project: str = typer.Option(None, "--project", "-p"),
    tag: list[str] = typer.Option(None, "--tag"),
    no_process: bool = typer.Option(False, "--no-process"),
):
    """Importe un fichier audio existant et le traite."""
    svc = _service()
    rec = svc.import_file(path, title=title, project=project, tags=tag or [], enqueue=not no_process)
    console.print(f"[green]Importé[/] {rec.display_title} ({rec.duration_text}) → {rec.dir_path}")
    if not no_process:
        svc.jobs.run_pending()
        _print_summary(svc, rec.id)
    svc.stop()


@app.command()
def devices():
    """Liste les périphériques audio d'entrée."""
    from noter.audio.devices import default_mic, find_blackhole, input_devices

    mic, bh = default_mic(), find_blackhole()
    table = Table(title="Entrées audio")
    for col in ("Index", "Nom", "Canaux", "Taux", "Rôle"):
        table.add_column(col)
    for d in input_devices():
        role = "[green]BlackHole (système)[/]" if d.is_blackhole else ("[blue]Micro par défaut[/]" if mic and d.index == mic.index else "")
        table.add_row(str(d.index), d.name, str(d.input_channels), f"{d.default_samplerate:.0f}", role)
    console.print(table)
    if not bh:
        console.print("\n[yellow]BlackHole absent[/] : brew install blackhole-2ch, puis crée un périphérique multi-sortie.")


# ─── Consultation ───────────────────────────────────────────────────


@app.command("list")
def list_cmd(
    limit: int = typer.Option(20, "--limit", "-n"),
    status: str = typer.Option(None, "--status", "-s"),
    project: str = typer.Option(None, "--project", "-p"),
    tag: str = typer.Option(None, "--tag"),
):
    """Liste les enregistrements."""
    svc = _service()
    recs = svc.repo.list_recordings(limit=limit, status=RecordingStatus(status) if status else None, project=project, tag=tag)
    if not recs:
        console.print("[dim]Aucun enregistrement.[/]")
        return
    table = Table()
    for col, kw in (("ID", {"style": "cyan"}), ("Date", {}), ("Titre", {}), ("Durée", {"justify": "right"}), ("Statut", {}), ("Projet", {}), ("Tags", {})):
        table.add_column(col, **kw)
    for r in recs:
        table.add_row(r.short_id, f"{r.started_at:%d/%m %H:%M}", r.display_title, r.duration_text, _status(r.status), r.project or "", ", ".join(r.tags))
    console.print(table)


@app.command()
def show(recording_id: str, transcript: bool = typer.Option(False, "--transcript", "-T", help="Affiche aussi le transcript")):
    """Affiche le résumé (et le transcript) d'un enregistrement."""
    svc = _service()
    rec = svc.repo.get_recording(recording_id)
    if rec is None:
        console.print(f"[red]'{recording_id}' introuvable (ou préfixe ambigu).[/]")
        raise typer.Exit(1)
    console.print(Panel(
        f"[bold]{rec.display_title}[/]\n{rec.started_at:%d/%m/%Y %H:%M} · {rec.duration_text} · {rec.source} · {_status(rec.status)}"
        + (f"\nProjet : {rec.project}" if rec.project else "") + (f"\nTags : {', '.join(rec.tags)}" if rec.tags else "")
        + f"\n[dim]{rec.dir_path}[/]",
        title=rec.short_id,
    ))
    _print_summary(svc, rec.id)
    if transcript:
        for s in svc.repo.get_segments(rec.id):
            console.print(f"  [dim]{format_timestamp(s.start)}[/] [cyan]{s.speaker or ''}[/] {s.text}")


@app.command()
def search(query: str, limit: int = typer.Option(20, "--limit", "-n")):
    """Recherche plein texte dans transcripts, résumés et titres."""
    svc = _service()
    hits = svc.repo.search(query, limit=limit)
    if not hits:
        console.print(f"[dim]Aucun résultat pour « {query} ».[/]")
        return
    table = Table(title=f"Résultats pour « {query} »")
    table.add_column("ID", style="cyan")
    table.add_column("Enregistrement")
    table.add_column("Où")
    table.add_column("Extrait")
    for h in hits:
        where = h.kind + (f" @ {format_timestamp(h.start_s)}" if h.start_s is not None else "")
        table.add_row(h.recording.short_id, h.recording.display_title, where, h.snippet.replace("[", "[bold red]").replace("]", "[/bold red]"))
    console.print(table)


@app.command()
def edit(
    recording_id: str,
    title: str = typer.Option(None, "--title", "-t"),
    project: str = typer.Option(None, "--project", "-p"),
    tag: list[str] = typer.Option(None, "--tag", help="Remplace les tags (répétable)"),
    notes: str = typer.Option(None, "--notes"),
):
    """Modifie titre, projet, tags ou notes."""
    svc = _service()
    rec = svc.repo.get_recording(recording_id)
    if rec is None:
        raise typer.Exit(1)
    fields = {k: v for k, v in {"title": title, "project": project, "notes": notes}.items() if v is not None}
    if tag is not None and len(tag) > 0:
        fields["tags"] = tag
    rec = svc.update_metadata(rec.id, **fields)
    console.print(f"[green]OK[/] {rec.display_title}")


@app.command()
def delete(recording_id: str, keep_files: bool = typer.Option(False, "--keep-files")):
    """Supprime un enregistrement (et ses fichiers)."""
    svc = _service()
    rec = svc.repo.get_recording(recording_id)
    if rec is None:
        raise typer.Exit(1)
    if not typer.confirm(f"Supprimer « {rec.display_title} » ?"):
        raise typer.Exit()
    svc.delete_recording(rec.id, delete_files=not keep_files)
    console.print("[green]Supprimé.[/]")


# ─── Traitement ─────────────────────────────────────────────────────


@app.command()
def process(recording_id: str, summarize_only: bool = typer.Option(False, "--summary", help="Résumé seul (transcript existant)")):
    """(Re)lance le traitement d'un enregistrement."""
    from noter.models import JobKind

    svc = _service()
    rec = svc.repo.get_recording(recording_id)
    if rec is None:
        raise typer.Exit(1)
    svc.jobs.enqueue(rec.id, JobKind.SUMMARIZE if summarize_only else JobKind.TRANSCRIBE)
    svc.jobs.run_pending()
    _print_summary(svc, rec.id)
    svc.stop()


@app.command()
def retry(recording_id: str = typer.Argument(None, help="ID, ou vide pour tous les échecs")):
    """Relance les jobs en échec."""
    svc = _service()
    if recording_id:
        n = svc.jobs.retry(recording_id)
    else:
        n = sum(svc.jobs.retry(r.id) for r in svc.repo.list_recordings(limit=1000, status=RecordingStatus.FAILED))
    console.print(f"{n} job(s) relancé(s)")
    svc.jobs.run_pending()
    svc.stop()


@app.command()
def jobs(limit: int = typer.Option(20, "--limit", "-n")):
    """Historique des jobs."""
    svc = _service()
    table = Table()
    for col in ("#", "Enreg.", "Type", "Statut", "Essais", "Erreur"):
        table.add_column(col)
    for j in svc.repo.list_jobs(limit=limit):
        table.add_row(str(j.id), j.recording_id[:8], j.kind, j.status, f"{j.attempts}/{j.max_attempts}", (j.error or "")[:60])
    console.print(table)


@app.command()
def worker():
    """Lance le worker de jobs en continu (utile sans l'app menu bar)."""
    svc = _service()
    svc.start()
    console.print("[green]Worker démarré[/] — Ctrl+C pour arrêter")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        svc.stop()


# ─── Service / diagnostic ───────────────────────────────────────────

service_app = typer.Typer(help="Lancement automatique au login (macOS).")
app.add_typer(service_app, name="service")


@service_app.command("install")
def service_install():
    from noter.config import load_settings
    from noter.launchd import install

    p = install(load_settings().log_path)
    console.print(f"[green]LaunchAgent installé[/] : {p}")


@service_app.command("uninstall")
def service_uninstall():
    from noter.launchd import uninstall

    console.print("[green]Désinstallé[/]" if uninstall() else "[dim]Rien à désinstaller[/]")


app_bundle = typer.Typer(help="Bundle Noter.app dans ~/Applications (icône et nom dans le Dock).")
app.add_typer(app_bundle, name="app")


@app_bundle.command("install")
def app_install():
    from noter import macapp
    from noter.launchd import is_installed

    p = macapp.install()
    console.print(f"[green]Noter.app installé[/] : {p}")
    if not macapp.is_native():
        console.print(
            "[yellow]Aucun compilateur C trouvé : lanceur de secours installé, l'accès au micro risque d'être refusé.[/]\n"
            "Installe les outils développeur (xcode-select --install) puis relance `noter app install`."
        )
    if is_installed():
        from noter.config import load_settings
        from noter.launchd import install

        install(load_settings().log_path)
        console.print("[dim]LaunchAgent mis à jour pour lancer Noter.app[/]")


@app_bundle.command("uninstall")
def app_uninstall():
    from noter import macapp

    console.print("[green]Noter.app supprimé[/]" if macapp.uninstall() else "[dim]Rien à supprimer[/]")


@app.command()
def doctor():
    """Vérifie la configuration."""
    from noter.config import load_settings

    s = load_settings()
    table = Table(show_header=False)
    table.add_column("k", style="dim")
    table.add_column("v")
    table.add_row("Données", str(s.data_dir))
    table.add_row("Base", str(s.db_path))
    table.add_row("Logs", str(s.log_path))
    table.add_row("Whisper", s.whisper_model + (" (mlx)" if s.is_apple_silicon else " (faster-whisper)"))
    table.add_row("Claude", f"{s.claude_model} · effort {s.claude_effort}")
    table.add_row("Clé API", "[green]présente[/]" if s.anthropic_api_key else "[red]absente[/] (ANTHROPIC_API_KEY dans ~/Noter/.env)")
    try:
        from noter.audio.devices import default_mic, find_blackhole

        table.add_row("Micro", (default_mic() or AudioDeviceNone()).name)
        table.add_row("BlackHole", "[green]oui[/]" if find_blackhole() else "[yellow]non[/]")
    except Exception as e:  # noqa: BLE001
        table.add_row("Audio", f"[red]{e}[/]")
    svc = _service()
    table.add_row("Enregistrements", str(svc.repo.count_recordings()))
    table.add_row("Jobs en attente", str(svc.repo.pending_job_count()))
    console.print(table)


class AudioDeviceNone:
    name = "[red]aucun[/]"


def _print_summary(svc, recording_id: str) -> None:
    rec = svc.repo.get_recording(recording_id)
    summary = svc.repo.get_summary(recording_id)
    if rec is None:
        return
    if summary is None:
        console.print(f"[dim]Pas de résumé (statut {rec.status}).[/]")
        jobs_ = svc.repo.list_jobs(recording_id=rec.id, limit=1)
        if jobs_ and jobs_[0].error:
            console.print(f"[red]{jobs_[0].error}[/]")
        return
    from noter.storage.files import summary_markdown

    console.print(Panel(Markdown(summary_markdown(rec, summary)), title="Résumé", border_style="green"))
    console.print(f"[dim]{rec.dir_path}[/]")


if __name__ == "__main__":
    app()
