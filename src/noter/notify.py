"""Notifications système, sans dépendance à une lib UI.

macOS : `osascript` (fonctionne depuis n'importe quel processus).
Ailleurs : simple log. Un handler peut être branché (l'UI Qt s'y abonne).
"""
from __future__ import annotations

import logging
import platform
import subprocess
from collections.abc import Callable

logger = logging.getLogger(__name__)

Handler = Callable[[str, str], None]
_handlers: list[Handler] = []


def add_handler(h: Handler) -> None:
    _handlers.append(h)


def remove_handler(h: Handler) -> None:
    if h in _handlers:
        _handlers.remove(h)


def notify(title: str, message: str) -> None:
    logger.info("[notif] %s — %s", title, message)
    if _handlers:
        for h in list(_handlers):
            try:
                h(title, message)
            except Exception:  # noqa: BLE001
                logger.exception("handler de notification en erreur")
        return
    if platform.system() == "Darwin":
        safe_t = title.replace('"', "'")
        safe_m = message.replace('"', "'")
        try:
            subprocess.run(
                ["osascript", "-e", f'display notification "{safe_m}" with title "{safe_t}"'],
                check=False, capture_output=True, timeout=5,
            )
        except Exception:  # noqa: BLE001
            logger.debug("osascript indisponible", exc_info=True)
