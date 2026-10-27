"""Configuration centralisée.

Priorité : variables d'environnement NOTER_* > fichier ~/Noter/.env > défauts.
NOTER_HOME déplace tout (données, DB, .env) — utile pour les tests.
"""
from __future__ import annotations

import os
import platform
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def noter_home() -> Path:
    return Path(os.environ.get("NOTER_HOME", "~/Noter")).expanduser()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NOTER_",
        env_file=(noter_home() / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Claude
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "medium"
    auto_summarize: bool = True
    auto_tasks: bool = True  # à la fin d'un résumé, chaque action devient une carte du premier board

    # Apparence : auto (suit macOS) | light | dark
    theme: str = "auto"

    # Whisper
    whisper_model: str = "large-v3"
    whisper_language: str | None = None  # None = auto-détection
    diarize: bool = False

    # Stockage
    data_dir: Path = Field(default_factory=lambda: noter_home() / "recordings")
    db_path: Path = Field(default_factory=lambda: noter_home() / "noter.db")
    log_path: Path = Field(default_factory=lambda: noter_home() / "noter.log")

    # Audio
    sample_rate: int = 48000

    # Jobs
    job_max_attempts: int = 3

    # Serveur MCP (Noter depuis Claude Desktop / Claude Code)
    mcp_read_only: bool = False     # seulement les outils de lecture
    mcp_allow_delete: bool = False  # outils de suppression (enregistrements, cartes)
    mcp_allow_record: bool = True   # démarrer / arrêter un enregistrement via l'app
    mcp_launch_app: bool = True     # lancer Noter.app si besoin (traitement, enregistrement)

    @field_validator("whisper_language", mode="before")
    @classmethod
    def _language(cls, v):
        """'' / 'auto' → None (auto-détection) ; ' FR ' → 'fr'."""
        if v is None:
            return None
        v = str(v).strip().lower()
        return None if v in ("", "auto", "none") else v

    @field_validator("theme", mode="before")
    @classmethod
    def _theme(cls, v):
        v = str(v or "").strip().lower()
        return v if v in ("auto", "light", "dark") else "auto"

    @field_validator("data_dir", "db_path", "log_path", mode="before")
    @classmethod
    def _expand(cls, v):
        return Path(v).expanduser()

    @property
    def is_apple_silicon(self) -> bool:
        return platform.machine() == "arm64" and platform.system() == "Darwin"

    @property
    def is_macos(self) -> bool:
        return platform.system() == "Darwin"


def load_settings() -> Settings:
    """Construit un Settings frais (relit l'env et le .env)."""
    return Settings()


settings = load_settings()
