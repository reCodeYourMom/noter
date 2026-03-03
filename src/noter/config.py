"""Configuration centralisée Noter."""
from __future__ import annotations

import platform
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NOTER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Claude API (lu aussi sans préfixe via ANTHROPIC_API_KEY)
    anthropic_api_key: str = ""

    # Whisper
    whisper_model: str = "large-v3"

    # Storage
    data_dir: Path = Path.home() / "Noter" / "recordings"
    db_path: Path = Path.home() / "Noter" / "noter.db"

    # Server
    server_port: int = 9876
    server_host: str = "0.0.0.0"

    # Audio
    sample_rate: int = 48000
    channels: int = 1

    # Diarisation (lourd sur CPU Intel, rapide sur Apple Silicon)
    diarize: bool = False

    @field_validator("data_dir", "db_path", mode="before")
    @classmethod
    def expand_path(cls, v):
        return Path(v).expanduser()

    @property
    def is_apple_silicon(self) -> bool:
        return platform.machine() == "arm64" and platform.system() == "Darwin"


settings = Settings()
