"""Serveur MCP : outils, resources, prompts et installation, via le client MCP en mémoire."""
from __future__ import annotations

import json
from datetime import date, timedelta

import anyio
import pytest

pytest.importorskip("mcp")

from mcp.client import Client  # noqa: E402

from noter.mcp_server import install  # noqa: E402
from noter.mcp_server.server import build_server  # noqa: E402
from noter.models import JobStatus, RecordingStatus, Segment  # noqa: E402


class FakeLink:
    """AppLink factice : l'app est « lancée » ou non, et on note les commandes reçues."""

    def __init__(self, running: bool = False):
        self.running = running
        self.sent: list[tuple[str, dict]] = []
        self.refreshes = 0

    def send(self, cmd, timeout=3.0, **args):
        self.sent.append((cmd, args))
        if not self.running:
            return None
        if cmd == "record_start":
            return {"ok": True, "recording": {"id": "abc", "title": args.get("title")}}
        if cmd == "record_stop":
            return {"ok": True, "recording": {"id": "abc"}}
        return {"ok": True}

    def is_running(self):
        return self.running

    def refresh(self):
        self.refreshes += 1
        return self.running

    def status(self):
        return {"ok": True, "recording": None, "job": None} if self.running else None

    def ensure_running(self, wait_s=25.0):
        return "running" if self.running else "absent"


class ToolFailed(Exception):
    pass


def _run(server, fn):
    async def main():
        async with Client(server) as c:
            return await fn(c)

    return anyio.run(main)


def call(server, _tool: str, **args):
    async def fn(c):
        return await c.call_tool(_tool, args)

    r = _run(server, fn)
    text = r.content[0].text if r.content else ""
    if r.is_error:
        raise ToolFailed(text)
    return json.loads(text)


def tool_names(server) -> set[str]:
    async def fn(c):
        return await c.list_tools()

    return {t.name for t in _run(server, fn).tools}


@pytest.fixture
def link():
    return FakeLink()


@pytest.fixture
def server(service, link):
    return build_server(service, link)


@pytest.fixture
def call_done(service, wav, engine):
    """Un call importé, transcrit (plusieurs speakers) et résumé."""
    engine._segments = [
        Segment(0.0, 4.0, "Bonjour, on fait le point sur le budget marketing.", "SPEAKER_00"),
        Segment(4.0, 9.0, "Le devis ACME arrive vendredi.", "SPEAKER_01"),
        Segment(9.0, 12.0, "Parfait, on valide l'option 1.", "SPEAKER_00"),
    ]
    rec = service.import_file(wav, title="Point ACME", project="ACME", tags=["client"])
    service.jobs.run_pending()
    return service.repo.get_recording(rec.id)


# ─── Surface exposée ────────────────────────────────────────────────


def test_default_tools_have_no_delete(server):
    names = tool_names(server)
    assert {"search", "get_recording", "create_card", "process", "start_recording"} <= names
    assert not {"delete_recording", "delete_card"} & names


def test_read_only_and_permissions(service, link):
    service.settings.mcp_read_only = True
    names = tool_names(build_server(service, link))
    assert "search" in names and "list_boards" in names
    assert not {"create_card", "update_recording", "start_recording", "process"} & names

    service.settings.mcp_read_only = False
    service.settings.mcp_allow_record = False
    service.settings.mcp_allow_delete = True
    names = tool_names(build_server(service, link))
    assert "start_recording" not in names and {"delete_recording", "delete_card"} <= names


# ─── Lecture ────────────────────────────────────────────────────────


def test_search_groups_hits_by_recording(server, call_done):
    out = call(server, "search", query="devis")
    assert len(out["results"]) == 1
    hit = out["results"][0]
    assert hit["recording"]["id"] == call_done.short_id
    assert any(m["in"] == "segment" and m["start_s"] == 4.0 for m in hit["matches"])


def test_get_recording_has_summary_actions_and_speakers(server, call_done):
    out = call(server, "get_recording", recording_id=call_done.short_id)
    assert out["full_id"] == call_done.id and out["project"] == "ACME"
    assert out["summary"]["tldr"] == "Résumé de test."
    assert out["summary"]["actions"][0] == {"index": 0, "text": "Envoyer le devis", "done": False,
                                            "owner": "Nassim", "due": "vendredi"}
    assert out["transcript"]["speakers"] == {"SPEAKER_00": 7, "SPEAKER_01": 5}

    with pytest.raises(ToolFailed, match="introuvable"):
        call(server, "get_recording", recording_id="zzzz")


def test_list_recordings_filters(server, service, call_done, wav):
    other = service.import_file(wav, title="Perso", enqueue=False)
    service.db.connect().execute("UPDATE recordings SET started_at = ? WHERE id = ?", ("2026-01-15T10:00:00", other.id))

    assert [r["title"] for r in call(server, "list_recordings", project="ACME")["recordings"]] == ["Point ACME"]
    assert call(server, "list_recordings", project="ACME")["recordings"][0]["tldr"] == "Résumé de test."
    jan = call(server, "list_recordings", since="2026-01-15", until="2026-01-15")["recordings"]
    assert [r["title"] for r in jan] == ["Perso"]
    page = call(server, "list_recordings", limit=1)
    assert page["has_more"] and page["next_offset"] == 1
    with pytest.raises(ToolFailed, match="AAAA-MM-JJ"):
        call(server, "list_recordings", since="hier")


def test_transcript_is_paginated(server, service, wav, engine):
    engine._segments = [Segment(float(i), float(i + 1), f"Phrase numéro {i} " + "x" * 80, "A" if i % 2 else "B")
                        for i in range(40)]
    rec = service.import_file(wav, title="Long")
    service.jobs.run_pending()

    seen, start = [], 0.0
    while True:
        out = call(server, "get_transcript", recording_id=rec.short_id, start_s=start, max_chars=1000)
        seen += out["text"].splitlines()
        if out["complete"]:
            break
        start = out["next_start_s"]
    assert len(seen) == 40 and seen[0].startswith("[00:00] B: Phrase numéro 0")

    only_a = call(server, "get_transcript", recording_id=rec.short_id, speaker="a", max_chars=60000)
    assert len(only_a["text"].splitlines()) == 20
    window = call(server, "get_transcript", recording_id=rec.short_id, start_s=10, end_s=12)
    assert [line[:7] for line in window["text"].splitlines()] == ["[00:10]", "[00:11]"]


def test_projects_tags_and_status(server, call_done, link):
    assert call(server, "list_projects_and_tags") == {"projects": {"ACME": 1}, "tags": {"client": 1}}
    status = call(server, "get_status")
    assert status["app_running"] is False and status["recordings"] == 1
    assert status["permissions"] == {"write": True, "record": True, "delete": False}


# ─── Tâches ─────────────────────────────────────────────────────────


def test_card_lifecycle(server, service, link):
    past = (date.today() - timedelta(days=3)).isoformat()
    card = call(server, "create_card", title="Appeler Julie", due=past, labels=["Rouge", "blue"],
                checklist=["Préparer", "Envoyer"], description="Relance")
    assert card["board"] == "Mes tâches" and card["list"] == "À faire"
    assert card["labels"] == ["red", "blue"] and card["overdue"] is True
    assert [i["text"] for i in card["checklist"]] == ["Préparer", "Envoyer"]

    card = call(server, "update_card", card_id=card["id"], checklist_check=[0], checklist_remove=[1],
                checklist_add=["Archiver"], labels=[])
    assert card["checklist"] == [{"index": 0, "text": "Préparer", "done": True},
                                 {"index": 1, "text": "Archiver", "done": False}]
    assert "labels" not in card

    assert [c["id"] for c in call(server, "find_cards", overdue_only=True)["cards"]] == [card["id"]]
    card = call(server, "update_card", card_id=card["id"], due_done=True)
    assert call(server, "find_cards", overdue_only=True)["cards"] == []

    moved = call(server, "move_card", card_id=card["id"], list_name="terminé")
    assert moved["list"] == "Terminé"
    board = call(server, "get_board", query="julie")
    assert [len(lst["cards"]) for lst in board["lists"]] == [0, 0, 1]

    with pytest.raises(ToolFailed, match="Pas de liste « Bloqué »"):
        call(server, "move_card", card_id=card["id"], list_name="Bloqué")
    with pytest.raises(ToolFailed, match="Étiquette inconnue"):
        call(server, "create_card", title="x", labels=["fuchsia"])
    with pytest.raises(ToolFailed, match="checklist"):
        call(server, "update_card", card_id=card["id"], checklist_check=[9])
    assert link.refreshes >= 3


def test_boards_and_lists(server):
    b = call(server, "create_board", name="Perso")
    assert [x["name"] for x in b["lists"]] == ["À faire", "En cours", "Terminé"]
    lst = call(server, "create_list", board_id=b["id"], name="Bloqué")
    call(server, "rename_list", list_id=lst["id"], name="En attente")
    call(server, "rename_board", board_id=b["id"], name="Maison")
    card = call(server, "create_card", title="Plombier", board_id=b["id"], list_name="en attente")
    assert card["board"] == "Maison" and card["list"] == "En attente"
    boards = call(server, "list_boards")["boards"]
    assert boards[0]["name"] == "Maison" and boards[0]["lists"][3] == {"id": lst["id"], "name": "En attente", "cards": 1}


def test_actions_to_tasks_and_open_actions(server, service, call_done):
    out = call(server, "add_actions_to_tasks", recording_id=call_done.short_id)
    assert out["created"] == 1 and out["cards"][0]["title"] == "Envoyer le devis"
    assert call(server, "add_actions_to_tasks", recording_id=call_done.short_id)["created"] == 0
    again = call(server, "add_actions_to_tasks", recording_id=call_done.short_id, action_index=0)
    assert again["created"] == 0 and again["cards"][0]["id"] == out["cards"][0]["id"]

    actions = call(server, "list_open_actions")["actions"]
    assert len(actions) == 1 and actions[0]["owner"] == "Nassim" and actions[0]["card"]["list"] == "À faire"
    assert call(server, "list_open_actions", owner="julie")["actions"] == []

    call(server, "set_action_done", recording_id=call_done.short_id, action_index=0)
    assert call(server, "list_open_actions")["actions"] == []
    assert "- [x]" in (call_done.dir_path / "summary.md").read_text()


# ─── Écriture : enregistrements et traitement ───────────────────────


def test_update_recording_and_rename_speaker(server, service, call_done, link):
    out = call(server, "update_recording", recording_id=call_done.short_id, title="Point ACME Q4",
               project="", tags=["client", "q4"])
    assert out["title"] == "Point ACME Q4" and "project" not in out and out["tags"] == ["client", "q4"]

    out = call(server, "rename_speaker", recording_id=call_done.short_id, old_name="SPEAKER_01", new_name="Julie")
    assert out["renamed_segments"] == 1 and "Julie" in out["speakers"]
    assert "**Julie**" in (call_done.dir_path / "transcript.md").read_text()
    with pytest.raises(ToolFailed, match="speakers : SPEAKER_00, Julie"):
        call(server, "rename_speaker", recording_id=call_done.short_id, old_name="Bob", new_name="X")
    assert link.refreshes == 2


def test_process_queues_a_job_for_the_app(server, service, call_done, link):
    out = call(server, "process", recording_id=call_done.short_id, summary_only=True)
    assert out["kind"] == "summarize" and out["app"] == "absent" and "file" in out["note"]
    assert service.repo.get_job(out["job_id"]).status == JobStatus.QUEUED

    link.running = True
    out = call(server, "process", recording_id=call_done.short_id)
    assert out["app"] == "running"


def test_retry_failed(server, service, wav, summarizer):
    summarizer.fail_times = 99
    rec = service.import_file(wav)
    service.jobs.run_pending()
    assert service.repo.get_recording(rec.id).status == RecordingStatus.FAILED
    assert call(server, "retry_failed")["requeued"] == 1


def test_import_audio(server, wav):
    out = call(server, "import_audio", path=str(wav), title="Depuis Claude", project="X")
    assert out["recording"]["title"] == "Depuis Claude" and out["app"] == "absent"
    notes = wav.with_suffix(".txt")
    notes.write_text("pas de l'audio")
    with pytest.raises(ToolFailed, match="Format non supporté"):
        call(server, "import_audio", path=str(notes))


# ─── Enregistrement et suppression ──────────────────────────────────


def test_recording_goes_through_the_app(server, link):
    with pytest.raises(ToolFailed, match="n'est pas lancée"):
        call(server, "start_recording", title="Point")
    link.running = True
    out = call(server, "start_recording", title="Point", mic_only=True, tags=["a"])
    assert out["recording"]["title"] == "Point"
    assert link.sent[-1] == ("record_start", {"title": "Point", "project": None, "tags": ["a"], "system_audio": False})
    assert call(server, "stop_recording")["recording"]["id"] == "abc"


def test_delete_needs_confirmation(service, link, call_done):
    service.settings.mcp_allow_delete = True
    server = build_server(service, link)
    card = call(server, "create_card", title="Jetable")
    with pytest.raises(ToolFailed, match="non confirmée"):
        call(server, "delete_card", card_id=card["id"])
    assert call(server, "delete_card", card_id=card["id"], confirm=True)["title"] == "Jetable"

    with pytest.raises(ToolFailed, match="non confirmée"):
        call(server, "delete_recording", recording_id=call_done.short_id)
    call(server, "delete_recording", recording_id=call_done.short_id, confirm=True)
    assert service.repo.get_recording(call_done.id) is None and not call_done.dir_path.exists()


# ─── Resources et prompts ───────────────────────────────────────────


def test_resources_and_prompts(server, call_done):
    call(server, "create_card", title="Relancer")

    async def fn(c):
        summary = await c.read_resource(f"noter://recordings/{call_done.id}/summary")
        transcript = await c.read_resource(f"noter://recordings/{call_done.short_id}/transcript")
        board = await c.read_resource("noter://boards/1")
        prompts = await c.list_prompts()
        prompt = await c.get_prompt("mail_de_suivi", {"recording_id": call_done.short_id})
        return summary, transcript, board, prompts, prompt

    summary, transcript, board, prompts, prompt = _run(server, fn)
    assert "## TL;DR" in summary.contents[0].text
    assert "**SPEAKER_01** : Le devis ACME" in transcript.contents[0].text
    assert "- #1 Relancer" in board.contents[0].text
    assert {p.name for p in prompts.prompts} == {"preparer_call", "mail_de_suivi", "synthese_projet", "revue_des_taches"}
    assert call_done.short_id in prompt.messages[0].content.text


# ─── Installation ───────────────────────────────────────────────────


def test_desktop_config_is_merged_backed_up_and_removed(tmp_path):
    cfg = tmp_path / "Claude" / "claude_desktop_config.json"
    install.install_desktop(cfg, python=tmp_path / "py")
    assert json.loads(cfg.read_text())["mcpServers"]["noter"]["args"] == ["-m", "noter.mcp_server"]

    cfg.write_text(json.dumps({"mcpServers": {"autre": {"command": "x"}}, "theme": "dark"}))
    install.install_desktop(cfg, python=tmp_path / "py")
    data = json.loads(cfg.read_text())
    assert set(data["mcpServers"]) == {"autre", "noter"} and data["theme"] == "dark"
    assert data["mcpServers"]["noter"]["command"] == str(tmp_path / "py")
    assert list(cfg.parent.glob("*.bak"))
    assert install.is_installed_desktop(cfg)

    assert install.uninstall_desktop(cfg) and not install.uninstall_desktop(cfg)
    assert set(json.loads(cfg.read_text())["mcpServers"]) == {"autre"}

    cfg.write_text("{pas du json")
    with pytest.raises(ValueError):
        install.install_desktop(cfg)
    assert cfg.read_text() == "{pas du json"


def test_server_entry_keeps_noter_home(home):
    entry = install.server_entry()
    assert entry["env"] == {"NOTER_HOME": str(home)}
    cmd = install.claude_code_command()
    assert cmd[:8] == ["claude", "mcp", "add", "-s", "user", "noter", "-e", f"NOTER_HOME={home}"]
    assert cmd[-2:] == ["-m", "noter.mcp_server"]


def test_unnamed_speaker_can_be_renamed(server, service, wav, engine):
    engine._segments = [Segment(0.0, 2.0, "Salut.")]
    rec = service.import_file(wav)
    service.jobs.run_pending()
    assert call(server, "get_recording", recording_id=rec.short_id)["transcript"]["speakers"] == {"(sans nom)": 2}
    out = call(server, "rename_speaker", recording_id=rec.short_id, old_name="(sans nom)", new_name="Moi")
    assert out == {"renamed_segments": 1, "speakers": {"Moi": 2}}


def test_socket_path_stays_short(monkeypatch):
    from pathlib import Path

    from noter.applink import socket_path

    monkeypatch.setenv("NOTER_HOME", "/Users/x/Noter")
    assert socket_path() == Path("/Users/x/Noter/app.sock")
    monkeypatch.setenv("NOTER_HOME", "/Users/x/" + "d" * 120)
    long_ = socket_path()
    assert len(str(long_)) < 100 and long_ == socket_path() and long_.name.startswith("noter-")


def test_applink_without_app(home):
    from noter.applink import AppLink

    link = AppLink()
    assert link.send("status") is None and not link.is_running()
    assert link.ensure_running(wait_s=0.1) == "absent"  # pas de Noter.app hors macOS
