"""Point d'entrée de l'app desktop : `noter-app`."""
from __future__ import annotations

import logging
import signal
import sys

from noter.config import load_settings
from noter.logging_setup import setup_logging

logger = logging.getLogger("noter.ui")


def main() -> int:
    settings = load_settings()
    setup_logging(settings.log_path, console=False)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from noter import notify
    from noter.service import Service
    from noter.ui.bridge import ServiceBridge
    from noter.ui.main_window import MainWindow
    from noter.ui.tray import Tray

    app = QApplication(sys.argv)
    app.setApplicationName("Noter")
    app.setApplicationDisplayName("Noter")
    app.setOrganizationName("Noter")
    app.setQuitOnLastWindowClosed(False)

    from PySide6.QtGui import QFont, QIcon

    from noter.ui import theme

    theme.load_fonts()
    app.setFont(QFont(theme.SANS, 13))
    theme.apply(app)
    icon_path = theme.FONT_DIR.parent / "AppIcon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    try:  # suivre le passage clair/sombre du système
        app.styleHints().colorSchemeChanged.connect(lambda _s: theme.apply(app))
    except Exception:  # noqa: BLE001
        pass

    # Instance unique : si Noter tourne déjà, on lui demande d'afficher sa fenêtre et on sort.
    from noter.ui.single_instance import SingleInstance

    instance = SingleInstance("noter-app")
    if not instance.acquire():
        instance.notify_existing("show")
        logger.info("Noter tourne déjà — fenêtre existante réactivée")
        return 0

    service = Service(settings)
    service.start()
    bridge = ServiceBridge(service)
    window = MainWindow(bridge)
    tray = Tray(app)

    # Notifications système → tray (et plus osascript)
    notify.add_handler(lambda t, m: bridge.notification.emit(t, m))
    bridge.notification.connect(tray.message)

    tray.record_requested.connect(bridge.start_recording)
    tray.stop_requested.connect(bridge.stop_recording)
    def show_window():
        window.show()
        window.raise_()
        window.activateWindow()

    tray.open_requested.connect(show_window)
    instance.message_received.connect(lambda msg: show_window() if msg == "show" else None)
    bridge.recording_started.connect(lambda _: tray.set_recording(True))
    bridge.recording_stopped.connect(lambda _: tray.set_recording(False))
    bridge.recording_tick.connect(lambda elapsed, _lv: tray.set_elapsed(elapsed))

    def refresh_status():
        cur = service.jobs.current
        tray.set_status(f"{cur.kind} en cours" if cur else "inactif")

    status_timer = QTimer()
    status_timer.setInterval(2000)
    status_timer.timeout.connect(refresh_status)
    status_timer.start()

    def quit_app():
        if service.is_recording:
            from PySide6.QtWidgets import QMessageBox

            if QMessageBox.question(window, "Enregistrement en cours", "Arrêter l'enregistrement et quitter ?") != QMessageBox.StandardButton.Yes:
                return
        service.stop()
        app.quit()

    tray.quit_requested.connect(quit_app)
    signal.signal(signal.SIGINT, lambda *_: quit_app())
    sig_timer = QTimer()  # laisse Python traiter SIGINT
    sig_timer.setInterval(500)
    sig_timer.timeout.connect(lambda: None)
    sig_timer.start()

    window.show()
    code = app.exec()
    service.stop()
    return code


if __name__ == "__main__":
    sys.exit(main())
