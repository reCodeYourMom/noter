"""Design tokens → palette Qt + feuille de style. Deux thèmes, un seul accent (le voyant REC)."""
from __future__ import annotations

import logging
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
    sel: str         # survol / sélection (rgba)
    rec: str         # accent : REC et échec
    rec_soft: str
    ok: str
    busy: str
    busy_soft: str
    speakers: tuple[str, ...]
    is_dark: bool
    list_bg: str     # fond d'une liste de board
    card_bg: str     # fond d'une carte
    card_hover: str
    labels: dict[str, str]  # étiquettes de cartes (clé → couleur)


LIGHT = Tokens(
    name="light",
    canvas="#F3F3F1", panel="#FFFFFF", panel_2="#F8F8F6", inset="#EDEDEA",
    ink="#17191B", ink_2="#4B5057", ink_3="#7B818A", ink_4="#B0B5BC",
    line="rgba(23,25,27,0.08)", line_2="rgba(23,25,27,0.14)", sel="rgba(23,25,27,0.06)",
    rec="#E5484D", rec_soft="rgba(229,72,77,0.12)",
    ok="#2D9A68", busy="#D08A1E", busy_soft="rgba(208,138,30,0.14)",
    speakers=("#4E6FB3", "#5A9A6F", "#9A5AA0", "#C27A4C", "#3F8F9E", "#A6703A"),
    is_dark=False,
    list_bg="#EBEBE8", card_bg="#FFFFFF", card_hover="#F8F8F6",
    labels={"green": "#4FAE6A", "yellow": "#E2B203", "orange": "#E8802A", "red": "#E5484D", "purple": "#9F6FD0", "blue": "#3B7DD8"},
)

DARK = Tokens(
    name="dark",
    canvas="#131415", panel="#1B1C1E", panel_2="#202224", inset="#17181A",
    ink="#ECEDEE", ink_2="#B4B8BD", ink_3="#7F858C", ink_4="#4E535A",
    line="rgba(255,255,255,0.07)", line_2="rgba(255,255,255,0.12)", sel="rgba(255,255,255,0.07)",
    rec="#F0575C", rec_soft="rgba(240,87,92,0.16)",
    ok="#4CB381", busy="#E0A043", busy_soft="rgba(224,160,67,0.16)",
    speakers=("#7D9BE0", "#7FC296", "#C48BCB", "#E0A078", "#6FBFCF", "#D4A06A"),
    is_dark=True,
    list_bg="#1B1C1E", card_bg="#26282B", card_hover="#2D3033",
    labels={"green": "#5CBE78", "yellow": "#E5C13A", "orange": "#EE9A52", "red": "#F0575C", "purple": "#B48AE0", "blue": "#6AA0EC"},
)

_current: Tokens = LIGHT


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
        p.setColor(group, QPalette.ColorRole.Highlight, qcolor(t.ink))
        p.setColor(group, QPalette.ColorRole.HighlightedText, qcolor(t.panel))
        p.setColor(group, QPalette.ColorRole.ToolTipBase, qcolor(t.panel_2))
        p.setColor(group, QPalette.ColorRole.ToolTipText, qcolor(t.ink))
        p.setColor(group, QPalette.ColorRole.Mid, qcolor(t.ink_3))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, qcolor(t.ink_4))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, qcolor(t.ink_4))
    return p


def build_qss(t: Tokens) -> str:
    return f"""
* {{ font-family: "{SANS}"; font-size: 13px; }}
QMainWindow, QDialog {{ background: {t.canvas}; }}
QWidget#panel {{ background: {t.panel}; }}
QWidget#rail {{ background: {t.panel}; border-right: 1px solid {t.line}; }}
QWidget#listcol {{ background: {t.panel}; border-right: 1px solid {t.line}; }}
QToolTip {{ background: {t.panel_2}; color: {t.ink}; border: 1px solid {t.line_2}; padding: 4px 6px; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QAbstractScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t.ink_4}; border-radius: 3px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {t.ink_3}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t.ink_4}; border-radius: 3px; min-width: 24px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QSplitter::handle {{ background: transparent; }}

/* Texte */
QLabel {{ color: {t.ink}; background: transparent; }}
QLabel#ink2 {{ color: {t.ink_2}; }}
QLabel#meta {{ color: {t.ink_3}; font-size: 12px; }}
QLabel#metaMono {{ color: {t.ink_2}; font-family: "{MONO}"; font-size: 12px; }}
QLabel#section {{ color: {t.ink_3}; font-size: 11px; font-weight: 500; letter-spacing: 1px; }}
QLabel#title {{ color: {t.ink}; font-size: 24px; font-weight: 600; letter-spacing: -0.5px; }}
QLabel#tldr {{ color: {t.ink}; font-size: 15px; line-height: 150%; }}
QLabel#point {{ color: {t.ink_2}; }}
QLabel#empty {{ color: {t.ink_3}; }}
QLabel#emptyTitle {{ color: {t.ink}; font-size: 16px; font-weight: 600; }}
QLabel#gen {{ color: {t.ink_4}; font-size: 11px; }}
QLabel#lamp {{ color: {t.rec}; font-size: 12px; font-weight: 500; letter-spacing: 2px; }}
QLabel#timecode {{ color: {t.ink}; font-family: "{MONO}"; font-size: 72px; font-weight: 500; letter-spacing: -2px; }}
QLabel#error {{ color: {t.rec}; }}
QLabel#groupHeader {{ color: {t.ink_3}; font-size: 11px; font-weight: 500; letter-spacing: 1px; }}

/* Champs */
QLineEdit {{ background: {t.inset}; color: {t.ink}; border: 1px solid transparent; border-radius: 7px; padding: 6px 10px; selection-background-color: {t.ink}; selection-color: {t.panel}; }}
QLineEdit:focus {{ border: 1px solid {t.ink_3}; }}
QLineEdit#titleEdit {{ background: transparent; border: none; border-bottom: 1px solid transparent; border-radius: 0; padding: 2px 0; font-size: 24px; font-weight: 600; letter-spacing: -0.5px; }}
QLineEdit#titleEdit:hover {{ border-bottom: 1px solid {t.line_2}; }}
QLineEdit#titleEdit:focus {{ border-bottom: 1px solid {t.ink}; }}
QLineEdit#recTitle {{ background: transparent; border: none; border-bottom: 1px solid {t.line_2}; border-radius: 0; padding: 6px 2px; font-size: 16px; font-weight: 500; }}
QLineEdit#recTitle:focus {{ border-bottom: 1px solid {t.ink}; }}
QPlainTextEdit {{ background: {t.inset}; color: {t.ink}; border: 1px solid transparent; border-radius: 7px; padding: 8px; }}
QPlainTextEdit:focus {{ border: 1px solid {t.ink_3}; }}
QComboBox {{ background: {t.inset}; color: {t.ink}; border: 1px solid transparent; border-radius: 7px; padding: 5px 10px; }}
QComboBox:focus {{ border: 1px solid {t.ink_3}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: {t.panel}; color: {t.ink}; border: 1px solid {t.line_2}; selection-background-color: {t.sel}; selection-color: {t.ink}; outline: 0; }}

/* Boutons */
QPushButton, QToolButton {{ background: transparent; color: {t.ink_2}; border: 1px solid {t.line_2}; border-radius: 6px; padding: 5px 10px; font-weight: 500; }}
QPushButton:hover, QToolButton:hover {{ background: {t.sel}; color: {t.ink}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {t.inset}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {t.ink_4}; border-color: {t.line}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QPushButton#primary {{ background: {t.ink}; color: {t.panel}; border: none; padding: 7px 12px; }}
QPushButton#primary:hover {{ background: {t.ink_2}; }}
QPushButton#primary:disabled {{ background: {t.ink_4}; }}
QPushButton#stop {{ background: {t.rec}; color: white; border: none; border-radius: 22px; padding: 12px 28px; font-size: 14px; font-weight: 600; }}
QPushButton#stop:hover {{ background: {t.rec}; }}
QPushButton#play {{ background: {t.ink}; color: {t.panel}; border: none; border-radius: 14px; min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; padding: 0; }}
QToolButton#nav {{ border: none; border-radius: 6px; padding: 6px 8px; color: {t.ink_2}; text-align: left; font-weight: 400; }}
QToolButton#nav:hover {{ background: {t.sel}; }}
QToolButton#nav:checked {{ background: {t.sel}; color: {t.ink}; font-weight: 500; }}
QToolButton#ghost {{ border: none; padding: 4px 6px; color: {t.ink_3}; }}
QToolButton#ghost:hover {{ background: {t.sel}; color: {t.ink}; }}

/* Cases à cocher (actions) */
QCheckBox {{ color: {t.ink_2}; spacing: 10px; padding: 6px 8px; border-radius: 6px; }}
QCheckBox:hover {{ background: {t.sel}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1.5px solid {t.ink_4}; background: transparent; }}
QCheckBox::indicator:checked {{ background: {t.ink}; border-color: {t.ink}; image: url(:/qt-project.org/styles/commonstyle/images/standardbutton-apply-16.png); }}
QCheckBox#follow {{ color: {t.ink_3}; font-size: 12px; padding: 0; }}
QCheckBox#follow:hover {{ background: transparent; }}

/* Listes */
QListView {{ background: transparent; border: none; outline: 0; }}
QListView::item {{ border: none; }}
QMenu {{ background: {t.panel}; color: {t.ink}; border: 1px solid {t.line_2}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 24px 6px 10px; border-radius: 5px; }}
QMenu::item:selected {{ background: {t.sel}; }}
QMenu::separator {{ height: 1px; background: {t.line}; margin: 4px 6px; }}
QTabWidget::pane {{ border: none; }}
QStatusBar {{ background: {t.panel}; color: {t.ink_3}; border-top: 1px solid {t.line}; }}
QFrame#status {{ background: {t.panel_2}; border: 1px solid {t.line}; border-radius: 8px; }}
QFrame#status QLabel {{ color: {t.ink_2}; font-size: 12px; }}
QFrame#status QLabel#sub {{ color: {t.ink_3}; font-size: 11px; }}
QFrame#pill {{ border: 1px solid {t.line_2}; border-radius: 10px; }}
QFrame#pill QLabel {{ color: {t.ink_2}; font-size: 12px; }}
QFrame#pillOk {{ background: rgba(45,154,104,0.12); border: none; border-radius: 10px; }}
QFrame#pillOk QLabel {{ color: {t.ok}; font-size: 12px; font-weight: 500; }}
QFrame#pillBusy {{ background: {t.busy_soft}; border: none; border-radius: 10px; }}
QFrame#pillBusy QLabel {{ color: {t.busy}; font-size: 12px; font-weight: 500; }}
QFrame#pillRec {{ background: {t.rec_soft}; border: none; border-radius: 10px; }}
QFrame#pillRec QLabel {{ color: {t.rec}; font-size: 12px; font-weight: 500; }}
QFrame#hline {{ background: {t.line}; max-height: 1px; min-height: 1px; border: none; }}
QFrame#vline {{ background: {t.line}; max-width: 1px; min-width: 1px; border: none; }}
QDialog QLabel {{ color: {t.ink}; }}

/* Boards */
QWidget#board {{ background: {t.canvas}; }}
QFrame#boardList {{ background: {t.list_bg}; border-radius: 10px; }}
QLabel#listTitle {{ color: {t.ink}; font-weight: 600; padding: 4px 6px; }}
QLineEdit#listTitleEdit {{ background: {t.card_bg}; border: 1px solid {t.ink_3}; border-radius: 6px; padding: 3px 5px; font-weight: 600; }}
QLabel#listCount {{ color: {t.ink_3}; font-size: 12px; }}
QFrame#card {{ background: {t.card_bg}; border: 1px solid {t.line}; border-bottom: 2px solid {t.line_2}; border-radius: 8px; }}
QFrame#card:hover {{ background: {t.card_hover}; border-color: {t.line_2}; }}
QFrame#card QLabel {{ background: transparent; }}
QFrame#cardMatch {{ background: {t.card_bg}; border: 2px solid {t.ink}; border-radius: 8px; }}
QFrame#dropMark {{ background: {t.sel}; border: 1px dashed {t.ink_4}; border-radius: 8px; }}
QLabel#cardTitle {{ color: {t.ink}; }}
QLabel#badge {{ color: {t.ink_3}; font-size: 11px; }}
QPlainTextEdit#composer {{ background: {t.card_bg}; border: 1px solid {t.line_2}; border-radius: 8px; padding: 6px 8px; }}
QPlainTextEdit#composer:focus {{ border: 1px solid {t.ink_3}; }}
QToolButton#addCard {{ border: none; border-radius: 6px; padding: 6px 8px; color: {t.ink_2}; text-align: left; font-weight: 400; }}
QToolButton#addCard:hover {{ background: {t.sel}; color: {t.ink}; }}
QFrame#addList {{ background: {t.sel}; border-radius: 10px; }}
QToolButton#boardTitle {{ border: none; border-radius: 6px; padding: 4px 8px; color: {t.ink}; font-size: 18px; font-weight: 600; }}
QToolButton#boardTitle:hover {{ background: {t.sel}; }}
QToolButton#railAdd {{ border: none; padding: 1px 5px; color: {t.ink_3}; }}
QToolButton#railAdd:hover {{ background: {t.sel}; color: {t.ink}; }}
QToolButton#labelPick {{ border: 2px solid transparent; border-radius: 6px; min-width: 30px; min-height: 22px; padding: 0; }}
QProgressBar {{ background: {t.inset}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; }}
QProgressBar::chunk {{ background: {t.ok}; border-radius: 3px; }}
QDateEdit {{ background: {t.inset}; color: {t.ink}; border: 1px solid transparent; border-radius: 7px; padding: 5px 10px; }}
QDateEdit:focus {{ border: 1px solid {t.ink_3}; }}
QSlider::groove:horizontal {{ height: 3px; background: {t.inset}; border-radius: 1px; }}
QSlider::sub-page:horizontal {{ background: {t.ink}; border-radius: 1px; }}
QSlider::handle:horizontal {{ width: 10px; height: 10px; margin: -4px 0; border-radius: 5px; background: {t.ink}; }}
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
