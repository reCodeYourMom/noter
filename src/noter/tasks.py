"""Des actions d'un compte-rendu aux cartes d'un board.

Utilisé par le pipeline (toutes les actions, à la fin de chaque résumé) et par l'UI (une action à la fois).
Les deux sont idempotents : une action qui a déjà sa carte n'en reçoit pas une seconde.
"""
from __future__ import annotations

from datetime import date

from noter.models import ActionItem, Board, Card, Recording
from noter.storage.repo import Repository

DEFAULT_BOARD_NAME = "Mes tâches"
DEFAULT_LISTS = ["À faire", "En cours", "Terminé"]


def create_board(repo: Repository, name: str) -> Board:
    """Nouveau board avec les trois listes classiques (à faire, en cours, terminé)."""
    return repo.create_board(name, lists=DEFAULT_LISTS)


def default_board(repo: Repository) -> Board:
    """Premier board (le plus haut dans le rail), créé à la volée s'il n'y en a pas encore."""
    boards = repo.list_boards()
    return boards[0] if boards else create_board(repo, DEFAULT_BOARD_NAME)


def card_from_action(repo: Repository, recording_id: str, action_index: int, board_id: int | None = None) -> Card:
    """Crée une carte (en haut de la première liste) à partir d'une action d'un compte-rendu.

    Idempotent : si l'action a déjà une carte, elle est renvoyée telle quelle.
    """
    rec = repo.get_recording(recording_id)
    summary = repo.get_summary(recording_id)
    if rec is None or summary is None or not 0 <= action_index < len(summary.actions):
        raise IndexError("action introuvable")
    action = summary.actions[action_index]
    existing = _existing_cards(repo, rec.id)
    if action.text.strip() in existing:
        return existing[action.text.strip()]
    return _create(repo, rec, action, _first_list_id(repo, board_id))


def cards_from_summary(repo: Repository, recording_id: str, board_id: int | None = None) -> list[Card]:
    """Crée une carte pour chaque action qui n'en a pas encore. Retourne les cartes créées.

    Elles arrivent en haut de la première liste, dans l'ordre du compte-rendu.
    """
    rec = repo.get_recording(recording_id)
    summary = repo.get_summary(recording_id)
    if rec is None or summary is None:
        return []
    existing = _existing_cards(repo, rec.id)
    todo: list[ActionItem] = []
    for a in summary.actions:
        title = a.text.strip()
        if title and title not in existing and title not in {t.text.strip() for t in todo}:
            todo.append(a)
    if not todo:
        return []
    list_id = _first_list_id(repo, board_id)
    # Insérées en haut une à une : on part de la dernière pour garder l'ordre du compte-rendu.
    created = [_create(repo, rec, a, list_id) for a in reversed(todo)]
    return list(reversed(created))


def _existing_cards(repo: Repository, recording_id: str) -> dict[str, Card]:
    return {c.title: c for c in repo.cards_for_recording(recording_id)}


def _first_list_id(repo: Repository, board_id: int | None) -> int:
    board = repo.get_board(board_id) if board_id else default_board(repo)
    if board is None:
        raise ValueError("Board introuvable")
    lists = repo.get_lists(board.id)
    return lists[0].id if lists else repo.create_list(board.id, DEFAULT_LISTS[0]).id


def _create(repo: Repository, rec: Recording, action: ActionItem, list_id: int) -> Card:
    lines = [f"Issu de « {rec.display_title} » ({rec.started_at:%d/%m/%Y})."]
    if action.owner:
        lines.insert(0, f"Responsable : {action.owner}")
    due = _parse_due(action.due)
    if action.due and due is None:  # « vendredi » : pas une date exploitable, on garde l'info
        lines.insert(0, f"Échéance annoncée : {action.due}")
    return repo.create_card(
        list_id, action.text, at_top=True, description="\n".join(lines),
        due=due, done=action.done, recording_id=rec.id,
    )


def _parse_due(text: str | None) -> date | None:
    """Échéance d'une action : seules les dates ISO (AAAA-MM-JJ) sont reconnues."""
    try:
        return date.fromisoformat(text.strip()) if text else None
    except ValueError:
        return None
