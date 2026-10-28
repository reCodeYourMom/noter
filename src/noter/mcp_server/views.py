"""Objets Noter → dicts JSON compacts pour Claude (et rendus Markdown des resources)."""
from __future__ import annotations

from datetime import date

from noter.models import (
    LABEL_KEYS,
    LABEL_NAMES_FR,
    Board,
    BoardList,
    Card,
    Recording,
    Segment,
    Summary,
    format_timestamp,
)
from noter.storage.repo import Repository

UNNAMED_SPEAKER = "(sans nom)"

_LABEL_BY_NAME = {**{k: k for k in LABEL_KEYS}, **{v.lower(): k for k, v in LABEL_NAMES_FR.items()}}


def label_key(name: str) -> str:
    """'vert', 'Vert' ou 'green' → 'green'."""
    key = _LABEL_BY_NAME.get(name.strip().lower())
    if key is None:
        raise ValueError(f"Étiquette inconnue : {name} (au choix : {', '.join(LABEL_KEYS)})")
    return key


def iso_day(text: str | None) -> date | None:
    """Échéance d'une action (texte libre) : une date seulement si elle est au format AAAA-MM-JJ."""
    try:
        return date.fromisoformat(text.strip()) if text else None
    except ValueError:
        return None


# ─── Enregistrements ────────────────────────────────────────────────


def recording_brief(rec: Recording, summary: Summary | None = None) -> dict:
    out = {
        "id": rec.short_id,
        "title": rec.display_title,
        "date": rec.started_at.isoformat(timespec="minutes"),
        "duration": rec.duration_text,
        "status": str(rec.status),
    }
    if rec.project:
        out["project"] = rec.project
    if rec.tags:
        out["tags"] = rec.tags
    if summary is not None:
        out["tldr"] = summary.tldr
    return out


def speakers(segments: list[Segment]) -> dict[str, float]:
    """Temps de parole (s) par speaker, du plus bavard au moins bavard."""
    talk: dict[str, float] = {}
    for s in segments:
        name = s.speaker or UNNAMED_SPEAKER
        talk[name] = talk.get(name, 0.0) + max(0.0, s.end - s.start)
    return {k: round(v) for k, v in sorted(talk.items(), key=lambda kv: -kv[1])}


def recording_detail(repo: Repository, rec: Recording) -> dict:
    summary = repo.get_summary(rec.id)
    segments = repo.get_segments(rec.id)
    out = recording_brief(rec)
    out["full_id"] = rec.id
    out["source"] = str(rec.source)
    if rec.language:
        out["language"] = rec.language
    if rec.notes:
        out["notes"] = rec.notes
    out["folder"] = str(rec.dir_path)
    out["transcript"] = {
        "segments": len(segments),
        "chars": sum(len(s.text) for s in segments),
        "speakers": speakers(segments),
    }
    if summary is not None:
        tasks = TaskIndex(repo)
        cards = {c.title.strip(): c for c in repo.cards_for_recording(rec.id)}
        actions = []
        for i, a in enumerate(summary.actions):
            item = {"index": i, "text": a.text, "done": a.done}
            if a.owner:
                item["owner"] = a.owner
            if a.due:
                item["due"] = a.due
            card = cards.get(a.text.strip())
            if card is not None:
                item["card"] = tasks.card_ref(card)
            actions.append(item)
        out["summary"] = {
            "tldr": summary.tldr,
            "key_points": summary.key_points,
            "decisions": summary.decisions,
            "actions": actions,
        }
    if rec.status == "failed":
        jobs = repo.list_jobs(recording_id=rec.id, limit=1)
        if jobs and jobs[0].error:
            out["last_error"] = jobs[0].error
    return out


def transcript_window(segments: list[Segment], start_s: float = 0.0, end_s: float | None = None,
                      speaker: str | None = None, max_chars: int = 12000) -> dict:
    """Une fenêtre du transcript, avec de quoi demander la suite (next_start_s)."""
    lines: list[str] = []
    size = 0
    first = last = None
    next_start = None
    wanted = speaker.strip().lower() if speaker else None
    for s in segments:
        if s.end <= start_s and s.start < start_s:
            continue
        if end_s is not None and s.start >= end_s:
            break
        if wanted and (s.speaker or "").lower() != wanted:
            continue
        line = f"[{format_timestamp(s.start)}] {s.speaker or 'Speaker'}: {s.text}"
        if lines and size + len(line) + 1 > max_chars:
            next_start = s.start
            break
        lines.append(line)
        size += len(line) + 1
        first = s.start if first is None else first
        last = s.end
    return {
        "text": "\n".join(lines),
        "from_s": first,
        "to_s": last,
        "next_start_s": next_start,
        "complete": next_start is None,
    }


# ─── Tâches ─────────────────────────────────────────────────────────


class TaskIndex:
    """Listes et boards chargés une fois, pour nommer la liste et le board de chaque carte."""

    def __init__(self, repo: Repository):
        self.repo = repo
        self.boards: list[Board] = repo.list_boards()
        self.lists: dict[int, tuple[BoardList, Board]] = {}
        for b in self.boards:
            for lst in repo.get_lists(b.id):
                self.lists[lst.id] = (lst, b)

    def where(self, card: Card) -> tuple[BoardList | None, Board | None]:
        return self.lists.get(card.list_id, (None, None))

    def card_ref(self, card: Card) -> dict:
        lst, board = self.where(card)
        return {"id": card.id, "board": board.name if board else None, "list": lst.name if lst else None,
                "done": card.done}

    def card(self, card: Card, today: date | None = None, compact: bool = False) -> dict:
        lst, board = self.where(card)
        out: dict = {"id": card.id, "title": card.title}
        if not compact:
            out.update({"board_id": board.id if board else None, "board": board.name if board else None})
        out.update({"list_id": card.list_id, "list": lst.name if lst else None})
        if card.description and not compact:
            out["description"] = card.description
        if card.done:
            out["done"] = True
        if card.due:
            out["due"] = card.due.isoformat()
            out["due_done"] = card.done
            if card.is_overdue(today):
                out["overdue"] = True
        if card.labels:
            out["labels"] = card.labels
        if card.checklist:
            done, total = card.checklist_progress
            out["checklist_progress"] = f"{done}/{total}"
            if not compact:
                out["checklist"] = [{"index": i, "text": it.text, "done": it.done} for i, it in enumerate(card.checklist)]
        if card.recording_id:
            out["recording_id"] = card.recording_id[:8]
        return out

    def all_cards(self, board_id: int | None = None) -> list[Card]:
        out: list[Card] = []
        for b in self.boards:
            if board_id is not None and b.id != board_id:
                continue
            for cards in self.repo.cards_for_board(b.id).values():
                out.extend(cards)
        return out


def board_markdown(repo: Repository, board: Board) -> str:
    parts = [f"# {board.name}", ""]
    cards = repo.cards_for_board(board.id)
    for lst in repo.get_lists(board.id):
        parts.append(f"## {lst.name} ({len(cards.get(lst.id, []))})")
        for c in cards.get(lst.id, []):
            meta = []
            if c.done:
                meta.append("✓ terminée")
            if c.due:
                meta.append(f"échéance {c.due:%d/%m/%Y}" + (" (en retard)" if c.is_overdue() else ""))
            if c.labels:
                meta.append(", ".join(LABEL_NAMES_FR.get(k, k) for k in c.labels))
            if c.checklist:
                meta.append("checklist {}/{}".format(*c.checklist_progress))
            suffix = f" — {' · '.join(meta)}" if meta else ""
            parts.append(f"- #{c.id} {c.title}{suffix}")
        parts.append("")
    return "\n".join(parts)
