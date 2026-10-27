"""Réglages : édite ~/Noter/.env (les changements s'appliquent au prochain lancement du pipeline)."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpacerItem,
)

from noter.config import Settings, noter_home
from noter.ui import theme
from noter.ui.widgets.common import section_label

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3-turbo", "large-v3"]
EFFORTS = ["low", "medium", "high"]


def env_path() -> Path:
    return noter_home() / ".env"


def read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def write_env(path: Path, updates: dict[str, str]) -> None:
    """Met à jour les clés sans toucher aux commentaires ni à l'ordre."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen = set()
    def render(key: str, val: str) -> str:
        # Valeur vide → ligne commentée : la variable reste absente (défaut), jamais « chaîne vide »
        return f"{key}={val}" if val != "" else f"# {key}="

    for i, line in enumerate(lines):
        m = re.match(r"^\s*#?\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m and m.group(1) in updates:
            key = m.group(1)
            lines[i] = render(key, updates[key])
            seen.add(key)
    for key, val in updates.items():
        if key not in seen:
            lines.append(render(key, val))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Réglages Noter")
        self.setMinimumWidth(460)
        env = read_env(env_path())

        self.api_key = QLineEdit(env.get("ANTHROPIC_API_KEY", settings.anthropic_api_key))
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("sk-ant-…")
        self.model = QLineEdit(env.get("NOTER_CLAUDE_MODEL", settings.claude_model))
        self.effort = QComboBox()
        self.effort.addItems(EFFORTS)
        self.effort.setCurrentText(env.get("NOTER_CLAUDE_EFFORT", settings.claude_effort))
        self.whisper = QComboBox()
        self.whisper.setEditable(True)
        self.whisper.addItems(WHISPER_MODELS)
        self.whisper.setCurrentText(env.get("NOTER_WHISPER_MODEL", settings.whisper_model))
        self.language = QLineEdit(env.get("NOTER_WHISPER_LANGUAGE", settings.whisper_language or ""))
        self.language.setPlaceholderText("auto (ou fr, en…)")
        self.auto = QCheckBox("Résumer automatiquement après transcription")
        self.auto.setChecked(env.get("NOTER_AUTO_SUMMARIZE", str(settings.auto_summarize)).lower() in ("1", "true", "yes"))
        self.auto_tasks = QCheckBox("Ajouter toutes les actions aux tâches à la fin de chaque call")
        self.auto_tasks.setToolTip("Une carte par action, en haut de la liste « À faire » du premier board de la section Tâches.")
        self.auto_tasks.setChecked(env.get("NOTER_AUTO_TASKS", str(settings.auto_tasks)).lower() in ("1", "true", "yes"))

        t = theme.current()
        form = QFormLayout(self)
        form.setContentsMargins(28, 24, 28, 22)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        title = QLabel("Réglages")
        title.setObjectName("pageTitle")
        sub = QLabel("Résumés avec Claude, transcription en local avec Whisper.")
        sub.setObjectName("meta")
        form.addRow(title)
        form.addRow(sub)
        form.addItem(QSpacerItem(0, 8))
        form.addRow(section_label("Résumé · Claude", t.accent))
        form.addRow("Clé API Anthropic", self.api_key)
        form.addRow("Modèle Claude", self.model)
        form.addRow("Effort", self.effort)
        form.addRow("", self.auto)
        form.addRow("", self.auto_tasks)
        form.addItem(QSpacerItem(0, 6))
        form.addRow(section_label("Transcription · Whisper", t.ok))
        form.addRow("Modèle Whisper", self.whisper)
        form.addRow("Langue forcée", self.language)
        form.addItem(QSpacerItem(0, 6))
        note = QLabel(f"Fichier : {env_path()}\nLes changements s'appliquent au redémarrage de Noter.")
        note.setObjectName("gen")
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        save = buttons.button(QDialogButtonBox.StandardButton.Save)
        save.setText("Enregistrer")
        save.setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict[str, str]:
        return {
            "ANTHROPIC_API_KEY": self.api_key.text().strip(),
            "NOTER_CLAUDE_MODEL": self.model.text().strip() or "claude-opus-5-5",
            "NOTER_CLAUDE_EFFORT": self.effort.currentText(),
            "NOTER_WHISPER_MODEL": self.whisper.currentText().strip() or "large-v3",
            "NOTER_WHISPER_LANGUAGE": self.language.text().strip(),
            "NOTER_AUTO_SUMMARIZE": "true" if self.auto.isChecked() else "false",
            "NOTER_AUTO_TASKS": "true" if self.auto_tasks.isChecked() else "false",
        }

    def save(self) -> None:
        write_env(env_path(), self.values())
