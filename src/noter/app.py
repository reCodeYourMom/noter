"""App menu bar macOS (rumps). Client léger du Service — remplacée par l'UI Qt en phase 2."""
from __future__ import annotations

import logging
import subprocess
import threading

from noter.config import load_settings
from noter.logging_setup import setup_logging
from noter.models import Job, format_timestamp

logger = logging.getLogger("noter.app")


def main() -> None:
    settings = load_settings()
    setup_logging(settings.log_path, console=False)

    import rumps

    from noter import notify
    from noter.service import Service

    class NoterApp(rumps.App):
        def __init__(self):
            super().__init__(name="Noter", title="", icon=_icon_path(), template=True, quit_button=None)
            self.svc = Service(settings)
            self.svc.start()
            self.svc.jobs.subscribe(self._on_job)
            self._dirty = threading.Event()

            self.m_rec_sys = rumps.MenuItem("Enregistrer (micro + système)", callback=lambda _: self._start(True))
            self.m_rec_mic = rumps.MenuItem("Enregistrer (micro seul)", callback=lambda _: self._start(False))
            self.m_stop = rumps.MenuItem("Arrêter l'enregistrement", callback=self._stop)
            self.m_stop.set_callback(None)
            self.m_recent = rumps.MenuItem("Derniers enregistrements")
            self.m_jobs = rumps.MenuItem("Traitement : inactif")
            self.m_jobs.set_callback(None)
            self.menu = [
                self.m_rec_sys, self.m_rec_mic, self.m_stop, None,
                self.m_recent, None,
                rumps.MenuItem("Ouvrir le dossier Noter", callback=lambda _: subprocess.run(["open", str(settings.data_dir)])),
                self.m_jobs, None,
                rumps.MenuItem("Quitter", callback=self._quit),
            ]
            self._refresh_recent()

        # ─── Actions ────────────────────────────────────────────────

        def _start(self, with_system: bool):
            try:
                rec = self.svc.start_recording(with_system_audio=with_system)
            except Exception as e:  # noqa: BLE001
                rumps.alert("Noter", str(e))
                return
            self.m_rec_sys.set_callback(None)
            self.m_rec_mic.set_callback(None)
            self.m_stop.set_callback(self._stop)
            self.title = "● 00:00"
            notify.notify("Noter", f"Enregistrement démarré ({rec.source})")

        def _stop(self, _):
            if not self.svc.is_recording:
                return
            rec = self.svc.stop_recording()
            self.m_rec_sys.set_callback(lambda _: self._start(True))
            self.m_rec_mic.set_callback(lambda _: self._start(False))
            self.m_stop.set_callback(None)
            self.title = ""
            notify.notify("Noter", f"Enregistré ({rec.duration_text}) — traitement en cours")
            self._dirty.set()

        def _quit(self, _):
            if self.svc.is_recording:
                if rumps.alert("Enregistrement en cours", "Arrêter et quitter ?", ok="Quitter", cancel="Annuler") != 1:
                    return
            self.svc.stop()
            rumps.quit_application()

        # ─── Rafraîchissement ───────────────────────────────────────

        def _on_job(self, job: Job):
            self._dirty.set()

        @rumps.timer(1)
        def _tick(self, _):
            if self.svc.is_recording and self.svc.recorder:
                self.title = f"● {format_timestamp(self.svc.recorder.elapsed)}"
            cur = self.svc.jobs.current
            pending = self.svc.repo.pending_job_count()
            self.m_jobs.title = f"Traitement : {cur.kind} ({pending} en file)" if cur else "Traitement : inactif"
            if self._dirty.is_set():
                self._dirty.clear()
                self._refresh_recent()

        def _refresh_recent(self):
            for k in list(self.m_recent.keys()):
                del self.m_recent[k]
            recs = self.svc.repo.list_recordings(limit=10)
            if not recs:
                self.m_recent.add(rumps.MenuItem("Aucun enregistrement"))
                return
            for r in recs:
                item = rumps.MenuItem(f"{r.started_at:%d/%m %H:%M} — {r.display_title} [{r.duration_text}] · {r.status}")
                item.set_callback(lambda _, d=r.dir_path: subprocess.run(["open", str(d)]))
                self.m_recent.add(item)

    try:
        from AppKit import NSApplication

        NSApplication.sharedApplication().setActivationPolicy_(1)  # pas d'icône Dock
    except Exception:  # noqa: BLE001
        pass

    NoterApp().run()


def _icon_path() -> str | None:
    from pathlib import Path

    for p in (Path(__file__).resolve().parents[2] / "icon.png", Path(__file__).parent / "icon.png"):
        if p.exists():
            return str(p)
    return None


if __name__ == "__main__":
    main()
