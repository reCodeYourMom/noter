"""Icônes vectorielles (traits 1.75px, grille 24) rendues en QIcon dans la couleur demandée."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

PATHS: dict[str, str] = {
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
    "list": '<path d="M4 6h16M4 12h16M4 18h10"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "alert": '<path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17h.01"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>',
    "refresh": '<path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/>',
    "folder": '<path d="M3 7h5l2 2h11v10H3z"/>',
    "file": '<path d="M6 2h9l5 5v15H6z"/><path d="M14 2v6h6"/>',
    "more": '<circle cx="5" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="19" cy="12" r="1.3" fill="currentColor"/>',
    "import": '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 17v3h16v-3"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
    "copy": '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
    "play": '<path d="M7 4l13 8-13 8z" fill="currentColor" stroke="none"/>',
    "pause": '<rect x="6" y="4" width="4" height="16" fill="currentColor" stroke="none"/><rect x="14" y="4" width="4" height="16" fill="currentColor" stroke="none"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    "check": '<path d="M5 12l5 5 9-10"/>',
    "tag": '<path d="M3 12V4h8l9 9-8 8z"/><circle cx="7.5" cy="8.5" r="1" fill="currentColor"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "board": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16M15 4v10"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "checklist": '<rect x="3" y="4" width="4" height="4" rx="1"/><path d="M4 6.2l.7.7 1.3-1.5"/><path d="M10 6h11M10 12h11M10 18h11"/><rect x="3" y="10" width="4" height="4" rx="1"/><rect x="3" y="16" width="4" height="4" rx="1"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "text": '<path d="M4 6h16M4 12h16M4 18h9"/>',
    "chevron": '<path d="M6 9l6 6 6-6"/>',
    "chevron_left": '<path d="M15 6l-6 6 6 6"/>',
    "chevron_right": '<path d="M9 6l6 6-6 6"/>',
    "sparkle": '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
    "flag": '<path d="M5 21V4h11l-2 4 2 4H5"/>',
    "wave": '<path d="M3 12h2M7 8v8M11 5v14M15 9v6M19 11v2"/>',
}


def svg(name: str, color: str, size: int = 24, stroke: float = 1.75) -> bytes:
    body = PATHS[name]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round" '
        f'color="{color}">{body}</svg>'
    ).encode()


_cache: dict[tuple[str, str, int], QIcon] = {}


def icon(name: str, color: str | QColor, size: int = 16) -> QIcon:
    col = color.name(QColor.NameFormat.HexArgb) if isinstance(color, QColor) else color
    key = (name, col, size)
    if key in _cache:
        return _cache[key]
    ic = QIcon()
    for scale in (1, 2):
        px = size * scale
        pm = QPixmap(px, px)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        QSvgRenderer(QByteArray(svg(name, col))).render(p, QRectF(0, 0, px, px))
        p.end()
        pm.setDevicePixelRatio(scale)
        ic.addPixmap(pm)
    _cache[key] = ic
    return ic


# ─── Icônes qui suivent le thème ────────────────────────────────────

_bound: dict[int, tuple[object, str, str, int]] = {}


def bind(target, name: str, token: str, size: int = 16):
    """Pose l'icône `name` dans la couleur du token `token` (ex. "ink_3") et la repose à chaque changement
    de thème. `target` : bouton ou QAction (setIcon), ou QLabel (setPixmap). Retourne `target`."""
    from noter.ui import theme

    _set(target, name, getattr(theme.current(), token), size)
    key = id(target)
    if key not in _bound and hasattr(target, "destroyed"):
        target.destroyed.connect(lambda *_a, k=key: _bound.pop(k, None))
    _bound[key] = (target, name, token, size)
    return target


def _set(target, name: str, color: str, size: int) -> None:
    ic = icon(name, color, size)
    if hasattr(target, "setIcon"):
        target.setIcon(ic)
    else:
        target.setPixmap(ic.pixmap(size, size))


def _rebind(tokens) -> None:
    import shiboken6

    for key, (target, name, token, size) in list(_bound.items()):
        if not shiboken6.isValid(target):
            _bound.pop(key, None)
            continue
        _set(target, name, getattr(tokens, token), size)


def _register() -> None:
    from noter.ui import theme

    theme.on_change(_rebind)


_register()
