"""Serveur MCP de Noter : la bibliothèque de calls et les boards de tâches, côté Claude.

Lancé par Claude Desktop / Claude Code en stdio (`noter mcp`). Il lit et écrit la même base SQLite que
l'app (WAL, une connexion par thread), sans démarrer de worker : les traitements sont mis en file et
c'est Noter.app qui les exécute. Les enregistrements passent par l'app (socket local, voir applink).

Pas de `from __future__ import annotations` ici : le SDK lit les annotations pour bâtir les schémas.
"""
import functools
import logging
from datetime import date, datetime, timedelta
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from noter import __version__
from noter.applink import AppLink
from noter.config import Settings, load_settings
from noter.mcp_server import views
from noter.models import ChecklistItem, JobKind, Recording, RecordingStatus
from noter.service import Service
from noter.storage import files

logger = logging.getLogger(__name__)

INSTRUCTIONS = """Noter enregistre les calls et réunions de l'utilisateur sur son Mac, les transcrit en local
(Whisper) et en tire un compte-rendu (TL;DR, points clés, décisions, actions). Les actions alimentent
des boards de tâches façon Trello (boards → listes → cartes).

Bonnes pratiques :
- Pour retrouver un sujet, commence par `search` ou `list_recordings`, puis `get_recording` (résumé et
  actions). Ne lis le transcript (`get_transcript`, paginé) que si le résumé ne suffit pas.
- Les identifiants d'enregistrement acceptent les 8 premiers caractères.
- Cite tes sources : titre et date du call, et l'horodatage [mm:ss] quand tu t'appuies sur le transcript.
- Les dates sont au format AAAA-MM-JJ. Les échéances des actions sont du texte libre ; celles des cartes
  sont de vraies dates.
- Les traitements (transcription, résumé) et l'enregistrement tournent dans Noter.app : les outils le
  disent si l'app n'est pas lancée.
"""

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
IDEMPOTENT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
DELETE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)

RecId = Annotated[str, Field(description="Identifiant de l'enregistrement (complet ou 8 premiers caractères)")]
Day = Annotated[str | None, Field(description="Date AAAA-MM-JJ")]


def _safe(fn):
    """Les erreurs attendues (introuvable, valeur invalide…) arrivent à Claude avec leur message."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except (ValueError, LookupError, RuntimeError, OSError) as e:
            raise ToolError(str(e) or type(e).__name__) from e

    return wrapper


def _day(text: str | None, field: str) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(text.strip()[:10])
    except ValueError:
        raise ValueError(f"{field} : date attendue au format AAAA-MM-JJ, reçu « {text} »") from None


def _blank_to_none(v: str | None) -> str | None:
    return v.strip() or None if isinstance(v, str) else v


def build_server(service: Service | None = None, link: AppLink | None = None,
                 settings: Settings | None = None) -> MCPServer:
    svc = service or Service(settings or load_settings())
    cfg = svc.settings
    repo = svc.repo
    link = link or AppLink()
    server = MCPServer(name="noter", title="Noter", instructions=INSTRUCTIONS, version=__version__, log_level="WARNING")

    can_write = not cfg.mcp_read_only
    allowed = {
        "read": True,
        "write": can_write,
        "record": can_write and cfg.mcp_allow_record,
        "delete": can_write and cfg.mcp_allow_delete,
    }

    def tool(kind: str = "read", annotations: ToolAnnotations | None = None):
        default = {"read": READ, "write": WRITE, "record": WRITE, "delete": DELETE}[kind]

        def deco(fn):
            if allowed[kind]:
                server.add_tool(_safe(fn), annotations=annotations or default)
            return fn

        return deco

    # ─── Aides ──────────────────────────────────────────────────────

    def rec_or_fail(recording_id: str) -> Recording:
        rec = repo.get_recording(recording_id.strip())
        if rec is None:
            raise LookupError(f"Enregistrement introuvable (ou identifiant ambigu) : {recording_id}")
        return rec

    def changed() -> None:
        """Après une écriture : l'app (si elle tourne) relit la base."""
        link.refresh()

    def app_for_jobs() -> dict:
        state = link.ensure_running() if cfg.mcp_launch_app else ("running" if link.is_running() else "absent")
        notes = {
            "running": "Noter.app va traiter le job dans les secondes qui viennent.",
            "launched": "Noter.app vient d'être lancée et va traiter le job.",
            "absent": "Noter.app n'est pas lancée : le job attend en file et partira à son prochain lancement "
                      "(ou avec `noter worker`).",
        }
        return {"app": state, "note": notes[state]}

    def resolve_list(board_id: int | None, list_id: int | None, list_name: str | None):
        if list_id is not None:
            lst = repo.get_list(list_id)
            if lst is None:
                raise LookupError(f"Liste introuvable : {list_id}")
            return lst
        board = repo.get_board(board_id) if board_id is not None else svc.default_board()
        if board is None:
            raise LookupError(f"Board introuvable : {board_id}")
        lists = repo.get_lists(board.id)
        if list_name:
            wanted = list_name.strip().lower()
            for lst in lists:
                if lst.name.lower() == wanted:
                    return lst
            raise LookupError(f"Pas de liste « {list_name} » dans « {board.name} » "
                              f"(listes : {', '.join(x.name for x in lists) or 'aucune'})")
        if not lists:
            return repo.create_list(board.id, "À faire")
        return lists[0]

    def card_or_fail(card_id: int):
        card = repo.get_card(card_id)
        if card is None:
            raise LookupError(f"Carte introuvable : {card_id}")
        return card

    # ─── Lecture : enregistrements ──────────────────────────────────

    @tool()
    def search(
        query: Annotated[str, Field(description="Mots à chercher (recherche plein texte, préfixes acceptés)")],
        limit: Annotated[int, Field(ge=1, le=100)] = 30,
    ) -> dict:
        """Recherche plein texte dans les transcripts, les comptes-rendus et les titres.

        Les résultats sont groupés par enregistrement ; chaque passage de transcript a son horodatage
        (start_s) pour aller lire autour avec get_transcript.
        """
        grouped: dict[str, dict] = {}
        for hit in repo.search(query, limit=limit):
            entry = grouped.get(hit.recording.id)
            if entry is None:
                entry = grouped[hit.recording.id] = {"recording": views.recording_brief(hit.recording), "matches": []}
            match = {"in": hit.kind, "snippet": hit.snippet}
            if hit.start_s is not None:
                match["start_s"] = round(hit.start_s, 1)
            entry["matches"].append(match)
        return {"query": query, "results": list(grouped.values())}

    @tool()
    def list_recordings(
        project: str | None = None,
        tag: str | None = None,
        status: Annotated[str | None, Field(description="recorded, transcribing, done, failed…")] = None,
        since: Day = None,
        until: Annotated[str | None, Field(description="Date AAAA-MM-JJ (incluse)")] = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 30,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> dict:
        """Liste les enregistrements, du plus récent au plus ancien, avec leur TL;DR."""
        st = RecordingStatus(status) if status else None
        d_since, d_until = _day(since, "since"), _day(until, "until")
        recs = repo.list_recordings(
            limit=limit + 1, offset=offset, status=st, project=project or None, tag=tag or None,
            since=datetime.combine(d_since, datetime.min.time()) if d_since else None,
            until=datetime.combine(d_until + timedelta(days=1), datetime.min.time()) if d_until else None,
        )
        page = recs[:limit]
        return {
            "recordings": [views.recording_brief(r, repo.get_summary(r.id)) for r in page],
            "has_more": len(recs) > limit,
            "next_offset": offset + limit if len(recs) > limit else None,
        }

    @tool()
    def get_recording(recording_id: RecId) -> dict:
        """Fiche complète d'un enregistrement : métadonnées, compte-rendu (TL;DR, points clés, décisions,
        actions avec leur index et leur carte éventuelle), speakers et taille du transcript."""
        return views.recording_detail(repo, rec_or_fail(recording_id))

    @tool()
    def get_transcript(
        recording_id: RecId,
        start_s: Annotated[float, Field(ge=0, description="Début de la fenêtre, en secondes")] = 0.0,
        end_s: Annotated[float | None, Field(description="Fin de la fenêtre, en secondes")] = None,
        speaker: Annotated[str | None, Field(description="Seulement ce speaker")] = None,
        max_chars: Annotated[int, Field(ge=1000, le=60000)] = 12000,
    ) -> dict:
        """Transcript horodaté, par fenêtres. Si `complete` est faux, rappelle avec start_s=next_start_s
        pour la suite."""
        rec = rec_or_fail(recording_id)
        segments = repo.get_segments(rec.id)
        if not segments:
            raise ValueError(f"Pas encore de transcript pour « {rec.display_title} » (statut {rec.status})")
        out = views.transcript_window(segments, start_s, end_s, speaker, max_chars)
        return {"recording": views.recording_brief(rec), **out}

    @tool()
    def list_projects_and_tags() -> dict:
        """Projets et tags existants, avec leur nombre d'enregistrements."""
        return {"projects": repo.project_counts(), "tags": repo.tag_counts()}

    @tool()
    def list_open_actions(
        project: str | None = None,
        owner: Annotated[str | None, Field(description="Responsable (recherche partielle, sans casse)")] = None,
        since: Day = None,
        overdue_only: bool = False,
        limit: Annotated[int, Field(ge=1, le=300)] = 100,
    ) -> dict:
        """Actions pas encore faites, tous comptes-rendus confondus (une action est faite si elle est
        cochée dans le compte-rendu, ou si l'échéance de sa carte est marquée terminée)."""
        d_since = _day(since, "since")
        today = date.today()
        tasks = views.TaskIndex(repo)
        out = []
        recs = repo.list_recordings(
            limit=2000, project=project or None,
            since=datetime.combine(d_since, datetime.min.time()) if d_since else None,
        )
        for rec in recs:
            summary = repo.get_summary(rec.id)
            if summary is None:
                continue
            cards = {c.title.strip(): c for c in repo.cards_for_recording(rec.id)}
            for i, a in enumerate(summary.actions):
                card = cards.get(a.text.strip())
                if a.done or (card is not None and card.done):
                    continue
                if owner and owner.lower() not in (a.owner or "").lower():
                    continue
                due = card.due if card is not None and card.due else views.iso_day(a.due)
                overdue = bool(due and due < today)
                if overdue_only and not overdue:
                    continue
                item = {"recording_id": rec.short_id, "recording": rec.display_title,
                        "date": rec.started_at.date().isoformat(), "index": i, "text": a.text}
                if a.owner:
                    item["owner"] = a.owner
                if a.due:
                    item["due"] = a.due
                if overdue:
                    item["overdue"] = True
                if card is not None:
                    item["card"] = tasks.card_ref(card)
                out.append(item)
                if len(out) >= limit:
                    return {"actions": out, "truncated": True}
        return {"actions": out, "truncated": False}

    @tool()
    def get_status() -> dict:
        """État de Noter : app lancée ou non, enregistrement en cours, file de traitement, échecs récents,
        et ce que ce serveur MCP autorise."""
        live = link.status()
        failed = repo.list_recordings(limit=10, status=RecordingStatus.FAILED)
        failures = []
        for r in failed:
            jobs = repo.list_jobs(recording_id=r.id, limit=1)
            failures.append({**views.recording_brief(r), "error": jobs[0].error if jobs else None})
        return {
            "app_running": live is not None,
            "recording": live.get("recording") if live else None,
            "current_job": live.get("job") if live else None,
            "pending_jobs": repo.pending_job_count(),
            "recordings": repo.count_recordings(),
            "failed": failures,
            "permissions": {k: v for k, v in allowed.items() if k != "read"},
        }

    # ─── Lecture : tâches ───────────────────────────────────────────

    @tool()
    def list_boards() -> dict:
        """Boards de tâches avec leurs listes et le nombre de cartes (dont en retard)."""
        tasks = views.TaskIndex(repo)
        out = []
        for b in tasks.boards:
            cards = repo.cards_for_board(b.id)
            out.append({
                "id": b.id, "name": b.name,
                "lists": [{"id": lst.id, "name": lst.name, "cards": len(cards.get(lst.id, []))}
                          for lst in repo.get_lists(b.id)],
                "overdue": sum(1 for cs in cards.values() for c in cs if c.is_overdue()),
            })
        return {"boards": out, "default_board_id": out[0]["id"] if out else None}

    @tool()
    def get_board(
        board_id: Annotated[int | None, Field(description="Board (défaut : le premier)")] = None,
        query: Annotated[str | None, Field(description="Filtre titre / description")] = None,
    ) -> dict:
        """Contenu d'un board : ses listes dans l'ordre, et leurs cartes dans l'ordre."""
        board = repo.get_board(board_id) if board_id is not None else (repo.list_boards() or [None])[0]
        if board is None:
            raise LookupError("Board introuvable" if board_id is not None else "Aucun board pour l'instant")
        tasks = views.TaskIndex(repo)
        cards = repo.cards_for_board(board.id)
        q = (query or "").strip().lower()
        lists = []
        for lst in repo.get_lists(board.id):
            cs = [c for c in cards.get(lst.id, []) if not q or q in c.title.lower() or q in c.description.lower()]
            lists.append({"id": lst.id, "name": lst.name, "cards": [tasks.card(c, compact=True) for c in cs]})
        return {"board": {"id": board.id, "name": board.name}, "lists": lists}

    @tool()
    def get_card(card_id: int) -> dict:
        """Une carte en détail : description, checklist (avec index), échéance, enregistrement d'origine."""
        return views.TaskIndex(repo).card(card_or_fail(card_id))

    @tool()
    def find_cards(
        query: Annotated[str | None, Field(description="Texte dans le titre ou la description")] = None,
        board_id: int | None = None,
        label: Annotated[str | None, Field(description="green, yellow, orange, red, purple, blue (ou en français)")] = None,
        overdue_only: bool = False,
        due_before: Day = None,
        recording_id: Annotated[str | None, Field(description="Cartes issues de cet enregistrement")] = None,
        limit: Annotated[int, Field(ge=1, le=300)] = 50,
    ) -> dict:
        """Cherche des cartes dans tous les boards (ou un seul)."""
        tasks = views.TaskIndex(repo)
        q = (query or "").strip().lower()
        lab = views.label_key(label) if label else None
        before = _day(due_before, "due_before")
        rid = rec_or_fail(recording_id).id if recording_id else None
        out = []
        for c in tasks.all_cards(board_id):
            if q and q not in c.title.lower() and q not in c.description.lower():
                continue
            if lab and lab not in c.labels:
                continue
            if overdue_only and not c.is_overdue():
                continue
            if before and not (c.due and c.due < before):
                continue
            if rid and c.recording_id != rid:
                continue
            board = tasks.where(c)[1]
            out.append({**tasks.card(c, compact=True), "board": board.name if board else None})
            if len(out) >= limit:
                break
        return {"cards": out}

    # ─── Écriture : tâches ──────────────────────────────────────────

    @tool("write")
    def create_board(name: str) -> dict:
        """Crée un board avec les listes « À faire », « En cours » et « Terminé »."""
        board = svc.create_board(name.strip() or "Sans titre")
        changed()
        return {"id": board.id, "name": board.name, "lists": [{"id": x.id, "name": x.name} for x in repo.get_lists(board.id)]}

    @tool("write", IDEMPOTENT)
    def rename_board(board_id: int, name: str) -> dict:
        """Renomme un board."""
        if repo.get_board(board_id) is None:
            raise LookupError(f"Board introuvable : {board_id}")
        repo.rename_board(board_id, name)
        changed()
        return {"id": board_id, "name": name.strip()}

    @tool("write")
    def create_list(board_id: int, name: str) -> dict:
        """Ajoute une liste en bout de board."""
        if repo.get_board(board_id) is None:
            raise LookupError(f"Board introuvable : {board_id}")
        lst = repo.create_list(board_id, name)
        changed()
        return {"id": lst.id, "name": lst.name, "board_id": board_id}

    @tool("write", IDEMPOTENT)
    def rename_list(list_id: int, name: str) -> dict:
        """Renomme une liste."""
        if repo.get_list(list_id) is None:
            raise LookupError(f"Liste introuvable : {list_id}")
        repo.rename_list(list_id, name)
        changed()
        return {"id": list_id, "name": name.strip()}

    @tool("write")
    def create_card(
        title: str,
        board_id: Annotated[int | None, Field(description="Board (défaut : le premier)")] = None,
        list_id: Annotated[int | None, Field(description="Liste précise (prioritaire sur board/list_name)")] = None,
        list_name: Annotated[str | None, Field(description="Nom de la liste dans le board, ex. « En cours »")] = None,
        description: str = "",
        due: Day = None,
        labels: Annotated[list[str] | None, Field(description="Couleurs : green, yellow, orange, red, purple, blue")] = None,
        checklist: Annotated[list[str] | None, Field(description="Éléments de checklist")] = None,
        at_top: Annotated[bool, Field(description="En haut de la liste (sinon en bas)")] = False,
        recording_id: Annotated[str | None, Field(description="Enregistrement d'origine, pour le lien retour")] = None,
    ) -> dict:
        """Crée une carte (par défaut dans la première liste du premier board)."""
        lst = resolve_list(board_id, list_id, list_name)
        fields: dict = {"description": description or ""}
        if due:
            fields["due"] = _day(due, "due")
        if labels:
            fields["labels"] = [views.label_key(x) for x in labels]
        if checklist:
            fields["checklist"] = [ChecklistItem(text=t.strip()) for t in checklist if t.strip()]
        if recording_id:
            fields["recording_id"] = rec_or_fail(recording_id).id
        card = repo.create_card(lst.id, title, at_top=at_top, **fields)
        changed()
        return views.TaskIndex(repo).card(card)

    @tool("write", IDEMPOTENT)
    def update_card(
        card_id: int,
        title: str | None = None,
        description: str | None = None,
        due: Annotated[str | None, Field(description="AAAA-MM-JJ, ou chaîne vide pour retirer l'échéance")] = None,
        due_done: Annotated[bool | None, Field(description="Carte terminée (coche verte), avec ou sans échéance")] = None,
        labels: Annotated[list[str] | None, Field(description="Remplace les étiquettes ([] pour toutes les retirer)")] = None,
        checklist_add: Annotated[list[str] | None, Field(description="Éléments à ajouter à la checklist")] = None,
        checklist_check: Annotated[list[int] | None, Field(description="Index des éléments à cocher")] = None,
        checklist_uncheck: Annotated[list[int] | None, Field(description="Index des éléments à décocher")] = None,
        checklist_remove: Annotated[list[int] | None, Field(description="Index des éléments à retirer")] = None,
    ) -> dict:
        """Modifie une carte. Seuls les champs fournis changent. Les index de checklist sont ceux de
        get_card, avant les ajouts et retraits de cet appel."""
        card = card_or_fail(card_id)
        fields: dict = {}
        if title is not None:
            fields["title"] = title
        if description is not None:
            fields["description"] = description
        if due is not None:
            fields["due"] = _day(due, "due") if due.strip() else None
        if due_done is not None:
            fields["done"] = due_done
        if labels is not None:
            fields["labels"] = [views.label_key(x) for x in labels]
        if checklist_add or checklist_check or checklist_uncheck or checklist_remove:
            items = list(card.checklist)
            for idx in (checklist_check or []) + (checklist_uncheck or []) + (checklist_remove or []):
                if not 0 <= idx < len(items):
                    raise IndexError(f"Pas d'élément {idx} dans la checklist ({len(items)} éléments)")
            for idx in checklist_check or []:
                items[idx] = ChecklistItem(items[idx].text, True)
            for idx in checklist_uncheck or []:
                items[idx] = ChecklistItem(items[idx].text, False)
            drop = set(checklist_remove or [])
            items = [it for i, it in enumerate(items) if i not in drop]
            items += [ChecklistItem(t.strip()) for t in checklist_add or [] if t.strip()]
            fields["checklist"] = items
        repo.update_card(card.id, **fields)
        changed()
        return views.TaskIndex(repo).card(repo.get_card(card.id))

    @tool("write", IDEMPOTENT)
    def move_card(
        card_id: int,
        list_id: Annotated[int | None, Field(description="Liste de destination")] = None,
        list_name: Annotated[str | None, Field(description="…ou son nom (dans le board de la carte, sauf board_id)")] = None,
        board_id: Annotated[int | None, Field(description="Board de destination, avec list_name")] = None,
        position: Annotated[int | None, Field(ge=0, description="0 = en haut ; absent = en bas")] = None,
    ) -> dict:
        """Déplace une carte dans une autre liste (ou à une autre place dans la même)."""
        card = card_or_fail(card_id)
        if list_id is None and not list_name:
            raise ValueError("Indique list_id ou list_name")
        if list_id is None and board_id is None:
            board = repo.board_of_card(card.id)
            board_id = board.id if board else None
        lst = resolve_list(board_id, list_id, list_name)
        index = position if position is not None else len(repo.cards_in_list(lst.id))
        repo.move_card(card.id, lst.id, index)
        changed()
        return views.TaskIndex(repo).card(repo.get_card(card.id), compact=True)

    @tool("write", IDEMPOTENT)
    def add_actions_to_tasks(
        recording_id: RecId,
        action_index: Annotated[int | None, Field(description="Une seule action (index de get_recording) ; absent = toutes")] = None,
        board_id: Annotated[int | None, Field(description="Board (défaut : le premier)")] = None,
    ) -> dict:
        """Transforme les actions d'un compte-rendu en cartes (en haut de la première liste). Une action
        qui a déjà sa carte n'en reçoit pas une seconde."""
        rec = rec_or_fail(recording_id)
        if action_index is not None:
            before = {c.id for c in repo.cards_for_recording(rec.id)}
            card = svc.card_from_action(rec.id, action_index, board_id)
            created = [card] if card.id not in before else []
            cards = [card]
        else:
            created = svc.cards_from_summary(rec.id, board_id)
            cards = created
        changed()
        tasks = views.TaskIndex(repo)
        return {"created": len(created), "cards": [tasks.card(c, compact=True) for c in cards]}

    # ─── Écriture : enregistrements ─────────────────────────────────

    @tool("write", IDEMPOTENT)
    def update_recording(
        recording_id: RecId,
        title: str | None = None,
        project: Annotated[str | None, Field(description="Chaîne vide pour retirer le projet")] = None,
        tags: Annotated[list[str] | None, Field(description="Remplace tous les tags")] = None,
        notes: str | None = None,
    ) -> dict:
        """Modifie titre, projet, tags ou notes (les fichiers summary.md / rapport.pdf sont régénérés)."""
        rec = rec_or_fail(recording_id)
        fields: dict = {}
        if title is not None:
            fields["title"] = _blank_to_none(title)
        if project is not None:
            fields["project"] = _blank_to_none(project)
        if notes is not None:
            fields["notes"] = notes
        if tags is not None:
            fields["tags"] = tags
        if not fields:
            raise ValueError("Rien à modifier")
        rec = svc.update_metadata(rec.id, **fields)
        changed()
        return views.recording_brief(rec)

    @tool("write", IDEMPOTENT)
    def rename_speaker(
        recording_id: RecId,
        new_name: str,
        old_name: Annotated[str | None, Field(description="Nom actuel (ex. SPEAKER_00) ; absent = segments sans speaker")] = None,
    ) -> dict:
        """Renomme un speaker dans tout le transcript d'un enregistrement."""
        rec = rec_or_fail(recording_id)
        if not new_name.strip():
            raise ValueError("Le nouveau nom est vide")
        if old_name is not None and old_name.strip() in ("", views.UNNAMED_SPEAKER):
            old_name = None
        n = repo.rename_speaker(rec.id, old_name, new_name.strip())
        if n == 0:
            names = list(views.speakers(repo.get_segments(rec.id)))
            raise LookupError(f"Aucun segment pour « {old_name} » (speakers : {', '.join(names) or 'aucun'})")
        svc.pipeline.render_outputs(rec.id)
        changed()
        return {"renamed_segments": n, "speakers": views.speakers(repo.get_segments(rec.id))}

    @tool("write", IDEMPOTENT)
    def set_action_done(recording_id: RecId, action_index: int, done: bool = True) -> dict:
        """Coche (ou décoche) une action dans le compte-rendu."""
        rec = rec_or_fail(recording_id)
        repo.set_action_done(rec.id, action_index, done)
        svc.pipeline.render_outputs(rec.id)
        changed()
        return {"recording_id": rec.short_id, "action_index": action_index, "done": done}

    @tool("write")
    def import_audio(
        path: Annotated[str, Field(description="Chemin d'un fichier audio sur ce Mac (wav, m4a, mp3…)")],
        title: str | None = None,
        project: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Importe un fichier audio (copié dans ~/Noter) et lance transcription puis résumé."""
        from pathlib import Path

        rec = svc.import_file(Path(path), title=title or None, project=project or None, tags=tags or [])
        changed()
        return {"recording": views.recording_brief(rec), **app_for_jobs()}

    @tool("write")
    def process(
        recording_id: RecId,
        summary_only: Annotated[bool, Field(description="Refaire seulement le résumé (transcript conservé)")] = False,
    ) -> dict:
        """(Re)lance le traitement d'un enregistrement : transcription puis résumé, ou résumé seul."""
        rec = rec_or_fail(recording_id)
        if rec.status == RecordingStatus.RECORDING:
            raise RuntimeError("Enregistrement en cours : arrête-le d'abord")
        if summary_only and not repo.get_segments(rec.id):
            raise ValueError("Pas de transcript : relance sans summary_only")
        job = svc.jobs.enqueue(rec.id, JobKind.SUMMARIZE if summary_only else JobKind.TRANSCRIBE)
        changed()
        return {"job_id": job.id, "kind": str(job.kind), **app_for_jobs()}

    @tool("write")
    def retry_failed(recording_id: Annotated[str | None, Field(description="Absent = tous les échecs")] = None) -> dict:
        """Relance les traitements en échec."""
        if recording_id:
            n = svc.jobs.retry(rec_or_fail(recording_id).id)
        else:
            n = sum(svc.jobs.retry(r.id) for r in repo.list_recordings(limit=1000, status=RecordingStatus.FAILED))
        changed()
        return {"requeued": n, **(app_for_jobs() if n else {})}

    # ─── Enregistrement (via l'app) ─────────────────────────────────

    def app_or_fail() -> None:
        state = link.ensure_running() if cfg.mcp_launch_app else ("running" if link.is_running() else "absent")
        if state == "absent":
            raise RuntimeError("Noter.app n'est pas lancée (et n'a pas pu être lancée) : l'enregistrement passe par l'app")

    def reply_or_fail(reply: dict | None) -> dict:
        if reply is None:
            raise RuntimeError("Noter.app ne répond pas")
        if not reply.get("ok"):
            raise RuntimeError(reply.get("error") or "Échec côté Noter.app")
        return reply

    @tool("record")
    def start_recording(
        title: str | None = None,
        project: str | None = None,
        tags: list[str] | None = None,
        mic_only: Annotated[bool, Field(description="Micro seul (réunion en présentiel), sans l'audio du Mac")] = False,
    ) -> dict:
        """Démarre un enregistrement dans Noter.app (la fenêtre s'affiche pour que ça se voie). Ne l'utilise
        que si l'utilisateur le demande explicitement."""
        app_or_fail()
        reply = reply_or_fail(link.send("record_start", timeout=15, title=title, project=project,
                                        tags=tags or [], system_audio=not mic_only))
        return {"recording": reply.get("recording")}

    @tool("record")
    def stop_recording() -> dict:
        """Arrête l'enregistrement en cours ; transcription et résumé suivent automatiquement."""
        reply = reply_or_fail(link.send("record_stop", timeout=180))
        return {"recording": reply.get("recording"), "note": "Transcription puis résumé en cours dans Noter.app."}

    # ─── Suppression ────────────────────────────────────────────────

    @tool("delete")
    def delete_recording(
        recording_id: RecId,
        confirm: Annotated[bool, Field(description="Doit valoir true, après accord explicite de l'utilisateur")] = False,
    ) -> dict:
        """Supprime définitivement un enregistrement et son dossier (audio, transcript, résumé)."""
        rec = rec_or_fail(recording_id)
        if not confirm:
            raise ValueError(f"Suppression de « {rec.display_title} » non confirmée : demande d'abord à l'utilisateur, "
                             "puis rappelle avec confirm=true")
        if rec.status == RecordingStatus.RECORDING:
            raise RuntimeError("Enregistrement en cours : arrête-le d'abord")
        svc.delete_recording(rec.id)
        changed()
        return {"deleted": rec.short_id, "title": rec.display_title}

    @tool("delete")
    def delete_card(
        card_id: int,
        confirm: Annotated[bool, Field(description="Doit valoir true, après accord explicite de l'utilisateur")] = False,
    ) -> dict:
        """Supprime définitivement une carte."""
        card = card_or_fail(card_id)
        if not confirm:
            raise ValueError(f"Suppression de la carte « {card.title} » non confirmée : demande d'abord à l'utilisateur, "
                             "puis rappelle avec confirm=true")
        repo.delete_card(card.id)
        changed()
        return {"deleted": card.id, "title": card.title}

    # ─── Resources ──────────────────────────────────────────────────

    def rec_resource(recording_id: str) -> Recording:
        rec = repo.get_recording(recording_id)
        if rec is None:
            raise ResourceNotFoundError(f"Enregistrement introuvable : {recording_id}")
        return rec

    @server.resource("noter://recordings/{recording_id}/summary", title="Compte-rendu", mime_type="text/markdown")
    def summary_resource(recording_id: str) -> str:
        """Compte-rendu d'un enregistrement, en Markdown."""
        rec = rec_resource(recording_id)
        summary = repo.get_summary(rec.id)
        if summary is None:
            raise ResourceNotFoundError(f"Pas encore de compte-rendu pour {recording_id}")
        return files.summary_markdown(rec, summary)

    @server.resource("noter://recordings/{recording_id}/transcript", title="Transcript", mime_type="text/markdown")
    def transcript_resource(recording_id: str) -> str:
        """Transcript horodaté complet d'un enregistrement, en Markdown."""
        rec = rec_resource(recording_id)
        segments = repo.get_segments(rec.id)
        if not segments:
            raise ResourceNotFoundError(f"Pas encore de transcript pour {recording_id}")
        return files.transcript_markdown(rec, segments)

    @server.resource("noter://boards/{board_id}", title="Board", mime_type="text/markdown")
    def board_resource(board_id: str) -> str:
        """Un board de tâches, liste par liste, en Markdown."""
        board = repo.get_board(int(board_id)) if board_id.isdigit() else None
        if board is None:
            raise ResourceNotFoundError(f"Board introuvable : {board_id}")
        return views.board_markdown(repo, board)

    # ─── Prompts ────────────────────────────────────────────────────

    @server.prompt(title="Préparer un call")
    def preparer_call(sujet: Annotated[str, Field(description="Client, projet ou personne")]) -> str:
        """Brief avant un call : historique, décisions, actions ouvertes, questions à poser."""
        return (
            f"Je vais avoir un call à propos de : {sujet}.\n"
            "Avec les outils Noter : retrouve les calls passés qui en parlent (search, list_recordings avec le "
            "projet s'il existe), lis leurs comptes-rendus (get_recording), et les actions encore ouvertes "
            "(list_open_actions, find_cards).\n"
            "Fais-moi un brief court : contexte en 3 lignes, ce qui a été décidé (avec la date du call), ce qui "
            "est en attente et chez qui, points de friction, et 3 à 5 questions à poser. Cite les calls sources."
        )

    @server.prompt(title="Mail de suivi")
    def mail_de_suivi(recording_id: Annotated[str, Field(description="Identifiant de l'enregistrement")]) -> str:
        """Rédige le mail de suivi d'un call à partir de son compte-rendu."""
        return (
            f"Lis le compte-rendu de l'enregistrement {recording_id} (get_recording), et le transcript si un "
            "point est flou. Rédige le mail de suivi aux participants : remerciement bref, récap des décisions, "
            "actions avec responsable et échéance, prochaine étape. Même langue que le call, ton naturel, "
            "pas de formules creuses. Donne aussi un objet."
        )

    @server.prompt(title="Synthèse d'un projet")
    def synthese_projet(
        projet: str,
        depuis: Annotated[str, Field(description="Date AAAA-MM-JJ (optionnelle)")] = "",
    ) -> str:
        """Synthèse de tous les calls d'un projet sur une période."""
        period = f" depuis le {depuis}" if depuis else ""
        return (
            f"Fais la synthèse du projet « {projet} »{period} à partir des calls Noter (list_recordings avec "
            "project et since, puis get_recording pour chacun ; si aucun call n'a ce projet, utilise search).\n"
            "Structure : où on en est, chronologie des décisions (date + call), sujets récurrents, risques, "
            "actions ouvertes (list_open_actions). Cite les calls sources."
        )

    @server.prompt(title="Revue des tâches")
    def revue_des_taches(board: Annotated[str, Field(description="Nom du board (optionnel)")] = "") -> str:
        """Point sur les tâches : retards, cartes sans échéance, cartes qui stagnent."""
        target = f"le board « {board} »" if board else "tous les boards"
        return (
            f"Fais une revue de {target} avec les outils Noter (list_boards, get_board, find_cards).\n"
            "Liste : les cartes en retard, celles qui arrivent à échéance cette semaine, celles sans échéance "
            "issues d'un call, et propose un tri (quoi déplacer, quoi clore). Ne modifie rien sans mon accord."
        )

    return server


def main() -> None:
    """`noter mcp` : serveur stdio. stdout est réservé au protocole, les logs vont dans ~/Noter/noter.log."""
    from noter.logging_setup import setup_logging

    settings = load_settings()
    setup_logging(settings.log_path, console=False)
    service = Service(settings)
    logger.info("Serveur MCP démarré (lecture seule : %s)", settings.mcp_read_only)
    try:
        build_server(service).run("stdio")
    finally:
        service.stop()
