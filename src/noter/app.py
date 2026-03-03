"""Noter — App menu bar macOS."""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

# Charger le .env AVANT tout import de config
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")

import rumps

from noter.audio.devices import find_blackhole, find_default_mic
from noter.audio.recorder import Recorder, save_recording, run_pipeline
from noter.config import settings
from noter.storage.database import get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("noter.app")

TITLE_IDLE = "Noter"
TITLE_RECORDING = "REC"
TITLE_PROCESSING = "..."


class NoterApp(rumps.App):
    def __init__(self):
        super().__init__(
            name="Noter",
            title=TITLE_IDLE,
            quit_button=None,
        )

        self._recorder: Recorder | None = None
        self._record_thread: threading.Thread | None = None
        self._server_thread: threading.Thread | None = None

        # Menu items
        self._record_system = rumps.MenuItem("Enregistrer (Mic + Système)", callback=self._on_record_system)
        self._record_mic = rumps.MenuItem("Enregistrer (Mic seul)", callback=self._on_record_mic)
        self._stop_btn = rumps.MenuItem("Arrêter", callback=self._on_stop)
        self._stop_btn.set_callback(None)  # Grisé par défaut

        self._sep1 = rumps.separator

        self._recordings_menu = rumps.MenuItem("Derniers enregistrements")
        self._refresh_recordings()

        self._sep2 = rumps.separator

        self._server_status = rumps.MenuItem(f"Serveur :{settings.server_port}")
        self._server_status.set_callback(None)  # Non cliquable, juste informatif

        self._sep3 = rumps.separator

        self._quit_btn = rumps.MenuItem("Quitter", callback=self._on_quit)

        self.menu = [
            self._record_system,
            self._record_mic,
            self._stop_btn,
            self._sep1,
            self._recordings_menu,
            self._sep2,
            self._server_status,
            self._sep3,
            self._quit_btn,
        ]

        # Démarrer le serveur automatiquement
        self._start_server()

    # ─── Recording ──────────────────────────────────────────────

    def _start_recording(self, mode: str):
        """Lance un enregistrement en background."""
        if self._recorder and self._recorder.is_recording:
            rumps.notification("Noter", "", "Un enregistrement est déjà en cours")
            return

        try:
            self._recorder = Recorder(mode=mode)
            self._recorder.start_async()
        except RuntimeError as e:
            rumps.notification("Noter", "Erreur", str(e))
            self._recorder = None
            return

        # UI : mode enregistrement
        self._record_system.set_callback(None)
        self._record_mic.set_callback(None)
        self._stop_btn.set_callback(self._on_stop)
        self.title = "REC 00:00"

        rumps.notification("Noter", "Enregistrement démarré", f"Mode: {mode}")

    def _on_record_system(self, sender):
        self._start_recording("system+mic")

    def _on_record_mic(self, sender):
        self._start_recording("mic_only")

    def _on_stop(self, sender):
        """Arrête l'enregistrement et lance le pipeline."""
        if not self._recorder or not self._recorder.is_recording:
            return

        recorder = self._recorder
        self._recorder = None

        # Stop recording
        recorder.stop()
        duration = recorder.elapsed
        dur_str = f"{int(duration // 60)}:{int(duration % 60):02d}"

        # UI : mode processing
        self.title = "Noter..."
        self._stop_btn.set_callback(None)

        rumps.notification("Noter", f"Enregistrement terminé ({dur_str})", "Transcription en cours...")

        # Pipeline en background
        def pipeline():
            try:
                recording_id = save_recording(recorder)
                logger.info(f"Pipeline démarré: {recording_id[:8]}")
                run_pipeline(recording_id)
                rumps.notification("Noter", "Résumé prêt", f"Enregistrement {recording_id[:8]} traité")
                logger.info(f"Pipeline terminé: {recording_id[:8]}")
            except Exception as e:
                logger.error(f"Erreur pipeline: {e}")
                rumps.notification("Noter", "Erreur", str(e)[:100])
            finally:
                self._reset_ui()
                self._refresh_recordings()

        threading.Thread(target=pipeline, daemon=True).start()

    def _reset_ui(self):
        """Remet l'UI en mode idle."""
        self.title = TITLE_IDLE
        self._record_system.set_callback(self._on_record_system)
        self._record_mic.set_callback(self._on_record_mic)
        self._stop_btn.set_callback(None)

    # ─── Timer : mise à jour durée ──────────────────────────────

    @rumps.timer(1)
    def _update_timer(self, sender):
        """Met à jour le titre avec la durée d'enregistrement."""
        if self._recorder and self._recorder.is_recording:
            elapsed = self._recorder.elapsed
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            self.title = f"REC {minutes:02d}:{seconds:02d}"

    # ─── Recordings list ────────────────────────────────────────

    def _refresh_recordings(self):
        """Rafraîchit le sous-menu des derniers enregistrements."""
        try:
            # Vider le sous-menu existant
            keys_to_remove = list(self._recordings_menu.keys())
            for key in keys_to_remove:
                del self._recordings_menu[key]

            db = get_db()
            rows = db.execute(
                "SELECT r.id, r.title, r.started_at, r.duration_s, r.mode, s.tldr "
                "FROM recordings r LEFT JOIN summaries s ON r.id = s.recording_id "
                "ORDER BY r.started_at DESC LIMIT 10"
            ).fetchall()

            if not rows:
                self._recordings_menu.add(rumps.MenuItem("Aucun enregistrement"))
                return

            for row in rows:
                rid, title, started, duration, mode, tldr = row
                dur_str = f"{int((duration or 0) // 60)}min" if duration else "?"
                time_str = started[11:16] if started and len(started) > 16 else "?"
                label = f"{time_str} — {title or mode} [{dur_str}]"
                item = rumps.MenuItem(label)
                if tldr:
                    item.set_callback(lambda s, t=tldr, r=rid: self._show_summary(t, r))
                self._recordings_menu.add(item)
        except Exception as e:
            logger.error(f"Erreur refresh recordings: {e}")

    def _show_summary(self, tldr: str, recording_id: str):
        """Affiche le résumé dans une alerte."""
        rumps.alert(
            title=f"Résumé — {recording_id[:8]}",
            message=tldr[:500],
            ok="OK",
        )

    # ─── Server (auto-start) ─────────────────────────────────────

    def _start_server(self):
        """Lance le serveur FastAPI automatiquement au démarrage."""
        self._server_thread = threading.Thread(target=self._run_server, daemon=True)
        self._server_thread.start()
        logger.info(f"Serveur démarré sur le port {settings.server_port}")

    def _run_server(self):
        """Lance le serveur FastAPI en background."""
        import uvicorn
        uvicorn.run(
            "noter.server.api:api",
            host=settings.server_host,
            port=settings.server_port,
            log_level="warning",
        )

    # ─── Quit ───────────────────────────────────────────────────

    def _on_quit(self, sender):
        """Quitte l'app proprement."""
        if self._recorder and self._recorder.is_recording:
            response = rumps.alert(
                title="Enregistrement en cours",
                message="Un enregistrement est en cours. Arrêter et quitter ?",
                ok="Quitter",
                cancel="Annuler",
            )
            if response != 1:
                return
            self._recorder.stop()
            save_recording(self._recorder)

        rumps.quit_application()


def main():
    """Point d'entrée de l'app menu bar."""
    # S'assurer que le dossier data existe
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    # Initialiser la DB
    get_db()

    app = NoterApp()
    app.run()

    # Note: pour cacher l'icône du Dock, LSUIElement=true dans Info.plist
    # du .app bundle s'en charge


if __name__ == "__main__":
    main()
