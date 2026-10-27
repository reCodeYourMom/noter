"""Rail de navigation : marque, bouton Enregistrer, bibliothèque, tâches, projets, tags, état, réglages."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from noter.ui import icons, theme
from noter.ui.theme import MONO
from noter.ui.widgets.common import clear_layout, dot_icon


@dataclass(frozen=True)
class NavKey:
    kind: str  # all | active | failed | project | tag | board
    value: str | None = None


class NavItem(QToolButton):
    def __init__(self, key: NavKey, label: str, icon_name: str | None = None, swatch: QColor | None = None, count: int | None = None):
        super().__init__()
        self.key = key
        self.icon_name = icon_name
        self.setObjectName("nav")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(9, 0, 8, 0)
        lay.setSpacing(10)
        self.ic: QLabel | None = None
        if icon_name:
            self.ic = QLabel()
            self.ic.setFixedWidth(16)
            lay.addWidget(self.ic)
        elif swatch is not None:
            sw = QLabel()
            sw.setFixedSize(10, 10)
            sw.setStyleSheet(f"background: {swatch.name()}; border-radius: 3px;")
            lay.addWidget(sw)
            lay.addSpacing(2)
        self.lab = QLabel(label)
        self.lab.setStyleSheet("background: transparent; border: none;")
        lay.addWidget(self.lab, 1)
        self.count: QLabel | None = None
        if count is not None:
            self.count = QLabel(str(count))
            f = QFont(MONO)
            f.setPixelSize(11)
            self.count.setFont(f)
            self.count.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.count.setMinimumWidth(22)
            self.count.setFixedHeight(18)
            lay.addWidget(self.count)
        self.setFixedHeight(32)
        self.setText(" ")  # garde la hauteur / le style du bouton, le texte réel est dans le layout
        self.toggled.connect(self._restyle)
        self._restyle(False)

    def _restyle(self, checked: bool) -> None:
        """Les enfants ne suivent pas l'état :checked du bouton en QSS : on les recolore ici."""
        t = theme.current()
        if self.ic is not None and self.icon_name:
            self.ic.setPixmap(icons.icon(self.icon_name, t.accent if checked else t.ink_3, 16).pixmap(16, 16))
        weight = 600 if checked else 400
        self.lab.setStyleSheet(f"background: transparent; border: none; color: {t.accent_ink if checked else t.ink_2}; font-weight: {weight};")
        if self.count is not None:
            bg, fg = (t.accent, "#FFFFFF") if checked else (t.inset, t.ink_3)
            self.count.setStyleSheet(f"background: {bg}; color: {fg}; border-radius: 9px; padding: 1px 6px;")


class NavRail(QWidget):
    selected = Signal(object)  # NavKey
    settings_requested = Signal()
    board_add_requested = Signal()
    record_requested = Signal()
    import_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("rail")
        self.setFixedWidth(224)
        self._items: list[NavItem] = []
        self._current = NavKey("all")
        t = theme.current()

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(4)

        # Marque : pastille aurora + nom
        brand = QHBoxLayout()
        brand.setContentsMargins(6, 26, 6, 14)
        brand.setSpacing(10)
        mark = QFrame()
        mark.setObjectName("brandMark")
        mark.setFixedSize(26, 26)
        ml = QHBoxLayout(mark)
        ml.setContentsMargins(0, 0, 0, 0)
        glyph = QLabel()
        glyph.setPixmap(icons.icon("wave", "#FFFFFF", 16).pixmap(16, 16))
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ml.addWidget(glyph)
        name = QLabel("Noter")
        name.setObjectName("brand")
        brand.addWidget(mark)
        brand.addWidget(name)
        brand.addStretch()
        root.addLayout(brand)

        # Action principale, toujours à portée (bibliothèque comme boards)
        cta_row = QHBoxLayout()
        cta_row.setSpacing(6)
        self.record_btn = QPushButton("  Enregistrer")
        self.record_btn.setObjectName("cta")
        self.record_btn.setIcon(dot_icon("#FFFFFF", 8))
        self.record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.record_btn.setToolTip("Micro + audio système (⌘R)")
        self.record_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        rl = QHBoxLayout(self.record_btn)
        rl.setContentsMargins(0, 0, 12, 0)
        rl.addStretch()
        kbd = QLabel("⌘R")
        kbd.setStyleSheet("color: rgba(255,255,255,0.75); background: transparent; font-size: 11px; font-weight: 600;")
        rl.addWidget(kbd)
        self.record_btn.clicked.connect(self.record_requested.emit)
        self.import_btn = QToolButton()
        self.import_btn.setObjectName("iconBtn")
        self.import_btn.setIcon(icons.icon("import", t.ink_2, 16))
        self.import_btn.setToolTip("Importer un fichier audio (⌘I)")
        self.import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.import_btn.clicked.connect(self.import_requested.emit)
        cta_row.addWidget(self.record_btn, 1)
        cta_row.addWidget(self.import_btn)
        root.addLayout(cta_row)
        root.addSpacing(10)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        self.body_lay.setSpacing(2)
        self.body_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.body)
        root.addWidget(self.scroll, 1)

        self.status = QFrame()
        self.status.setObjectName("status")
        sl = QHBoxLayout(self.status)
        sl.setContentsMargins(12, 10, 12, 10)
        sl.setSpacing(10)
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(10, 10)
        txt = QVBoxLayout()
        txt.setSpacing(1)
        self.status_main = QLabel("Inactif")
        self.status_sub = QLabel("")
        self.status_sub.setObjectName("sub")
        txt.addWidget(self.status_main)
        txt.addWidget(self.status_sub)
        sl.addWidget(self.status_dot)
        sl.addLayout(txt, 1)
        root.addWidget(self.status)
        self.status.hide()

        settings = QToolButton()
        settings.setObjectName("nav")
        settings.setText("  Réglages")
        settings.setIcon(icons.icon("settings", t.ink_3, 16))
        settings.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        settings.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        settings.setCursor(Qt.CursorShape.PointingHandCursor)
        settings.clicked.connect(self.settings_requested.emit)
        root.addSpacing(6)
        root.addWidget(settings)

    @property
    def current(self) -> NavKey:
        return self._current

    def set_status(self, main: str | None, sub: str = "", busy: bool = False) -> None:
        t = theme.current()
        if not main:
            self.status.hide()
            return
        self.status.show()
        self.status_main.setText(main)
        self.status_sub.setText(sub)
        self.status_sub.setVisible(bool(sub))
        color = t.busy if busy else t.ok
        self.status_dot.setStyleSheet(f"background: {color}; border-radius: 5px;")

    def populate(
        self,
        counts: dict[str, int],
        projects: list[tuple[str, int]],
        tags: list[tuple[str, int]],
        boards: list[tuple[int, str, int]] | None = None,
    ) -> None:
        """`boards` : (id, nom, nombre de cartes)."""
        clear_layout(self.body_lay)
        self._items = []
        t = theme.current()

        def add(item: NavItem):
            item.setChecked(item.key == self._current)
            item.clicked.connect(lambda _=False, k=item.key: self._select(k))
            self.body_lay.addWidget(item)
            self._items.append(item)

        def label(text: str, action: QToolButton | None = None):
            head = QWidget()
            hl = QHBoxLayout(head)
            hl.setContentsMargins(9, 14, 2, 4)
            hl.setSpacing(0)
            lab = QLabel(text.upper())
            lab.setObjectName("section")
            hl.addWidget(lab, 1)
            if action is not None:
                hl.addWidget(action, 0, Qt.AlignmentFlag.AlignBottom)
            self.body_lay.addWidget(head)

        label("Bibliothèque")
        add(NavItem(NavKey("all"), "Tous les calls", "list", count=counts.get("all", 0)))
        add(NavItem(NavKey("active"), "En cours", "clock", count=counts.get("active", 0)))
        add(NavItem(NavKey("failed"), "Échecs", "alert", count=counts.get("failed", 0)))

        plus = QToolButton()
        plus.setObjectName("railAdd")
        plus.setIcon(icons.icon("plus", t.ink_3, 14))
        plus.setToolTip("Nouveau board")
        plus.setCursor(Qt.CursorShape.PointingHandCursor)
        plus.clicked.connect(self.board_add_requested.emit)
        label("Tâches", plus)
        if boards:
            for board_id, name, n in boards:
                add(NavItem(NavKey("board", str(board_id)), name, "board", count=n))
        else:
            hint = QToolButton()
            hint.setObjectName("addCard")
            hint.setText("  Créer un board")
            hint.setIcon(icons.icon("plus", t.ink_3, 14))
            hint.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            hint.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            hint.setCursor(Qt.CursorShape.PointingHandCursor)
            hint.clicked.connect(self.board_add_requested.emit)
            self.body_lay.addWidget(hint)
        if projects:
            label("Projets")
            for name, n in projects:
                add(NavItem(NavKey("project", name), name, swatch=theme.speaker_color(t, name), count=n))
        if tags:
            label("Tags")
            for name, n in tags:
                add(NavItem(NavKey("tag", name), f"#{name}", "tag", count=n))

    def _select(self, key: NavKey) -> None:
        self._current = key
        for it in self._items:
            it.setChecked(it.key == key)
        self.selected.emit(key)

    def select(self, key: NavKey) -> None:
        self._select(key)
