"""Diagnostic : pourquoi le plein écran macOS retombe sur le bureau.

macOS sort une fenêtre de son Space plein écran dès qu'une *autre* fenêtre de premier niveau s'affiche
(écran noir, retour au bureau). Les coupables sont souvent involontaires : un widget encore sans parent
au moment où il est affiché devient une fenêtre.

Activé par `NOTER_DEBUG_WINDOWS=1` dans l'environnement ou `debug_windows=true` dans `~/Noter/.env`.
Chaque fenêtre affichée est journalisée dans `~/Noter/noter.log` avec la pile d'appels qui l'a créée,
ainsi que chaque perte du plein écran de la fenêtre principale.
"""
from __future__ import annotations

import logging
import traceback
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QWidget

logger = logging.getLogger(__name__)

_SRC = str(Path(__file__).resolve().parent.parent)  # …/noter : on ne garde que nos propres frames


def _window_kind(w: QWidget) -> str:
    """Nom du type de fenêtre (Window, Dialog, Popup, ToolTip…)."""
    flag = w.windowFlags() & Qt.WindowType.WindowType_Mask
    for name in ("Dialog", "Popup", "ToolTip", "Tool", "SplashScreen", "Drawer", "Sheet", "SubWindow", "Window"):
        if flag == getattr(Qt.WindowType, name):
            return name
    return str(int(flag))


def _culprit() -> str:
    """La pile d'appels, réduite au code de Noter : la ligne qui affiche la fenêtre."""
    frames = [f for f in traceback.extract_stack()[:-2] if f.filename.startswith(_SRC)]
    return " ← ".join(f"{Path(f.filename).name}:{f.lineno} {f.name}" for f in reversed(frames[-6:])) or "(hors Noter)"


class WindowTracer(QObject):
    """Filtre d'événements applicatif : journalise les fenêtres et les changements d'état."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._fullscreen: set[int] = set()

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:  # noqa: N802
        try:
            if isinstance(obj, QWidget) and obj.isWindow():
                if ev.type() == QEvent.Type.Show:
                    self._on_show(obj)
                elif ev.type() == QEvent.Type.WindowStateChange:
                    self._on_state(obj)
        except Exception:  # noqa: BLE001 — un diagnostic ne doit jamais casser l'app
            logger.debug("windowtrace en erreur", exc_info=True)
        return False

    def _on_show(self, w: QWidget) -> None:
        kind = _window_kind(w)
        desc = f"{type(w).__name__}(objectName={w.objectName()!r}, titre={w.windowTitle()!r}, type={kind})"
        # Une fenêtre « Window » qui n'est pas la fenêtre principale est presque sûrement une erreur :
        # c'est elle qui fait sortir macOS du plein écran.
        level = logging.WARNING if kind == "Window" and not w.isMaximized() and w.windowTitle() != "Noter" else logging.INFO
        logger.log(level, "fenêtre affichée : %s — depuis %s", desc, _culprit())

    def _on_state(self, w: QWidget) -> None:
        key = id(w)
        now = bool(w.windowState() & Qt.WindowState.WindowFullScreen)
        before = key in self._fullscreen
        if now == before:
            return
        if now:
            self._fullscreen.add(key)
            logger.info("plein écran activé : %s", type(w).__name__)
        else:
            self._fullscreen.discard(key)
            logger.warning("PLEIN ÉCRAN PERDU : %s — la fenêtre affichée juste avant est la coupable", type(w).__name__)


def install(app: QApplication) -> WindowTracer:
    tracer = WindowTracer(app)
    app.installEventFilter(tracer)
    logger.warning("diagnostic des fenêtres actif (NOTER_DEBUG_WINDOWS) — journal : voir ~/Noter/noter.log")
    return tracer
