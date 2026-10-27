"""Rail de navigation : bibliothèque, projets, tags, état du traitement, réglages."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from noter.ui import icons, theme
from noter.ui.theme import MONO
from noter.ui.widgets.common import clear_layout


@dataclass(frozen=True)
class NavKey:
    kind: str  # all | active | failed | project | tag | board
    value: str | None = None


class NavItem(QToolButton):
    def __init__(self, key: NavKey, label: str, icon_name: str | None = None, swatch: QColor | None = None, count: int | None = None):
        super().__init__()
        self.key = key
        self.setObjectName("nav")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        t = theme.current()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(9)
        if icon_name:
            ic = QLabel()
            ic.setPixmap(icons.icon(icon_name, t.ink_3, 15).pixmap(15, 15))
            ic.setFixedWidth(15)
            lay.addWidget(ic)
        elif swatch is not None:
            sw = QLabel()
            sw.setFixedSize(8, 8)
            sw.setStyleSheet(f"background: {swatch.name()}; border-radius: 2px;")
            lay.addWidget(sw)
            lay.addSpacing(1)
        self.lab = QLabel(label)
        self.lab.setStyleSheet("background: transparent; border: none;")
        lay.addWidget(self.lab, 1)
        if count is not None:
            c = QLabel(str(count))
            f = QFont(MONO)
            f.setPixelSize(11)
            c.setFont(f)
            c.setStyleSheet(f"color: {t.ink_3}; background: transparent;")
            lay.addWidget(c)
        self.setFixedHeight(30)
        self.setText(" ")  # garde la hauteur / le style du bouton, le texte réel est dans le layout


class NavRail(QWidget):
    selected = Signal(object)  # NavKey
    settings_requested = Signal()
    board_add_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("rail")
        self.setFixedWidth(208)
        self._items: list[NavItem] = []
        self._current = NavKey("all")

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 12, 10, 12)
        root.setSpacing(4)

        brand = QHBoxLayout()
        brand.setContentsMargins(8, 24, 8, 12)
        dot = QLabel()
        dot.setFixedSize(9, 9)
        t = theme.current()
        dot.setStyleSheet(f"background: {t.rec}; border-radius: 4px;")
        name = QLabel("Noter")
        f = QFont()
        f.setPixelSize(14)
        f.setWeight(QFont.Weight.DemiBold)
        name.setFont(f)
        brand.addWidget(dot)
        brand.addSpacing(4)
        brand.addWidget(name)
        brand.addStretch()
        root.addLayout(brand)

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
        sl.setContentsMargins(10, 8, 10, 8)
        sl.setSpacing(8)
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(10, 10)
        txt = QVBoxLayout()
        txt.setSpacing(0)
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
        settings.setText("Réglages")
        settings.setIcon(icons.icon("settings", t.ink_3, 15))
        settings.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        settings.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        settings.setCursor(Qt.CursorShape.PointingHandCursor)
        settings.clicked.connect(self.settings_requested.emit)
        root.addSpacing(4)
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

        def label(text: str):
            lab = QLabel(text.upper())
            lab.setObjectName("section")
            lab.setContentsMargins(8, 12, 8, 4)
            self.body_lay.addWidget(lab)

        add(NavItem(NavKey("all"), "Tous", "list", count=counts.get("all", 0)))
        add(NavItem(NavKey("active"), "En cours", "clock", count=counts.get("active", 0)))
        add(NavItem(NavKey("failed"), "Échecs", "alert", count=counts.get("failed", 0)))

        # Section « Tâches » : un item par board, et un « + » pour en créer un
        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        lab = QLabel("TÂCHES")
        lab.setObjectName("section")
        lab.setContentsMargins(8, 12, 8, 4)
        plus = QToolButton()
        plus.setObjectName("railAdd")
        plus.setIcon(icons.icon("plus", t.ink_3, 13))
        plus.setToolTip("Nouveau board")
        plus.setCursor(Qt.CursorShape.PointingHandCursor)
        plus.clicked.connect(self.board_add_requested.emit)
        hl.addWidget(lab, 1)
        hl.addWidget(plus, 0, Qt.AlignmentFlag.AlignBottom)
        self.body_lay.addWidget(head)
        for board_id, name, n in boards or []:
            add(NavItem(NavKey("board", str(board_id)), name, "board", count=n))
        if projects:
            label("Projets")
            for name, n in projects:
                add(NavItem(NavKey("project", name), name, swatch=theme.speaker_color(t, name), count=n))
        if tags:
            label("Tags")
            for name, n in tags:
                add(NavItem(NavKey("tag", name), f"#{name}", count=n))

    def _select(self, key: NavKey) -> None:
        self._current = key
        for it in self._items:
            it.setChecked(it.key == key)
        self.selected.emit(key)

    def select(self, key: NavKey) -> None:
        self._select(key)
