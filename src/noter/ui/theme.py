"""Design tokens → palette Qt + feuille de style.

Deux thèmes (clair, sombre) et trois couleurs : iris, corail, menthe, réunies dans un dégradé « aurora ».
"""
from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication, QPalette

logger = logging.getLogger(__name__)

FONT_DIR = Path(__file__).parent / "assets" / "fonts"
SANS = "IBM Plex Sans"
MONO = "IBM Plex Mono"


@dataclass(frozen=True)
class Tokens:
    name: str
    canvas: str      # fond de fenêtre
    panel: str       # colonnes
    panel_2: str     # surface +1 (timeline, statut)
    inset: str       # champs, encoches
    ink: str         # texte principal
    ink_2: str       # texte secondaire
    ink_3: str       # métadonnées
    ink_4: str       # désactivé / traits
    line: str        # bordure standard (rgba)
    line_2: str      # bordure emphase (rgba)
    sel: str         # survol (rgba, légèrement teinté iris)
    # Les trois couleurs : iris (marque, actions, sélection, traitement), corail (REC, retard, erreur),
    # menthe (terminé, réussi). Chacune existe en aplat, en texte lisible (`*_ink`) et en fond doux.
    accent: str
    accent_hover: str
    accent_ink: str
    accent_soft: str
    rec: str
    rec_ink: str
    rec_soft: str
    ok: str
    ok_ink: str
    ok_soft: str
    busy: str        # traitement en cours = iris
    busy_soft: str
    speakers: tuple[str, ...]
    is_dark: bool
    list_bg: str     # fond d'une liste de board
    card_bg: str     # fond d'une carte
    card_hover: str
    labels: dict[str, str]  # étiquettes de cartes (clé → couleur)


LIGHT = Tokens(
    name="light",
    canvas="#F4F3FA", panel="#FFFFFF", panel_2="#F8F7FD", inset="#EEEDF6",
    ink="#1A1830", ink_2="#4A4862", ink_3="#7D7A96", ink_4="#B9B7CC",
    line="rgba(26,24,48,0.07)", line_2="rgba(26,24,48,0.13)", sel="rgba(109,94,245,0.07)",
    accent="#6D5EF5", accent_hover="#5B4BE8", accent_ink="#5847E0", accent_soft="rgba(109,94,245,0.12)",
    rec="#FF6B5E", rec_ink="#DE4636", rec_soft="rgba(255,107,94,0.14)",
    ok="#1FBF8F", ok_ink="#0B8763", ok_soft="rgba(31,191,143,0.15)",
    busy="#6D5EF5", busy_soft="rgba(109,94,245,0.12)",
    speakers=("#6D5EF5", "#FF6B5E", "#1FBF8F", "#3D9BF0", "#F0A12B", "#DD5AAE"),
    is_dark=False,
    list_bg="#ECEBF5", card_bg="#FFFFFF", card_hover="#FBFAFF",
    labels={"green": "#1FBF8F", "yellow": "#F5BE3D", "orange": "#FF9457", "red": "#FF6B5E", "purple": "#6D5EF5", "blue": "#3D9BF0"},
)

DARK = Tokens(
    name="dark",
    canvas="#121120", panel="#191828", panel_2="#1F1E31", inset="#15141F",
    ink="#EEEDF7", ink_2="#B9B7CC", ink_3="#8784A0", ink_4="#514E68",
    line="rgba(255,255,255,0.06)", line_2="rgba(255,255,255,0.11)", sel="rgba(140,128,255,0.10)",
    accent="#8C80FF", accent_hover="#9D93FF", accent_ink="#ABA2FF", accent_soft="rgba(140,128,255,0.18)",
    rec="#FF7A6E", rec_ink="#FF9086", rec_soft="rgba(255,122,110,0.18)",
    ok="#3DDBA8", ok_ink="#56E4B7", ok_soft="rgba(61,219,168,0.16)",
    busy="#8C80FF", busy_soft="rgba(140,128,255,0.18)",
    speakers=("#8C80FF", "#FF7A6E", "#3DDBA8", "#6CB8FF", "#FFB547", "#F07CC8"),
    is_dark=True,
    list_bg="#1A1929", card_bg="#24233A", card_hover="#2A2944",
    labels={"green": "#3DDBA8", "yellow": "#FFC75A", "orange": "#FFA06B", "red": "#FF7A6E", "purple": "#8C80FF", "blue": "#6CB8FF"},
)

_current: Tokens = LIGHT


def aurora_stops(t: Tokens) -> list[tuple[float, str]]:
    """Le dégradé signature : menthe → iris → corail."""
    return [(0.0, t.ok), (0.5, t.accent), (1.0, t.rec)]


def qss_gradient(stops: list[tuple[float, str]], x2: float = 1, y2: float = 0) -> str:
    inner = ", ".join(f"stop:{pos} {color}" for pos, color in stops)
    return f"qlineargradient(x1:0, y1:0, x2:{x2}, y2:{y2}, {inner})"


def cta_gradient(t: Tokens) -> str:
    """Bouton Enregistrer : corail → iris."""
    return qss_gradient([(0.0, t.rec), (1.0, t.accent)])


def soft(color: str | QColor, alpha: float) -> QColor:
    c = QColor(color) if isinstance(color, str) else QColor(color)
    c.setAlphaF(alpha)
    return c


def rgba(color: str, alpha: float) -> str:
    """Couleur hexadécimale → `rgba(...)` pour la feuille de style."""
    c = QColor(color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


def gradient_color(t: Tokens, frac: float) -> QColor:
    """Couleur du dégradé aurora à la position `frac` (0..1), pour le dessin au QPainter."""
    stops = aurora_stops(t)
    frac = max(0.0, min(1.0, frac))
    for (p0, c0), (p1, c1) in zip(stops, stops[1:], strict=False):
        if frac <= p1:
            k = (frac - p0) / (p1 - p0) if p1 > p0 else 0.0
            a, b = QColor(c0), QColor(c1)
            return QColor(
                round(a.red() + (b.red() - a.red()) * k),
                round(a.green() + (b.green() - a.green()) * k),
                round(a.blue() + (b.blue() - a.blue()) * k),
            )
    return QColor(stops[-1][1])


def _asset(name: str, color: str, stroke: float = 1.75) -> str:
    """Icône SVG écrite dans un cache, pour les `image: url(...)` de la feuille de style."""
    from noter.ui import icons

    folder = Path(tempfile.gettempdir()) / "noter-ui"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}-{color.lstrip('#')}-{stroke}.svg"
    if not path.exists():
        path.write_bytes(icons.svg(name, color, stroke=stroke))
    return path.as_posix()


def current() -> Tokens:
    return _current


def system_prefers_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:  # noqa: BLE001
        return False


def load_fonts() -> bool:
    ok = True
    for f in sorted(FONT_DIR.glob("*.ttf")):
        if QFontDatabase.addApplicationFont(str(f)) < 0:
            logger.warning("Police non chargée : %s", f.name)
            ok = False
    return ok


def qcolor(value: str) -> QColor:
    if value.startswith("rgba("):
        r, g, b, a = (v.strip() for v in value[5:-1].split(","))
        c = QColor(int(r), int(g), int(b))
        c.setAlphaF(float(a))
        return c
    return QColor(value)


def speaker_color(t: Tokens, name: str | None) -> QColor:
    if not name:
        return qcolor(t.ink_4)
    h = 0
    for ch in name:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return QColor(t.speakers[h % len(t.speakers)])


def initials(name: str | None) -> str:
    if not name:
        return "?"
    parts = [p for p in name.replace("_", " ").split() if p]
    if len(parts) >= 2 and parts[0].isalpha():
        return (parts[0][0] + parts[-1][0]).upper()
    core = "".join(ch for ch in name if ch.isalnum())
    return (core[-1] if name.upper().startswith("SPEAKER") and core else core[:1] or "?").upper()


def build_palette(t: Tokens) -> QPalette:
    p = QPalette()
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
        p.setColor(group, QPalette.ColorRole.Window, qcolor(t.canvas))
        p.setColor(group, QPalette.ColorRole.Base, qcolor(t.panel))
        p.setColor(group, QPalette.ColorRole.AlternateBase, qcolor(t.panel_2))
        p.setColor(group, QPalette.ColorRole.Text, qcolor(t.ink))
        p.setColor(group, QPalette.ColorRole.WindowText, qcolor(t.ink))
        p.setColor(group, QPalette.ColorRole.ButtonText, qcolor(t.ink))
        p.setColor(group, QPalette.ColorRole.Button, qcolor(t.panel_2))
        p.setColor(group, QPalette.ColorRole.PlaceholderText, qcolor(t.ink_4))
        p.setColor(group, QPalette.ColorRole.Highlight, qcolor(t.accent))
        p.setColor(group, QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
        p.setColor(group, QPalette.ColorRole.Link, qcolor(t.accent_ink))
        p.setColor(group, QPalette.ColorRole.ToolTipBase, qcolor(t.panel_2))
        p.setColor(group, QPalette.ColorRole.ToolTipText, qcolor(t.ink))
        p.setColor(group, QPalette.ColorRole.Mid, qcolor(t.ink_3))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, qcolor(t.ink_4))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, qcolor(t.ink_4))
    return p


def build_qss(t: Tokens) -> str:
    check = _asset("check", "#FFFFFF", 3.0)
    chevron = _asset("chevron", t.ink_3, 2.0)
    cta = cta_gradient(t)
    aurora = qss_gradient(aurora_stops(t))
    return f"""
* {{ font-family: "{SANS}"; font-size: 13px; }}
QMainWindow, QDialog {{ background: {t.canvas}; }}
QWidget#panel {{ background: {t.panel}; }}
QWidget#rail {{ background: {t.canvas}; }}
QWidget#listcol {{ background: {t.panel}; border-left: 1px solid {t.line}; border-right: 1px solid {t.line}; }}
QToolTip {{ background: {t.ink}; color: {t.panel}; border: none; border-radius: 6px; padding: 5px 8px; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QAbstractScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t.ink_4}; border-radius: 3px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {t.accent}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t.ink_4}; border-radius: 3px; min-width: 24px; }}
QScrollBar::handle:horizontal:hover {{ background: {t.accent}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QSplitter::handle {{ background: transparent; }}

/* Texte */
QLabel {{ color: {t.ink}; background: transparent; }}
QLabel#ink2 {{ color: {t.ink_2}; }}
QLabel#meta {{ color: {t.ink_3}; font-size: 12px; }}
QLabel#metaMono {{ color: {t.ink_2}; font-family: "{MONO}"; font-size: 12px; }}
QLabel#section {{ color: {t.ink_3}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
QLabel#title {{ color: {t.ink}; font-size: 24px; font-weight: 600; letter-spacing: -0.5px; }}
QLabel#pageTitle {{ color: {t.ink}; font-size: 20px; font-weight: 600; letter-spacing: -0.4px; }}
QLabel#brand {{ color: {t.ink}; font-size: 15px; font-weight: 700; letter-spacing: -0.2px; }}
QFrame#tldrCard {{ background: {t.accent_soft}; border-left: 3px solid {t.accent}; border-radius: 10px; }}
QLabel#tldr {{ color: {t.ink}; font-size: 15px; background: transparent; }}
QLabel#point {{ color: {t.ink_2}; }}
QLabel#empty {{ color: {t.ink_3}; }}
QLabel#emptyTitle {{ color: {t.ink}; font-size: 19px; font-weight: 600; letter-spacing: -0.3px; }}
QLabel#gen {{ color: {t.ink_4}; font-size: 11px; }}
QLabel#lamp {{ color: {t.rec_ink}; font-size: 12px; font-weight: 600; letter-spacing: 3px; }}
QLabel#timecode {{ color: {t.ink}; font-family: "{MONO}"; font-size: 72px; font-weight: 500; letter-spacing: -2px; }}
QLabel#error {{ color: {t.rec_ink}; }}
QFrame#warnCard {{ background: {t.rec_soft}; border-radius: 12px; }}
QLabel#warn {{ color: {t.ink}; font-size: 12px; background: transparent; }}
QLabel#groupHeader {{ color: {t.ink_3}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}

/* Champs */
QLineEdit {{ background: {t.inset}; color: {t.ink}; border: 1.5px solid transparent; border-radius: 9px; padding: 6px 10px; selection-background-color: {t.accent}; selection-color: white; }}
QLineEdit:hover {{ border: 1.5px solid {t.line_2}; }}
QLineEdit:focus {{ background: {t.panel}; border: 1.5px solid {t.accent}; }}
QLineEdit#titleEdit {{ background: transparent; border: none; border-bottom: 2px solid transparent; border-radius: 0; padding: 2px 0; font-size: 24px; font-weight: 600; letter-spacing: -0.5px; }}
QLineEdit#titleEdit:hover {{ border-bottom: 2px solid {t.line_2}; }}
QLineEdit#titleEdit:focus {{ border-bottom: 2px solid {t.accent}; }}
QLineEdit#recTitle {{ background: transparent; border: none; border-bottom: 2px solid {t.line_2}; border-radius: 0; padding: 6px 2px; font-size: 16px; font-weight: 500; }}
QLineEdit#recTitle:focus {{ border-bottom: 2px solid {t.rec}; }}
QPlainTextEdit {{ background: {t.inset}; color: {t.ink}; border: 1.5px solid transparent; border-radius: 10px; padding: 8px; selection-background-color: {t.accent}; selection-color: white; }}
QPlainTextEdit:focus {{ background: {t.panel}; border: 1.5px solid {t.accent}; }}
QComboBox {{ background: {t.inset}; color: {t.ink}; border: 1.5px solid transparent; border-radius: 9px; padding: 5px 10px; }}
QComboBox:hover {{ border: 1.5px solid {t.line_2}; }}
QComboBox:focus {{ border: 1.5px solid {t.accent}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url({chevron}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {t.panel}; color: {t.ink}; border: 1px solid {t.line_2}; border-radius: 8px; selection-background-color: {t.accent_soft}; selection-color: {t.accent_ink}; outline: 0; padding: 4px; }}
QDateEdit {{ background: {t.inset}; color: {t.ink}; border: 1.5px solid transparent; border-radius: 9px; padding: 5px 10px; }}
QDateEdit:focus {{ border: 1.5px solid {t.accent}; }}
QDateEdit::drop-down {{ border: none; width: 22px; }}
QDateEdit::down-arrow {{ image: url({chevron}); width: 12px; height: 12px; }}
QCalendarWidget QAbstractItemView {{ selection-background-color: {t.accent}; selection-color: white; }}

/* Boutons */
QPushButton, QToolButton {{ background: transparent; color: {t.ink_2}; border: 1px solid {t.line_2}; border-radius: 8px; padding: 5px 11px; font-weight: 500; }}
QPushButton:hover, QToolButton:hover {{ background: {t.sel}; color: {t.ink}; border-color: {t.accent_soft}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {t.accent_soft}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {t.ink_4}; border-color: {t.line}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QPushButton#primary {{ background: {t.accent}; color: white; border: none; border-radius: 9px; padding: 7px 14px; font-weight: 600; }}
QPushButton#primary:hover {{ background: {t.accent_hover}; }}
QPushButton#primary:disabled {{ background: {t.ink_4}; }}
QPushButton#cta {{ background: {cta}; color: white; border: none; border-radius: 11px; padding: 9px 14px; font-size: 13px; font-weight: 600; text-align: left; }}
QPushButton#cta:hover {{ background: {qss_gradient([(0.0, t.rec_ink), (1.0, t.accent_hover)])}; }}
QPushButton#cta:disabled {{ background: {t.ink_4}; color: {t.panel}; }}
QPushButton#danger {{ color: {t.rec_ink}; border-color: {t.rec_soft}; }}
QPushButton#danger:hover {{ background: {t.rec_soft}; color: {t.rec_ink}; border-color: {t.rec_soft}; }}
QPushButton#stop {{ background: {t.rec}; color: white; border: none; border-radius: 23px; min-height: 46px; max-height: 46px; padding: 0 34px; font-size: 14px; font-weight: 600; }}
QPushButton#stop:hover {{ background: {t.rec_ink}; }}
QPushButton#play {{ background: {t.accent}; color: white; border: none; border-radius: 15px; min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; padding: 0; }}
QPushButton#play:hover {{ background: {t.accent_hover}; }}
QToolButton#nav {{ border: none; border-radius: 9px; padding: 6px 8px; color: {t.ink_2}; text-align: left; font-weight: 400; }}
QToolButton#nav:hover {{ background: {t.sel}; }}
QToolButton#nav:checked {{ background: {t.accent_soft}; color: {t.accent_ink}; font-weight: 600; }}
QToolButton#ghost {{ border: none; padding: 4px 6px; color: {t.ink_3}; border-radius: 7px; }}
QToolButton#ghost:hover {{ background: {t.accent_soft}; color: {t.accent_ink}; }}
QToolButton#iconBtn {{ border: 1px solid {t.line_2}; border-radius: 11px; padding: 0; min-width: 36px; min-height: 34px; }}
QToolButton#iconBtn:hover {{ background: {t.accent_soft}; border-color: {t.accent_soft}; }}

/* Cases à cocher (actions, checklist) */
QCheckBox {{ color: {t.ink_2}; spacing: 10px; padding: 6px 8px; border-radius: 8px; }}
QCheckBox:hover {{ background: {t.sel}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1.5px solid {t.ink_4}; background: transparent; }}
QCheckBox::indicator:hover {{ border-color: {t.accent}; }}
QCheckBox::indicator:checked {{ background: {t.accent}; border-color: {t.accent}; image: url({check}); }}
QCheckBox#follow {{ color: {t.ink_3}; font-size: 12px; padding: 0; }}
QCheckBox#follow:hover {{ background: transparent; }}

/* Listes, menus */
QListView {{ background: transparent; border: none; outline: 0; }}
QListView::item {{ border: none; }}
QListWidget::item {{ padding: 8px 10px; border-radius: 8px; color: {t.ink_2}; }}
QListWidget::item:hover {{ background: {t.sel}; }}
QListWidget::item:selected {{ background: {t.accent_soft}; color: {t.ink}; }}
QMenu {{ background: {t.panel}; color: {t.ink}; border: 1px solid {t.line_2}; border-radius: 10px; padding: 5px; }}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t.accent_soft}; color: {t.accent_ink}; }}
QMenu::separator {{ height: 1px; background: {t.line}; margin: 4px 6px; }}
QTabWidget::pane {{ border: none; }}
QStatusBar {{ background: {t.panel}; color: {t.ink_3}; border-top: 1px solid {t.line}; }}
QFrame#status {{ background: {t.panel}; border: 1px solid {t.line}; border-radius: 12px; }}
QFrame#status QLabel {{ color: {t.ink_2}; font-size: 12px; font-weight: 500; }}
QFrame#status QLabel#sub {{ color: {t.ink_3}; font-size: 11px; font-weight: 400; }}
QFrame#brandMark {{ background: {aurora}; border-radius: 8px; }}
QFrame#pill {{ border: 1px solid {t.line_2}; border-radius: 11px; }}
QFrame#pill QLabel {{ color: {t.ink_2}; font-size: 12px; }}
QFrame#pillOk {{ background: {t.ok_soft}; border: none; border-radius: 11px; }}
QFrame#pillOk QLabel {{ color: {t.ok_ink}; font-size: 12px; font-weight: 600; }}
QFrame#pillBusy {{ background: {t.accent_soft}; border: none; border-radius: 11px; }}
QFrame#pillBusy QLabel {{ color: {t.accent_ink}; font-size: 12px; font-weight: 600; }}
QFrame#pillRec {{ background: {t.rec_soft}; border: none; border-radius: 11px; }}
QFrame#pillRec QLabel {{ color: {t.rec_ink}; font-size: 12px; font-weight: 600; }}
QFrame#hline {{ background: {t.line}; max-height: 1px; min-height: 1px; border: none; }}
QFrame#vline {{ background: {t.line}; max-width: 1px; min-width: 1px; border: none; }}
QDialog QLabel {{ color: {t.ink}; }}
QSlider::groove:horizontal {{ height: 4px; background: {t.inset}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; background: {t.accent}; }}

/* Boards */
QWidget#board {{ background: {t.canvas}; }}
QFrame#boardList {{ background: {t.list_bg}; border-radius: 14px; }}
QLabel#listTitle {{ color: {t.ink}; font-weight: 600; padding: 4px 4px; }}
QLineEdit#listTitleEdit {{ background: {t.card_bg}; border: 1.5px solid {t.accent}; border-radius: 7px; padding: 3px 5px; font-weight: 600; }}
QLabel#listCount {{ color: {t.ink_3}; background: {t.panel}; font-size: 11px; font-weight: 600; border-radius: 9px; padding: 0 7px; min-height: 18px; max-height: 18px; }}
QFrame#card {{ background: {t.card_bg}; border: 1px solid {t.line}; border-bottom: 2px solid {t.line_2}; border-radius: 10px; }}
QFrame#card:hover {{ background: {t.card_hover}; border: 1px solid {t.accent}; border-bottom: 2px solid {t.accent}; }}
QFrame#card QLabel {{ background: transparent; }}
QFrame#dropMark {{ background: {t.accent_soft}; border: 1.5px dashed {t.accent}; border-radius: 10px; }}
QLabel#cardTitle {{ color: {t.ink}; }}
QLabel#badge {{ color: {t.ink_3}; font-size: 11px; }}
QPlainTextEdit#composer {{ background: {t.card_bg}; border: 1.5px solid {t.accent}; border-radius: 10px; padding: 6px 8px; }}
QToolButton#addCard {{ border: none; border-radius: 8px; padding: 7px 8px; color: {t.ink_3}; text-align: left; font-weight: 500; }}
QToolButton#addCard:hover {{ background: {t.accent_soft}; color: {t.accent_ink}; }}
QFrame#addList {{ background: {t.sel}; border: 1.5px dashed {t.line_2}; border-radius: 14px; }}
QToolButton#railAdd {{ border: none; padding: 2px 5px; color: {t.ink_3}; border-radius: 6px; }}
QToolButton#railAdd:hover {{ background: {t.accent_soft}; color: {t.accent_ink}; }}
QToolButton#labelPick {{ border: 2px solid transparent; border-radius: 12px; min-width: 40px; min-height: 24px; padding: 0 6px; }}
QProgressBar {{ background: {t.inset}; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; }}
QProgressBar::chunk {{ background: {qss_gradient([(0.0, t.accent), (1.0, t.ok)])}; border-radius: 4px; }}
"""


def apply(app, dark: bool | None = None) -> Tokens:
    """Applique palette + QSS à l'application. Retourne les tokens actifs."""
    global _current
    if dark is None:
        dark = system_prefers_dark()
    _current = DARK if dark else LIGHT
    app.setPalette(build_palette(_current))
    app.setStyleSheet(build_qss(_current))
    return _current
