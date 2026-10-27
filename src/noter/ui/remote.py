"""Commandes reçues sur le socket de l'app (voir noter.applink) : exécutées dans le thread Qt."""
from __future__ import annotations

from collections.abc import Callable

from noter.models import Recording
from noter.ui.bridge import ServiceBridge


def recording_info(rec: Recording) -> dict:
    return {
        "id": rec.id, "title": rec.display_title, "status": str(rec.status),
        "started_at": rec.started_at.isoformat(timespec="seconds"), "duration_s": rec.duration_s,
        "project": rec.project, "tags": rec.tags, "source": str(rec.source),
    }


class RemoteCommands:
    def __init__(self, bridge: ServiceBridge, show_window: Callable[[], None]):
        self.bridge = bridge
        self.service = bridge.service
        self.show_window = show_window

    def handle(self, req: dict) -> dict:
        cmd = req.get("cmd")
        fn = getattr(self, f"_cmd_{cmd}", None) if isinstance(cmd, str) else None
        if fn is None:
            return {"ok": False, "error": f"commande inconnue : {cmd}"}
        return {"ok": True, **(fn(req) or {})}

    def _cmd_show(self, _req: dict) -> None:
        self.show_window()

    def _cmd_refresh(self, _req: dict) -> None:
        self.bridge.data_changed.emit()

    def _cmd_status(self, _req: dict) -> dict:
        svc = self.service
        out: dict = {"recording": None, "job": None, "pending_jobs": svc.repo.pending_job_count()}
        if svc.is_recording and svc.current_recording is not None:
            out["recording"] = {
                **recording_info(svc.current_recording),
                "elapsed_s": round(svc.recorder.elapsed, 1) if svc.recorder else None,
                "system_audio": bool(svc.recorder and svc.recorder.system_audio_captured),
            }
        job = svc.jobs.current
        if job is not None:
            out["job"] = {"id": job.id, "kind": str(job.kind), "recording_id": job.recording_id}
        return out

    def _cmd_record_start(self, req: dict) -> dict:
        if self.service.is_recording:
            raise RuntimeError("Un enregistrement est déjà en cours")
        tags = req.get("tags") or []
        rec = self.bridge.start_recording_or_raise(
            with_system_audio=bool(req.get("system_audio", True)), title=req.get("title") or None,
            project=req.get("project") or None, tags=[str(t) for t in tags],
        )
        self.show_window()  # un enregistrement lancé à distance doit se voir
        return {"recording": recording_info(rec)}

    def _cmd_record_stop(self, _req: dict) -> dict:
        rec = self.bridge.stop_recording_or_raise()
        if rec is None:
            raise RuntimeError("Aucun enregistrement en cours")
        return {"recording": recording_info(rec)}
